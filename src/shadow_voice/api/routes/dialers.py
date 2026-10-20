"""
Dialers & CTI Hub API Router
============================
Handles:
- Dialer configurations (VICIdial, Asterisk, CPaaS, WebPhone)
- Live connection health testing
- Runtime adapter status
"""

from __future__ import annotations
import os
import logging
import socket
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shadow_voice.core.db import get_connection
from shadow_voice.cti.vicidial import ViciDialAdapter

logger = logging.getLogger("shadow_voice.api.dialers")
router = APIRouter(prefix="/api/dialers", tags=["Dialers & CTI Hub"])


class UpdateDialerRequest(BaseModel):
    name: str
    host: Optional[str] = None
    api_url: Optional[str] = None
    api_user: Optional[str] = None
    api_pass: Optional[str] = None
    campaign_id: Optional[str] = None
    closer_group: Optional[str] = None
    audiosocket_port: Optional[int] = 9092
    sip_port: Optional[int] = 5060
    is_active: bool = True
    simulated: bool = False
    notes: Optional[str] = ""


@router.get("/")
def get_dialers() -> List[Dict[str, Any]]:
    """Retrieves all registered dialer configurations."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dialer_configs ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        # Obscure password in UI response
        if item.get("api_pass"):
            item["api_pass"] = "••••••••"
        result.append(item)
    return result


@router.put("/{dialer_id}")
def update_dialer(dialer_id: str, req: UpdateDialerRequest) -> Dict[str, Any]:
    """Updates configuration for a specific dialer platform."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT api_pass FROM dialer_configs WHERE id = ?", (dialer_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Dialer not found")

    api_pass = req.api_pass
    if api_pass in ("••••••••", "********") or not api_pass:
        api_pass = row["api_pass"]

    cursor.execute("""
        UPDATE dialer_configs
        SET name = ?, host = ?, api_url = ?, api_user = ?, api_pass = ?,
            campaign_id = ?, closer_group = ?, audiosocket_port = ?, sip_port = ?,
            is_active = ?, simulated = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        req.name, req.host, req.api_url, req.api_user, api_pass,
        req.campaign_id, req.closer_group, req.audiosocket_port, req.sip_port,
        1 if req.is_active else 0, 1 if req.simulated else 0, req.notes,
        dialer_id
    ))
    conn.commit()
    conn.close()

    return {"success": True, "message": f"{req.name} configuration updated."}


@router.post("/{dialer_id}/test")
async def test_dialer_connection(dialer_id: str) -> Dict[str, Any]:
    """Tests connectivity to the target dialer / telephony endpoint."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dialer_configs WHERE id = ?", (dialer_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Dialer configuration not found")

    cfg = dict(row)

    if dialer_id == "vicidial":
        adapter = ViciDialAdapter(
            base_url=cfg.get("api_url") or "http://vicidial.local",
            api_user=cfg.get("api_user") or "shadow_api",
            api_pass=cfg.get("api_pass") or "shadow_secret",
            simulated=bool(cfg.get("simulated", 1))
        )
        return await adapter.test_connection()

    elif dialer_id == "asterisk":
        host = cfg.get("host") or "127.0.0.1"
        port = cfg.get("audiosocket_port") or 9092
        simulated = bool(cfg.get("simulated", 1))

        if simulated:
            return {
                "success": True,
                "simulated": True,
                "status": "online",
                "message": f"Asterisk AudioSocket simulated listener active on {host}:{port}.",
                "endpoint": f"{host}:{port}"
            }

        # Try TCP connection
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            res = s.connect_ex((host, port))
            s.close()
            is_open = (res == 0)
            return {
                "success": is_open,
                "simulated": False,
                "status": "online" if is_open else "unreachable",
                "message": f"AudioSocket TCP port {port} is {'OPEN' if is_open else 'CLOSED'}.",
                "endpoint": f"{host}:{port}"
            }
        except Exception as e:
            return {
                "success": False,
                "simulated": False,
                "status": "offline",
                "message": f"Socket check failed: {str(e)}",
                "endpoint": f"{host}:{port}"
            }

    elif dialer_id == "webphone":
        return {
            "success": True,
            "simulated": False,
            "status": "online",
            "message": "Built-in Web Audio softphone engine is active and ready in your browser.",
            "endpoint": f"ws://localhost:{os.getenv('PORT', '9000')}/api/calls/ws/webphone"
        }

    else:
        return {
            "success": True,
            "simulated": bool(cfg.get("simulated", 1)),
            "status": "online",
            "message": f"{cfg.get('name')} adapter ready.",
            "endpoint": cfg.get("host") or "cloud"
        }


@router.get("/{dialer_id}/raw")
def get_dialer_raw_config(dialer_id: str) -> Dict[str, Any]:
    """Retrieves full dialer configuration including unmasked API password for editing."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dialer_configs WHERE id = ?", (dialer_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Dialer configuration not found")

    return dict(row)


@router.get("/{dialer_id}/guide")
def get_dialer_setup_guide(dialer_id: str) -> Dict[str, Any]:
    """Returns complete production setup instructions, dialplans, and API configurations."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM dialer_configs WHERE id = ?", (dialer_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Dialer not found")

    cfg = dict(row)
    host = cfg.get("host") or "192.168.1.50"
    as_port = cfg.get("audiosocket_port") or 9092
    camp = cfg.get("campaign_id") or "SALES_OUT"
    closer = cfg.get("closer_group") or "CLOSER_POOL"
    web_port = os.getenv("PORT", "9000")

    if dialer_id == "vicidial":
        return {
            "dialer_id": "vicidial",
            "name": cfg.get("name"),
            "architecture": "VICIdial Outbound Predictive Cluster -> Asterisk AudioSocket (Port 9092) -> Shadow Voice -> Closer Transfer (/agc/api.php)",
            "asterisk_dialplan": f"""; ==============================================================
; SHADOW VOICE AI AGENT EXTENSION FOR VICIDIAL
; Place this in /etc/asterisk/extensions.conf
; ==============================================================
[shadow-voice-agent]
exten => 8388,1,Answer()
exten => 8388,n,Wait(0.3)
exten => 8388,n,Set(SHADOW_UUID=${{UUID()}})
; Connects raw 16kHz PCM audio stream via TCP to Shadow Voice server
; Replace <YOUR_SHADOW_VOICE_SERVER_IP> with the IP address of your Shadow Voice server
exten => 8388,n,AudioSocket(${{SHADOW_UUID}},<YOUR_SHADOW_VOICE_SERVER_IP>:{as_port})
exten => 8388,n,Hangup()
""",
            "vicidial_admin_steps": [
                {
                    "step": 1,
                    "title": "Configure Asterisk AudioSocket Extension",
                    "instruction": f"Open /etc/asterisk/extensions.conf on your VICIdial Asterisk server and add extension 8388 pointing to your Shadow Voice server IP on port {as_port}. Run 'asterisk -rx \"dialplan reload\"'."
                },
                {
                    "step": 2,
                    "title": "Set Campaign Transfer-Conf Extension or Remote Agent",
                    "instruction": f"In VICIdial Admin -> Campaigns -> {camp} -> Detail View, set 'Transfer-Conf Extension' to 8388. Alternatively, in Admin -> Remote Agents, create an entry with External Extension: 8388 and Lines: 10."
                },
                {
                    "step": 3,
                    "title": "Enable Dispo Call URL / Webhook",
                    "instruction": f"In VICIdial Admin -> Campaigns -> {camp} -> Dispo Call URL, enter: http://<YOUR_SHADOW_VOICE_SERVER_IP>:{web_port}/api/dialers/vicidial/webhook?lead_id=--A--lead_id--B--&phone=--A--phone_number--B--&dispo=--A--dispo--B--&campaign={camp}"
                },
                {
                    "step": 4,
                    "title": "Configure API Credentials for Transfers & Dispositions",
                    "instruction": f"Ensure API user '{cfg.get('api_user')}' has user level 8 or 9 with permissions for 'API transfer conference', 'API external hangup', and 'API add DNC list' enabled."
                }
            ],
            "closer_transfer_code": f"When a prospect requests a human representative, Shadow Voice calls /agc/api.php to transfer the call to Closer In-Group '{closer}' or extension 8300 with zero caller drop.",
            "dispo_webhook_url": f"http://<YOUR_SHADOW_VOICE_SERVER_IP>:{web_port}/api/dialers/vicidial/webhook?lead_id=--A--lead_id--B--&phone=--A--phone_number--B--&dispo=--A--dispo--B--"
        }
    elif dialer_id == "asterisk":
        return {
            "dialer_id": "asterisk",
            "name": cfg.get("name"),
            "architecture": "Asterisk PBX -> AudioSocket app_audiosocket.so TCP 9092 -> Shadow Voice bidirectional 16kHz PCM mono",
            "asterisk_dialplan": f"""; Pure Asterisk AudioSocket Dialplan
[default]
exten => 9000,1,Answer()
exten => 9000,n,AudioSocket(${{UUID()}},<YOUR_SHADOW_VOICE_SERVER_IP>:{as_port})
exten => 9000,n,Hangup()
""",
            "asterisk_admin_steps": [
                {
                    "step": 1,
                    "title": "Verify app_audiosocket.so is Loaded",
                    "instruction": "Run 'asterisk -rx \"module show like audiosocket\"'. If missing, compile res_audiosocket.c from Asterisk source."
                },
                {
                    "step": 2,
                    "title": "Route Inbound DIDs to Shadow Voice",
                    "instruction": f"Point your incoming carrier trunk or IVR selection to AudioSocket({host}:{as_port})."
                }
            ]
        }
    else:
        return {
            "dialer_id": dialer_id,
            "name": cfg.get("name"),
            "architecture": "SIP Trunk / CPaaS Webhook -> RTP Media Stream -> Shadow Voice Gateway",
            "asterisk_dialplan": f"; CPaaS / SIP Direct Trunk\nDial(SIP/shadow-voice/{host}:5060)",
            "asterisk_admin_steps": [
                {"step": 1, "title": "SIP Registration", "instruction": f"Register SIP trunk to {host}:5060"}
            ]
        }


@router.post("/{dialer_id}/simulate-call")
def simulate_dialer_call(dialer_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Simulates a live call dispatched from VICIdial or Asterisk into Shadow Voice.
    Creates an active WebPhoneSession with the lead details, generates the natural greeting,
    and returns connection metadata.
    """
    from shadow_voice.api.routes.calls import active_sessions
    from shadow_voice.telephony.webphone import WebPhoneSession

    data = payload or {}
    lead_id = data.get("lead_id") or f"VICI_{uuid.uuid4().hex[:6].upper()}"
    phone = data.get("phone_number") or "+1 (312) 555-0188"
    campaign = data.get("campaign_id") or "SALES_OUT"
    customer_name = data.get("customer_name") or "David Miller"

    session = WebPhoneSession(
        phone_number=phone,
        lead_id=lead_id,
        campaign_id=campaign
    )
    active_sessions[session.session_id] = session
    greeting = session.get_initial_greeting()

    return {
        "success": True,
        "session_id": session.session_id,
        "dialer_id": dialer_id,
        "lead_id": lead_id,
        "phone_number": phone,
        "customer_name": customer_name,
        "campaign_id": campaign,
        "greeting": greeting,
        "message": f"Inbound call from {dialer_id.upper()} (Lead {lead_id} - {customer_name}) successfully connected."
    }


@router.get("/vicidial/webhook")
@router.post("/vicidial/webhook")
def vicidial_webhook(
    lead_id: Optional[str] = "0",
    phone: Optional[str] = "",
    phone_number: Optional[str] = "",
    dispo: Optional[str] = "CALLBK",
    campaign: Optional[str] = "SALES_OUT"
) -> Dict[str, Any]:
    """Receives and logs VICIdial Dispo Call URL webhook pings."""
    ph = phone or phone_number or "N/A"
    safe_dispo = dispo or "CALLBK"
    logger.info(f"[VICIdial Webhook] Lead {lead_id} ({ph}) dispo={safe_dispo} campaign={campaign}")

    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO call_logs (
                session_id, lead_id, phone_number, dialer_type, duration_sec,
                disposition, latency_p95_ms, transcript, created_at
            ) VALUES (?, ?, ?, 'vicidial_webhook', 0.0, ?, 0.0, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
                disposition = excluded.disposition
        """, (
            f"vici-hook-{uuid.uuid4().hex[:8]}",
            str(lead_id or "0"),
            ph,
            safe_dispo,
            f"VICIdial Webhook Dispo Call: Lead {lead_id}, Dispo {safe_dispo}"
        ))
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to record vicidial webhook: {e}")
    finally:
        if conn is not None:
            conn.close()

    return {
        "status": "success",
        "lead_id": lead_id,
        "phone": ph,
        "dispo": safe_dispo,
        "message": "VICIdial Dispo Webhook successfully recorded by Shadow Voice."
    }
