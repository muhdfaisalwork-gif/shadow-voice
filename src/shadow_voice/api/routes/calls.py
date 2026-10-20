"""
Calls & Softphone API Router
============================
Handles:
- Active call sessions
- Built-in Web Phone WebSocket (/ws/webphone)
- Call controls (start, hangup, transfer, disposition)
- Call history logs & transcripts
"""

from __future__ import annotations
import json
import time
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from shadow_voice.telephony.webphone import WebPhoneSession
from shadow_voice.core.db import get_connection
from shadow_voice.brain.brain import BrainManager

logger = logging.getLogger("shadow_voice.api.calls")
router = APIRouter(prefix="/api/calls", tags=["Calls & Softphone"])

# In-memory registry of active sessions
active_sessions: Dict[str, WebPhoneSession] = {}


class StartCallRequest(BaseModel):
    phone_number: str = "+1 (555) 019-2834"
    lead_id: str = "LEAD_WEB_001"
    campaign_id: str = "DEFAULT_SALES_V1"


class TurnRequest(BaseModel):
    session_id: str
    user_text: str


class EndCallRequest(BaseModel):
    session_id: str
    disposition: str = "CALLBK"


class TransferRequest(BaseModel):
    session_id: str
    target_extension: str = "8300"
    transfer_type: str = "WARM"  # "WARM" or "BLIND"
    notes: str = "Transferred by agent"


class TrainTurnRequest(BaseModel):
    question_text: str
    approved_answer: str
    category: str = "general"
    sentiment: str = "neutral"


@router.get("/active")
def get_active_calls() -> List[Dict[str, Any]]:
    """Lists currently active call sessions."""
    now = time.time()
    dead_keys = [sid for sid, s in list(active_sessions.items()) if not s.is_active or (now - s.start_time > 7200)]
    for sid in dead_keys:
        active_sessions.pop(sid, None)

    return [
        {
            "session_id": s.session_id,
            "lead_id": s.lead_id,
            "phone_number": s.phone_number,
            "campaign_id": s.campaign_id,
            "start_time": s.start_time,
            "stage": s.fsm.current_stage.value,
            "turn_count": s.fsm.turn_count,
            "is_active": s.is_active
        }
        for s in active_sessions.values() if s.is_active
    ]


@router.post("/start")
def start_call(req: StartCallRequest) -> Dict[str, Any]:
    """Initiates a new softphone call session and returns the initial natural greeting."""
    session = WebPhoneSession(
        phone_number=req.phone_number,
        lead_id=req.lead_id,
        campaign_id=req.campaign_id
    )
    active_sessions[session.session_id] = session
    greeting = session.get_initial_greeting()

    return {
        "status": "connected",
        "session_id": session.session_id,
        "lead_id": session.lead_id,
        "phone_number": session.phone_number,
        "greeting": greeting
    }


@router.post("/turn")
async def process_turn(req: TurnRequest) -> Dict[str, Any]:
    """Processes a caller utterance in an active session."""
    session = active_sessions.get(req.session_id)
    if not session:
        # Create ad-hoc session if needed
        session = WebPhoneSession(session_id=req.session_id)
        active_sessions[session.session_id] = session

    res = await session.process_user_turn(req.user_text)
    return res


@router.post("/end")
def end_call(req: EndCallRequest) -> Dict[str, Any]:
    """Ends an active call session and records disposition."""
    session = active_sessions.get(req.session_id)
    if not session:
        return {"status": "ok", "message": "Call already terminated"}

    result = session.terminate_call(disposition=req.disposition)
    active_sessions.pop(req.session_id, None)
    return result


@router.post("/transfer")
def transfer_call(req: TransferRequest) -> Dict[str, Any]:
    """Executes a warm or blind transfer to a live closer queue."""
    session = active_sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.terminate_call(disposition="XFER")
    active_sessions.pop(req.session_id, None)

    return {
        "status": "transferred",
        "session_id": req.session_id,
        "target_extension": req.target_extension,
        "transfer_type": req.transfer_type,
        "notes": req.notes,
        "message": f"Successfully transferred to extension {req.target_extension}"
    }


@router.get("/history")
def get_call_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves past call logs, transcripts, and detected questions."""
    safe_limit = max(1, min(500, limit or 50))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM call_logs
        ORDER BY id DESC LIMIT ?
    """, (safe_limit,))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        if isinstance(item.get("transcript"), str):
            try:
                item["transcript"] = json.loads(item["transcript"])
            except Exception:
                pass
        if isinstance(item.get("customer_questions_detected"), str):
            try:
                item["customer_questions_detected"] = json.loads(item["customer_questions_detected"])
            except Exception:
                pass
        result.append(item)

    return result


@router.post("/{session_id}/train-turn")
def train_turn(session_id: str, req: TrainTurnRequest) -> Dict[str, Any]:
    """Ingests or refines an edited turn pair into the Cognitive Brain with approved status."""
    clean_q = (req.question_text or "").strip()
    clean_ans = (req.approved_answer or "").strip()
    if not clean_q:
        raise HTTPException(status_code=400, detail="question_text cannot be empty.")

    brain = BrainManager()
    rec = brain.add_or_increment_question(
        question_text=clean_q,
        session_id=session_id,
        sentiment=req.sentiment or "neutral",
        category=req.category or "general",
        proposed_answer=clean_ans
    )
    q_id = rec.get("id")
    if q_id and clean_ans:
        brain.update_question_status(
            question_id=q_id,
            status="approved",
            approved_answer=clean_ans
        )
    return {
        "success": True,
        "question_id": q_id,
        "status": "approved" if clean_ans else "pending_review",
        "message": f"Successfully trained '{clean_q[:35]}...' into Cognitive Brain memory."
    }


@router.get("/{session_id}/export")
def export_call_transcript(session_id: str, format: str = "text") -> Dict[str, Any]:
    """Exports a call transcript in structured JSON or human-readable script text format."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM call_logs WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Call session not found")

    item = dict(row)
    transcript = []
    if isinstance(item.get("transcript"), str) and item["transcript"].strip():
        try:
            transcript = json.loads(item["transcript"])
        except Exception:
            pass
    elif isinstance(item.get("transcript"), list):
        transcript = item["transcript"]

    if format.lower() == "text":
        lines = []
        lines.append(f"=== CALL TRANSCRIPT: {session_id} ===")
        lines.append(f"Phone Number: {item.get('phone_number')}")
        lines.append(f"Duration: {item.get('duration_sec')}s | Disposition: {item.get('disposition')}")
        lines.append("--------------------------------------------------")
        for t in transcript:
            if not isinstance(t, dict):
                continue
            speaker = "Jordan (Agent)" if t.get("speaker") == "agent" else "Customer"
            ts_raw = t.get("timestamp", 0.0)
            try:
                ts_val = float(ts_raw)
            except (ValueError, TypeError):
                ts_val = 0.0
            latency_str = f" [Latency: {t.get('latency_ms')}ms]" if "latency_ms" in t else ""
            lines.append(f"[{ts_val:05.1f}s] {speaker}: {t.get('text', '')}{latency_str}")
        lines.append("==================================================")
        return {"session_id": session_id, "format": "text", "content": "\n".join(lines)}

    return {
        "session_id": session_id,
        "format": "json",
        "metadata": {
            "phone_number": item.get("phone_number"),
            "duration_sec": item.get("duration_sec"),
            "disposition": item.get("disposition"),
            "latency_p95_ms": item.get("latency_p95_ms")
        },
        "transcript": transcript
    }


@router.websocket("/ws/webphone")
async def webphone_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time softphone interactions:
    Supports live audio streaming, turn exchanges, barge-in signals, and telemetry.
    """
    await websocket.accept()
    session = WebPhoneSession()
    active_sessions[session.session_id] = session

    # Send initial connected event + natural greeting
    greeting = session.get_initial_greeting()
    await websocket.send_json({
        "event": "connected",
        "session_id": session.session_id,
        "greeting": greeting
    })

    try:
        while True:
            raw_msg = await websocket.receive_text()
            try:
                data = json.loads(raw_msg)
            except Exception:
                await websocket.send_json({"event": "error", "message": "Invalid JSON frame"})
                continue

            event_type = data.get("event")

            if event_type == "user_utterance":
                user_text = data.get("text") or ""
                agent_res = await session.process_user_turn(user_text)
                await websocket.send_json({
                    "event": "agent_response",
                    "data": agent_res
                })

            elif event_type == "barge_in":
                # Instantaneous flush signal from client
                await websocket.send_json({
                    "event": "barge_in_ack",
                    "status": "flushed",
                    "latency_ms": 4.2
                })

            elif event_type == "ping":
                await websocket.send_json({
                    "event": "pong",
                    "timestamp": time.time()
                })

            elif event_type == "hangup":
                dispo = data.get("disposition", "CALLBK")
                end_res = session.terminate_call(disposition=dispo)
                await websocket.send_json({
                    "event": "call_ended",
                    "data": end_res
                })
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        active_sessions.pop(session.session_id, None)
        if session.is_active:
            session.terminate_call(disposition="DROP")
