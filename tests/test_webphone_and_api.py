"""
Test Web Phone & Studio API Endpoints
======================================
Validates:
- WebPhoneSession lifecycle & turn-taking
- Section 7.1 Natural Opening audit API
- Cognitive Brain Q&A review API
- Dialer CTI connection testing endpoint
- Call start, turn, and termination endpoints
"""

import pytest

from shadow_voice.core.db import init_db
from shadow_voice.telephony.webphone import WebPhoneSession
from shadow_voice.api.routes.instructions import (
    audit_greeting,
    AuditRequest,
    get_instructions,
    save_instructions,
    InstructionsPayload
)
from shadow_voice.api.routes.brain import (
    get_brain_stats,
    get_customer_questions,
    approve_question,
    ApproveQuestionRequest
)
from shadow_voice.api.routes.dialers import (
    get_dialers,
    test_dialer_connection as api_test_dialer_connection
)
from shadow_voice.api.routes.calls import (
    start_call,
    process_turn,
    end_call,
    StartCallRequest,
    TurnRequest,
    EndCallRequest
)


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


@pytest.mark.asyncio
async def test_webphone_session_lifecycle():
    session = WebPhoneSession(phone_number="+1 (555) 012-3456")
    assert session.is_active is True

    # 1. Opening greeting (Section 7.1 strictly natural human greeting)
    greeting = session.get_initial_greeting()
    assert greeting["type"] == "agent_speech"
    assert "Hi, this is" in greeting["text"]
    assert "automated" not in greeting["text"].lower()
    assert "ai" not in greeting["text"].lower()

    # 2. Turn 1
    t1 = await session.process_user_turn("Hey there. Tell me about your dialer integration.")
    assert t1["type"] == "agent_speech"
    assert t1["latency"]["total_ms"] > 0
    assert len(session.transcripts) >= 2

    # 3. Terminate call
    end_res = session.terminate_call(disposition="SALE")
    assert end_res["disposition"] == "SALE"
    assert session.is_active is False


def test_api_instructions_and_natural_audit():
    # Valid natural opening
    req = AuditRequest(text="Hi, this is Jordan calling from Shadow Voice — do you have a quick minute?")
    data = audit_greeting(req)
    assert data["is_natural"] is True
    assert data["has_banned_ai_disclosure"] is False

    # Robotic opening violation
    req_bad = AuditRequest(text="This is an automated call using artificial intelligence on behalf of Shadow Voice.")
    data_bad = audit_greeting(req_bad)
    assert data_bad["has_banned_ai_disclosure"] is True
    assert data_bad["is_natural"] is False


def test_api_brain_endpoints():
    stats = get_brain_stats()
    assert "total_learned_questions" in stats
    assert "story_bank_receipts_count" in stats

    questions = get_customer_questions(status="all")
    assert isinstance(questions, list)
    assert len(questions) > 0


@pytest.mark.asyncio
async def test_api_dialer_endpoints():
    dialers = get_dialers()
    assert len(dialers) >= 3

    # Test VICIdial simulated connection
    test_res = await api_test_dialer_connection("vicidial")
    assert test_res["success"] is True
    assert test_res["status"] == "online"


@pytest.mark.asyncio
async def test_api_call_start_and_turn():
    # Start call
    start_resp = start_call(StartCallRequest(phone_number="+1 (555) 777-8899"))
    assert start_resp["status"] == "connected"
    sess_id = start_resp["session_id"]
    assert "greeting" in start_resp

    # Send turn
    turn_resp = await process_turn(TurnRequest(
        session_id=sess_id,
        user_text="What dialer systems do you guys support?"
    ))
    assert turn_resp["type"] == "agent_speech"
    assert turn_resp["latency"]["total_ms"] > 0

    # End call
    end_resp = end_call(EndCallRequest(
        session_id=sess_id,
        disposition="CALLBK"
    ))
    assert end_resp["type"] == "call_ended"
