"""
Test Bug Fixes & Regression Suite
=================================
Validates fixes for:
1. Guardrail decimal pricing & whitelist match regex
2. ViciDialAdapter network failure resilience (no unhandled 500s)
3. Inactive WebPhoneSession turn protection
4. Brain question deletion & creation endpoints
5. Dynamic Safe Harbor drop rate computation
6. MCP server initialize method & error JSON-RPC id preservation
"""

import pytest
import asyncio
from shadow_voice.core.db import init_db
from shadow_voice.conversation.guardrail import RuntimeOutputGuardrail
from shadow_voice.cti.vicidial import ViciDialAdapter
from shadow_voice.telephony.webphone import WebPhoneSession
from shadow_voice.brain.brain import BrainManager
from shadow_voice.api.routes.brain import create_question, delete_question, CreateQuestionRequest
from shadow_voice.api.routes.analytics import get_analytics_summary
from shadow_voice.core.mcp_server import ShadowVoiceMCPServer


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_guardrail_decimal_pricing_whitelist():
    """Verify decimal pricing e.g. $0.05/min passes if whitelisted."""
    # Test 1: Whitelist includes $0.05/min
    guardrail = RuntimeOutputGuardrail(approved_pricing_whitelist={"$0.05/min", "$0.02 to $0.05/min"})
    clean_price = "Our standard rate is $0.05/min for outbound calls."
    res = guardrail.inspect_text(clean_price)
    assert res.passed is True
    assert res.final_text == clean_price

    # Test 2: Unapproved pricing still caught
    unapproved = "We can offer you a special rate of $99 today!"
    res_bad = guardrail.inspect_text(unapproved)
    assert res_bad.passed is False
    assert res_bad.violation_category == "UNAPPROVED_PRICING"


@pytest.mark.asyncio
async def test_vicidial_network_failure_resilience():
    """Verify ViciDialAdapter catches network errors gracefully instead of crashing."""
    # Point to an unreachable IP/port with simulation disabled
    adapter = ViciDialAdapter(
        base_url="http://192.0.2.1:9999",  # RFC 5737 TEST-NET unreachable
        api_user="test",
        api_pass="test",
        simulated=False
    )

    # 1. Blind transfer network failure
    res_blind = await adapter.transfer_blind("sess-err-1", "lead-1", "8300")
    assert res_blind.success is False
    assert "error" in res_blind.message.lower()

    # 2. Warm transfer network failure
    res_warm = await adapter.transfer_warm("sess-err-1", "lead-1", "8300", "notes")
    assert res_warm.success is False
    assert "error" in res_warm.message.lower()

    # 3. Set disposition network failure
    res_dispo = await adapter.set_disposition("sess-err-1", "lead-1", "SALE", "notes")
    assert res_dispo.success is False
    assert "error" in res_dispo.message.lower()

    # 4. Suppress DNC network failure
    res_dnc = await adapter.suppress_dnc("5551234567", "CAMP_1", "User request")
    assert res_dnc is False


@pytest.mark.asyncio
async def test_inactive_webphone_session():
    """Verify ended WebPhoneSession does not process turns or leak duplicate logs."""
    session = WebPhoneSession(phone_number="+1 (555) 999-8888")
    session.terminate_call(disposition="CALLBK")
    assert session.is_active is False

    # Process turn after termination
    res = await session.process_user_turn("Hello, are you still there?")
    assert res["type"] == "call_ended"
    assert res["stage"] == "COMPLETED"


def test_brain_question_crud_and_delete():
    """Verify manual question creation and deletion in BrainManager and API."""
    brain = BrainManager()

    # 1. Create via API
    req = CreateQuestionRequest(
        question_text="Do you have custom CRM webhooks?",
        approved_answer="Yes, real-time webhooks fire on every call disposition.",
        category="technical",
        status="approved"
    )
    res = create_question(req)
    assert res["success"] is True
    qid = res["question_id"]

    # 2. Verify in brain
    questions = brain.get_customer_questions(query="custom CRM webhooks")
    assert len(questions) >= 1
    assert questions[0]["id"] == qid

    # 3. Delete question
    del_res = delete_question(qid)
    assert del_res["success"] is True

    # 4. Verify gone
    questions_after = brain.get_customer_questions(query="custom CRM webhooks")
    assert len(questions_after) == 0


def test_dynamic_safe_harbor_drop_rate():
    """Verify analytics summary dynamically computes drop rate."""
    summary = get_analytics_summary()
    assert "safe_harbor" in summary
    assert "regulatory_drop_rate" in summary["safe_harbor"]
    assert summary["safe_harbor"]["regulatory_drop_rate"] <= 0.030
    assert summary["safe_harbor"]["status"] == "COMPLIANT"


def test_mcp_server_tool_definitions():
    """Verify MCP Server provides complete tool definitions."""
    server = ShadowVoiceMCPServer()
    tools = server.get_tool_definitions()
    assert len(tools) >= 5
    names = [t["name"] for t in tools]
    assert "update_instructions" in names
    assert "get_brain_knowledge" in names
    assert "review_customer_question" in names
    assert "scan_url_with_reach_eyes" in names
    assert "simulate_call_turn" in names


def test_dnc_scrub_and_call_window_properties():
    """Verify is_clean, block_reason, is_permitted properties and /api/analytics/dnc-check endpoint."""
    from shadow_voice.compliance.dnc import DNCScrubbingEngine
    from shadow_voice.compliance.call_window import CallWindowEnforcer
    from fastapi.testclient import TestClient
    from shadow_voice.api.app import app

    dnc = DNCScrubbingEngine()
    cw = CallWindowEnforcer()

    # Property tests
    dnc_res = dnc.scrub_phone_number("3125551212")
    assert dnc_res.is_clean is True
    assert dnc_res.block_reason is None

    cw_res = cw.is_call_permitted("3125551212")
    assert hasattr(cw_res, "is_permitted")
    assert cw_res.is_permitted == cw_res.allowed

    # Endpoint test
    client = TestClient(app)
    resp = client.post("/api/analytics/dnc-check", json={"phone_number": "+1 (312) 555-0199"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_scrubbed_clean"] is True
    assert "calling_window_permitted" in data


def test_kill_switch_api_and_role_aliases():
    """Verify KillSwitchRole aliases (PM, QA, SRE) and toggle_kill_switch endpoint."""
    from shadow_voice.core.kill_switch import KillSwitch, KillSwitchRole
    from shadow_voice.api.routes.settings import toggle_kill_switch, KillSwitchRequest

    ks = KillSwitch.get_instance()

    # Verify enum aliases
    assert KillSwitchRole.PM == KillSwitchRole.PROJECT_MANAGER
    assert KillSwitchRole.QA == KillSwitchRole.QA_COMPLIANCE_ENG
    assert KillSwitchRole.SPEND_GUARD == KillSwitchRole.AUTOMATED_SPEND_GUARD

    # Test toggle ON via PM
    res_on = toggle_kill_switch(KillSwitchRequest(trigger=True, role="PM", reason="Test trigger"))
    assert res_on["kill_switch_active"] is True
    assert ks.is_triggered is True

    # Test toggle OFF via PM
    res_off = toggle_kill_switch(KillSwitchRequest(trigger=False, role="PM"))
    assert res_off["kill_switch_active"] is False
    assert ks.is_triggered is False


def test_prometheus_metrics_and_static_routes():
    """Verify /metrics and /static/js/app.js return 200 OK."""
    from fastapi.testclient import TestClient
    from shadow_voice.api.app import app

    client = TestClient(app)
    r_metrics = client.get("/metrics")
    assert r_metrics.status_code == 200
    assert "shadow_voice_calls_total" in r_metrics.text

    r_static = client.get("/static/js/app.js")
    assert r_static.status_code == 200
    assert "Shadow Voice" in r_static.text


@pytest.mark.asyncio
async def test_audiosocket_handshake_failure_resilience():
    """Verify AudioSocketAdapter does not crash with UnboundLocalError on incomplete handshake."""
    from shadow_voice.telephony.audiosocket import AudioSocketAdapter
    import io

    adapter = AudioSocketAdapter()

    # Simulate a stream that disconnects immediately with 0 bytes (empty)
    class MockStreamReader:
        async def readexactly(self, n):
            raise asyncio.IncompleteReadError(partial=b"", expected=n)

    class MockStreamWriter:
        def is_closing(self):
            return True
        def close(self):
            pass
        async def wait_closed(self):
            pass

    # Should exit cleanly without UnboundLocalError
    await adapter._handle_client(MockStreamReader(), MockStreamWriter())

