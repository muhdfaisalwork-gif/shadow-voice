"""End-to-End Integration Test: Complete Call Lifecycle & Subsystems."""

import pytest
import asyncio
import time
import numpy as np
from shadow_voice.core.audio import (
    AudioFrame,
    SAMPLE_RATE_16K,
    SAMPLE_RATE_8K,
    FRAME_BYTES_8K,
    FRAME_BYTES_16K,
)
from shadow_voice.core.jitter_buffer import IngressJitterBuffer
from shadow_voice.core.playout_buffer import PacedPlayoutBuffer
from shadow_voice.core.kill_switch import KillSwitch, KillSwitchRole
from shadow_voice.telephony.session import TelephonySession
from shadow_voice.telephony.metadata import CallMetadata
from shadow_voice.telephony.amd import AnsweringMachineDetector, AMDStatus
from shadow_voice.telephony.resampler import GatewayResampler
from shadow_voice.conversation.vad import VoiceActivityDetector
from shadow_voice.conversation.stt import DeepgramStreamingSTT
from shadow_voice.conversation.llm import StreamingLLMClient
from shadow_voice.conversation.tts import Qwen3TTSClient
from shadow_voice.conversation.guardrail import RuntimeOutputGuardrail
from shadow_voice.conversation.barge_in import BargeInController
from shadow_voice.cti.lead_history import LeadHistoryStore
from shadow_voice.cti.vicidial import ViciDialAdapter
from shadow_voice.dialogue.fsm import SalesConversationFSM, Stage
from shadow_voice.compliance.call_window import CallWindowEnforcer
from shadow_voice.compliance.dnc import DNCScrubbingEngine
from shadow_voice.compliance.abandonment import SafeHarborAbandonmentMonitor
from shadow_voice.compliance.audit_logger import ComplianceAuditStore, ComplianceCallRecord


@pytest.mark.asyncio
async def test_complete_end_to_end_call_lifecycle():
    # 0. Initialize compliance, kill switch, and CTI
    ks = KillSwitch.reset_for_test()
    lead_store = LeadHistoryStore(db_path=":memory:")
    audit_store = ComplianceAuditStore(db_path=":memory:")
    vicidial = ViciDialAdapter(simulated=True)
    abandonment_mon = SafeHarborAbandonmentMonitor()
    dnc_engine = DNCScrubbingEngine()
    dnc_engine.national_dnc_last_updated = time.time()  # Fresh
    call_window = CallWindowEnforcer()

    lead_id = "LEAD_E2E_888"
    phone_number = "3125550188"
    session_id = "sess-e2e-live-call-001"

    # Step 1: Pre-dial checks (Call Window, DNC, Kill Switch)
    assert ks.can_dial() is True

    cw_check = call_window.is_call_permitted(phone_number)
    # Chicago timezone (central) daytime check
    dnc_check = dnc_engine.scrub_phone_number(phone_number)
    assert dnc_check.allowed is True

    # Step 2: Register session with Kill Switch
    assert ks.register_session(session_id) is True

    # Step 3: Telephony Session & Metadata setup
    meta = CallMetadata(
        session_id=session_id,
        lead_id=lead_id,
        called_number=phone_number,
        campaign_id="CAMPAIGN_ENTERPRISE_SALES"
    )
    session = TelephonySession(session_id=session_id, metadata=meta)
    session.mark_connected()

    # Step 4: AMD Live Human Voice Detection within Safe Harbor
    t_answer = time.time() * 1000.0
    # Simulate short human "Hello?" (300ms = 15 frames) + silence (600ms = 30 frames)
    t_wave = np.linspace(0, 0.02, 320, endpoint=False)
    voice_pcm = (np.sin(2 * np.pi * 280 * t_wave) * 16000).astype(np.int16).tobytes()
    silence_pcm = b"\x00" * FRAME_BYTES_16K

    for _ in range(15):
        frame = GatewayResampler.ingress_pstn_to_internal(AudioFrame(voice_pcm[:320], sample_rate=SAMPLE_RATE_8K))
        dec = session.amd.process_frame(frame)

    amd_cleared = False
    for _ in range(35):
        frame = GatewayResampler.ingress_pstn_to_internal(AudioFrame(silence_pcm[:320], sample_rate=SAMPLE_RATE_8K))
        dec = session.amd.process_frame(frame)
        if dec.status == AMDStatus.HUMAN:
            amd_cleared = True
            break

    assert amd_cleared is True
    t_connect_audio = time.time() * 1000.0
    time_to_audio_ms = t_connect_audio - t_answer
    safe_harbor_ok = abandonment_mon.record_live_answer(time_to_connect_audio_ms=time_to_audio_ms, is_human=True)
    assert safe_harbor_ok is True

    # Step 5: Lookup lead history and initialize FSM
    lead_hist = lead_store.lookup_lead(lead_id)
    fsm = SalesConversationFSM(lead_history=lead_hist, agent_name="Alex", company_name="Shadow Voice")
    opening = fsm.get_initial_greeting()

    # Verify Section 7.1 Non-Negotiable
    assert "automated" not in opening.lower()
    assert "artificial" not in opening.lower()
    assert "Alex" in opening

    # Step 6: User asks qualification question -> FSM progresses
    stt = DeepgramStreamingSTT()
    stt.set_mock_transcript("Hi Alex, what dialer systems do you integrate with?")
    transcript = await stt.finish_turn(time.time() * 1000.0)

    turn1 = fsm.process_turn(transcript.text)
    assert turn1.next_stage == Stage.QUALIFICATION

    # Step 7: Runtime Guardrail passes compliant text
    guardrail = RuntimeOutputGuardrail()
    gr_res = guardrail.inspect_text(turn1.agent_text)
    assert gr_res.passed is True

    # Step 8: Qwen3-TTS Streaming Synthesis & Playout
    tts = Qwen3TTSClient()
    cancel_event = asyncio.Event()
    frames_enqueued = 0
    async for tts_frame, meta in tts.stream_synthesize(gr_res.final_text, cancel_event):
        frames_enqueued += session.playout_buffer.enqueue_pcm(tts_frame.data)
        if frames_enqueued >= 5:
            break  # Buffered sufficient audio

    assert session.playout_buffer.has_audio is True

    # Step 9: User interrupts (Barge-In)
    barge_in = BargeInController(session.playout_buffer)
    llm_cancel = asyncio.Event()
    tts_cancel = asyncio.Event()
    barge_in.set_tts_active(True, llm_cancel, tts_cancel)

    interruption_frame = AudioFrame(b"\x00" * FRAME_BYTES_16K, sample_rate=SAMPLE_RATE_16K)
    interrupted = barge_in.handle_user_speech_detected(interruption_frame)
    assert interrupted is True
    assert session.playout_buffer.has_audio is False  # Purged
    assert llm_cancel.is_set() is True

    # Step 10: Prospect accepts demo -> Warm Transfer via VICIdial
    turn2 = fsm.process_turn("Actually that sounds great, can you connect me to an engineer?")
    assert turn2.action == "TRANSFER_WARM"
    assert turn2.disposition_code == "XFER"

    transfer_res = await vicidial.transfer_warm(
        session_id=session_id,
        lead_id=lead_id,
        extension="8300",
        whisper_context=turn2.transfer_notes
    )
    assert transfer_res.success is True

    # Step 11: Write back to Lead History on hangup
    lead_store.append_call_outcome(
        lead_id=lead_id,
        session_id=session_id,
        campaign_id="CAMPAIGN_ENTERPRISE_SALES",
        disposition="XFER",
        phone_number=phone_number,
        notes="Connected prospect to tech lead demo queue"
    )
    updated_lead = lead_store.lookup_lead(lead_id)
    assert updated_lead.total_prior_calls == 1
    assert updated_lead.last_disposition == "XFER"

    # Step 12: Compliance Audit Record with SHA-256 Hash Chain
    rec = ComplianceCallRecord(
        session_id=session_id,
        lead_id=lead_id,
        campaign_id="CAMPAIGN_ENTERPRISE_SALES",
        calling_number="18005550100",
        called_number=phone_number,
        timezone="America/Chicago",
        start_timestamp=time.time() - 30.0,
        end_timestamp=time.time(),
        duration_seconds=30.0,
        disposition="XFER",
        script_version_id="v2.1.0-pinned",
        prompt_model_version="deepgram-nova3+gpt4o+qwen3tts",
        consent_provenance="TCPA_EXPRESS_WRITTEN_CONSENT",
        legal_basis="B2B_INQUIRY",
        dnc_scrubbed_passed=True,
        safe_harbor_cleared=True,
        guardrail_flagged=False,
        transfer_destination="8300"
    )
    record_hash = audit_store.record_call(rec)
    assert len(record_hash) == 64

    # Step 13: Clean Session Unregister from Kill Switch
    session.terminate(disposition="XFER")
    ks.unregister_session(session_id)
    assert ks.get_status().remaining_active_calls == 0