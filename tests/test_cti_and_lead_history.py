"""Tests for CTI Adapters (VICIdial), DNC Read-Back Verification, and Lead History Store."""

import pytest
from shadow_voice.cti.vicidial import ViciDialAdapter
from shadow_voice.cti.lead_history import LeadHistoryStore


@pytest.mark.asyncio
async def test_vicidial_adapter_operations():
    adapter = ViciDialAdapter(simulated=True)

    # Blind transfer
    blind_res = await adapter.transfer_blind("sess-1", "lead-100", "8300")
    assert blind_res.success is True
    assert blind_res.transfer_type == "BLIND"

    # Warm transfer
    warm_res = await adapter.transfer_warm("sess-1", "lead-100", "8301", "Prospect requested tech demo")
    assert warm_res.success is True
    assert warm_res.transfer_type == "WARM"

    # Disposition write-back
    disp_res = await adapter.set_disposition("sess-1", "lead-100", "SALE", "Customer accepted demo")
    assert disp_res.success is True
    assert disp_res.persisted is True


@pytest.mark.asyncio
async def test_vicidial_dnc_suppression_and_readback():
    adapter = ViciDialAdapter(simulated=True)
    phone = "3125550199"

    # Initially not in DNC
    is_suppressed = await adapter.verify_dnc_suppression_state(phone)
    assert is_suppressed is False

    # Suppress number
    success = await adapter.suppress_dnc(phone, "CAMPAIGN_A", "CONSUMER_OPT_OUT")
    assert success is True

    # Confirm read-back verification actually proves suppression
    verified = await adapter.verify_dnc_suppression_state(phone)
    assert verified is True


def test_lead_history_lookup_and_append():
    store = LeadHistoryStore(db_path=":memory:")

    # 1. First contact for unknown lead
    rec_first = store.lookup_lead("LEAD_NEW_999")
    assert rec_first.first_contact is True
    assert rec_first.total_prior_calls == 0

    # 2. Append call outcome
    store.append_call_outcome(
        lead_id="LEAD_NEW_999",
        session_id="sess-turn-1",
        campaign_id="CAMPAIGN_1",
        disposition="CALLBK",
        phone_number="3125550123",
        objection_raised="BUSY_CALLBACK",
        callback_requested=True,
        notes="Requested follow up tomorrow afternoon"
    )

    # 3. Subsequent call: lookup returns prior history
    rec_second = store.lookup_lead("LEAD_NEW_999")
    assert rec_second.first_contact is False
    assert rec_second.total_prior_calls == 1
    assert rec_second.last_disposition == "CALLBK"
    assert rec_second.last_objection == "BUSY_CALLBACK"
    assert rec_second.has_pending_callback is True


def test_lead_history_corrupted_failsafe():
    store = LeadHistoryStore(db_path=":memory:")
    # Query with None / empty
    fallback = store.lookup_lead(None)
    assert fallback.first_contact is True
    assert fallback.lead_id == "UNKNOWN"
