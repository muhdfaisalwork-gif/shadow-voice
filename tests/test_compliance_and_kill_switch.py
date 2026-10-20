"""Tests for Compliance Engines, Call Windows, DNC Staleness, Abandonment, and Kill Switch."""

import pytest
import datetime
import os
import tempfile
from shadow_voice.compliance.call_window import CallWindowEnforcer
from shadow_voice.compliance.dnc import DNCScrubbingEngine
from shadow_voice.compliance.abandonment import SafeHarborAbandonmentMonitor
from shadow_voice.compliance.spend_guard import SpendCeilingGuard
from shadow_voice.compliance.audit_logger import ComplianceAuditStore, ComplianceCallRecord
from shadow_voice.core.kill_switch import KillSwitch, KillSwitchRole


def test_call_window_daytime_enforcement():
    enforcer = CallWindowEnforcer()
    ny_phone = "2125550100"  # America/New_York

    # 1. Daytime 2:00 PM EST (19:00 UTC) -> Permitted
    dt_day = datetime.datetime(2026, 9, 18, 19, 0, tzinfo=datetime.timezone.utc)
    res_day = enforcer.is_call_permitted(ny_phone, simulated_now_utc=dt_day)
    assert res_day.allowed is True

    # 2. Nighttime 11:00 PM EST (04:00 UTC next day) -> Blocked
    dt_night = datetime.datetime(2026, 9, 19, 4, 0, tzinfo=datetime.timezone.utc)
    res_night = enforcer.is_call_permitted(ny_phone, simulated_now_utc=dt_night)
    assert res_night.allowed is False
    assert "CALL BLOCKED" in res_night.reason


def test_national_dnc_staleness_gate():
    dnc_engine = DNCScrubbingEngine()
    test_number = "3125550111"

    # Fresh snapshot (age = 5 days) -> Allowed
    now = 1700000000.0
    dnc_engine.national_dnc_last_updated = now - (5 * 86400.0)
    res_fresh = dnc_engine.scrub_phone_number(test_number, current_time=now)
    assert res_fresh.allowed is True
    assert res_fresh.national_dnc_stale is False

    # Stale snapshot (age = 35 days > 31 days) -> CRITICAL BLOCK!
    dnc_engine.national_dnc_last_updated = now - (35 * 86400.0)
    res_stale = dnc_engine.scrub_phone_number(test_number, current_time=now)
    assert res_stale.allowed is False
    assert res_stale.national_dnc_stale is True
    assert "exceeds 31-day legal limit" in res_stale.rejection_reason


def test_internal_and_state_dnc():
    dnc_engine = DNCScrubbingEngine()
    dnc_engine.national_dnc_last_updated = 1700000000.0
    now = 1700000000.0

    # Add Internal DNC
    dnc_engine.add_internal_dnc("4155550122")
    res_int = dnc_engine.scrub_phone_number("4155550122", current_time=now)
    assert res_int.allowed is False
    assert res_int.is_internal_dnc is True

    # Add State DNC (FL)
    dnc_engine.add_state_dnc("FL", {"3055550133"})
    res_state = dnc_engine.scrub_phone_number("3055550133", state="FL", current_time=now)
    assert res_state.allowed is False
    assert res_state.is_state_dnc is True


def test_regulatory_abandonment_vs_technical_failures():
    monitor = SafeHarborAbandonmentMonitor()

    # 1. Record technical carrier disconnects (SIP 503)
    monitor.record_call_attempt()
    monitor.record_technical_failure("SIP_503_SERVICE_UNAVAILABLE")

    # Technical failure rate > 0, but regulatory abandonment rate MUST be 0!
    assert monitor.metrics.technical_failure_rate > 0.0
    assert monitor.metrics.regulatory_abandonment_rate == 0.0

    # 2. Record live human connected within safe harbor (< 2.0s)
    monitor.record_call_attempt()
    safe = monitor.record_live_answer(time_to_connect_audio_ms=1450.0, is_human=True)
    assert safe is True
    assert monitor.metrics.regulatory_abandoned_calls == 0

    # 3. Record live human connected AFTER 2.0s (> 2000ms safe harbor breached)
    monitor.record_call_attempt()
    breached = monitor.record_live_answer(time_to_connect_audio_ms=2800.0, is_human=True)
    assert breached is False
    assert monitor.metrics.regulatory_abandoned_calls == 1
    assert monitor.metrics.regulatory_abandonment_rate == 0.5  # 1 of 2 human answers


def test_spend_ceiling_guard_kill_switch_trigger():
    ks = KillSwitch.reset_for_test()
    guard = SpendCeilingGuard(daily_ceiling_usd=100.0, kill_switch=ks)
    assert ks.can_dial() is True

    # Add allowable spend
    guard.record_cost("CAMPAIGN_A", 50.0)
    assert ks.can_dial() is True

    # Breach ceiling
    guard.record_cost("CAMPAIGN_A", 60.0)  # Total 110.0 >= 100.0
    assert ks.is_triggered is True
    assert ks.can_dial() is False
    assert "spend limit reached" in ks.get_status().reason


def test_kill_switch_session_registration_and_wind_down():
    ks = KillSwitch.reset_for_test()
    assert ks.register_session("sess-active-1") is True
    assert ks.register_session("sess-active-2") is True

    # Pull kill switch
    status = ks.trigger(KillSwitchRole.PROJECT_MANAGER, "Carrier attestation inspection")
    assert status.is_active is True
    assert status.active_calls_at_trigger == 2

    # New dial attempt is immediately REJECTED
    assert ks.register_session("sess-new-attempt") is False

    # Existing calls wind down cleanly
    ks.unregister_session("sess-active-1")
    ks.unregister_session("sess-active-2")
    assert ks.get_status().remaining_active_calls == 0


def test_compliance_audit_store_hash_chain_and_backup():
    audit_store = ComplianceAuditStore(db_path=":memory:")
    rec = ComplianceCallRecord(
        session_id="sess-audit-1",
        lead_id="LEAD_777",
        campaign_id="CAMP_1",
        calling_number="18005550100",
        called_number="13125550199",
        timezone="America/Chicago",
        start_timestamp=1700000000.0,
        end_timestamp=1700000045.0,
        duration_seconds=45.0,
        disposition="SALE",
        script_version_id="v2.1.0-pinned",
        prompt_model_version="deepgram-nova3+gpt4o+qwen3tts",
        consent_provenance="WEB_FORM_OPT_IN_2026",
        legal_basis="TCPA_EXPRESS_WRITTEN_CONSENT",
        dnc_scrubbed_passed=True,
        safe_harbor_cleared=True,
        guardrail_flagged=False
    )
    h1 = audit_store.record_call(rec)
    assert h1 is not None
    assert len(h1) == 64  # SHA-256

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        backup_path = tf.name

    try:
        count = audit_store.export_backup(backup_path)
        assert count == 1
        assert audit_store.verify_backup_integrity(backup_path) is True
    finally:
        if os.path.exists(backup_path):
            os.remove(backup_path)
