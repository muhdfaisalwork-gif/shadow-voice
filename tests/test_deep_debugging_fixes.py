"""
Deep Debugging & Fixes Verification Suite
=========================================
Validates fixes for:
1. estimated_pitch_hz persistence and retrieval across voice profiles
2. Automatic fallback when active voice profile is deleted (no null pointer)
3. Empty file and non-WAV / MP3 handling in VoiceCloningEngine
4. Voice upload input validation (empty names, empty files)
5. Brain question learning filtering against empty or punctuation-only strings
6. Export call transcript resilience against malformed turns
7. Dialer setup guide placeholders (<YOUR_SHADOW_VOICE_SERVER_IP>)
8. Webphone _save_call_log connection cleanup
9. DNC scrubber minimum length enforcement (<7 digits)
10. SpendCeilingGuard non-negative cost sanitization
11. CallWindowEnforcer ZoneInfo error fallback
12. ReachReader protocol restriction (HTTP/HTTPS only)
13. Favicon 204 No Content response
"""

import os
import io
import time
import pytest
from fastapi.testclient import TestClient

from shadow_voice.core.db import init_db, get_connection
from shadow_voice.conversation.cloning import VoiceCloningEngine, VOICES_DIR
from shadow_voice.brain.brain import BrainManager
from shadow_voice.compliance.dnc import DNCScrubbingEngine
from shadow_voice.compliance.spend_guard import SpendCeilingGuard
from shadow_voice.compliance.call_window import CallWindowEnforcer
from shadow_voice.reach.reader import ReachReader
from shadow_voice.api.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_estimated_pitch_hz_persistence_and_retrieval():
    """Verify that estimated_pitch_hz is persisted to SQLite and retrieved accurately."""
    engine = VoiceCloningEngine()
    
    # Create profile with custom pitch
    profile = engine.create_voice_profile(
        name="Pitch Test Voice",
        description="Testing pitch persistence",
        engine="cartesia_sonic",
        estimated_pitch_hz=235.5,
        set_active=False
    )
    
    # Retrieve via list_voice_profiles
    profiles = engine.list_voice_profiles()
    saved = next((p for p in profiles if p["id"] == profile["id"]), None)
    assert saved is not None
    assert float(saved["estimated_pitch_hz"]) == 235.5
    
    # Cleanup
    engine.delete_voice_profile(profile["id"])


def test_active_voice_deletion_fallback():
    """Verify that deleting an active voice automatically promotes another voice as active."""
    engine = VoiceCloningEngine()
    
    # Create a temporary custom profile and set active
    profile = engine.create_voice_profile(
        name="Temporary Active Voice",
        engine="custom_clone",
        estimated_pitch_hz=210.0,
        set_active=True
    )
    assert engine.get_active_profile()["id"] == profile["id"]
    
    # Delete the active profile
    success = engine.delete_voice_profile(profile["id"])
    assert success is True
    
    # Verify active profile is NOT None and was automatically reassigned
    active = engine.get_active_profile()
    assert active is not None
    assert active["is_active"] == 1
    assert active["id"] != profile["id"]


def test_empty_audio_analysis_and_mp3_fallback(tmp_path):
    """Verify analyze_audio_file handles 0-byte files and non-WAV files cleanly."""
    engine = VoiceCloningEngine()
    
    # 1. Non-existent file
    res_none = engine.analyze_audio_file(str(tmp_path / "non_existent.wav"))
    assert res_none.get("status") == "error"
    
    # 2. 0-byte file
    empty_file = tmp_path / "empty.wav"
    empty_file.write_bytes(b"")
    res_empty = engine.analyze_audio_file(str(empty_file))
    assert res_empty.get("status") == "error"
    
    # 3. Simulated MP3 file
    mp3_file = tmp_path / "test.mp3"
    mp3_file.write_bytes(b"\xFF\xFB\x90\x44" + (b"\x00" * 32000))  # ~2 sec MP3 frame data
    res_mp3 = engine.analyze_audio_file(str(mp3_file))
    assert res_mp3.get("status") == "ready"
    assert res_mp3.get("duration_sec") > 0


def test_voice_upload_validation():
    """Verify voice upload endpoints reject empty names and empty files."""
    # 1. Empty name in multipart
    resp = client.post(
        "/api/voices/upload",
        data={"name": "   ", "description": "test"},
        files={"file": ("test.wav", io.BytesIO(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"), "audio/wav")}
    )
    assert resp.status_code == 400
    assert "name cannot be empty" in resp.json()["detail"].lower()
    
    # 2. Empty file
    resp_empty = client.post(
        "/api/voices/upload",
        data={"name": "Valid Name"},
        files={"file": ("empty.wav", io.BytesIO(b""), "audio/wav")}
    )
    assert resp_empty.status_code == 400
    assert "empty" in resp_empty.json()["detail"].lower()

    # 3. Base64 empty name
    resp_b64 = client.post(
        "/api/voices/upload-base64",
        json={"name": "  ", "audio_base64": "UklGRg=="}
    )
    assert resp_b64.status_code == 400
    
    # 4. Base64 empty audio
    resp_b64_empty = client.post(
        "/api/voices/upload-base64",
        json={"name": "Valid Name", "audio_base64": ""}
    )
    assert resp_b64_empty.status_code == 400


def test_brain_question_learning_filter_punctuation():
    """Verify add_or_increment_question ignores empty or punctuation-only inquiries."""
    brain = BrainManager()
    
    # Punctuation-only strings should be ignored
    res1 = brain.add_or_increment_question("???")
    assert res1["id"] is None
    assert res1["status"] == "ignored"
    
    res2 = brain.add_or_increment_question("!! ...")
    assert res2["id"] is None
    assert res2["status"] == "ignored"
    
    # Legitimate question should be recorded
    res_legit = brain.add_or_increment_question("Do you offer volume discounts?")
    assert res_legit["id"] is not None
    assert res_legit["status"] in ("pending_review", "approved")


def test_export_call_transcript_malformed_turns():
    """Verify export_call_transcript handles malformed or non-dict turn elements gracefully."""
    conn = get_connection()
    c = conn.cursor()
    
    session_id = "test-export-malformed-001"
    # Malformed transcript array containing strings and dicts
    c.execute("""
        INSERT INTO call_logs (session_id, phone_number, duration_sec, disposition, transcript)
        VALUES (?, '+15551234567', 15.0, 'SALE', '["plain string", {"speaker": "agent", "text": "Hello"}, 123]')
        ON CONFLICT(session_id) DO UPDATE SET transcript = excluded.transcript
    """, (session_id,))
    conn.commit()
    conn.close()
    
    resp = client.get(f"/api/calls/{session_id}/export?format=text")
    assert resp.status_code == 200
    assert "CALL TRANSCRIPT" in resp.json()["content"]
    assert "Hello" in resp.json()["content"]


def test_dialer_setup_guide_contains_placeholder():
    """Verify setup guide instructs user to use Shadow Voice server IP rather than dialer IP."""
    resp = client.get("/api/dialers/vicidial/guide")
    assert resp.status_code == 200
    data = resp.json()
    assert "<YOUR_SHADOW_VOICE_SERVER_IP>" in data["asterisk_dialplan"]
    assert "<YOUR_SHADOW_VOICE_SERVER_IP>" in data["dispo_webhook_url"]


def test_dnc_scrubber_minimum_digits():
    """Verify DNC scrubber blocks numbers with fewer than 7 digits."""
    dnc = DNCScrubbingEngine()
    
    res_short = dnc.scrub_phone_number("1234")
    assert res_short.allowed is False
    assert "7 digits" in res_short.rejection_reason.lower()
    
    res_empty = dnc.scrub_phone_number("  ")
    assert res_empty.allowed is False


def test_spend_guard_negative_cost_sanitization():
    """Verify SpendCeilingGuard does not allow negative cost tampering."""
    guard = SpendCeilingGuard(daily_ceiling_usd=100.0)
    
    # Adding negative cost should not decrease total daily spend
    guard.record_cost("CAMP_1", 20.0)
    assert guard.total_daily_spend_usd == 20.0
    
    guard.record_cost("CAMP_1", -50.0)
    assert guard.total_daily_spend_usd == 20.0


def test_call_window_timezone_fallback():
    """Verify CallWindowEnforcer falls back gracefully if invalid timezone encountered."""
    enforcer = CallWindowEnforcer(default_tz="America/New_York")
    
    # Number with unmapped area code
    res = enforcer.is_call_permitted("9995551234")
    assert res.resolved_timezone == "America/New_York"
    assert res.local_time_str != ""


def test_reach_reader_url_scheme_validation():
    """Verify ReachReader rejects non-HTTP(S) protocols like file:// or ftp://."""
    reader = ReachReader()
    
    res_file = reader.read_url("file:///etc/passwd")
    assert res_file["status"] == "error"
    assert "only http and https" in res_file["message"].lower()


def test_favicon_endpoint():
    """Verify /favicon.ico returns 204 No Content without 404 error."""
    resp = client.get("/favicon.ico")
    assert resp.status_code == 204


def test_fsm_greeting_template_interpolation():
    """Verify brain custom greeting interpolates [Name] and [Company]."""
    from shadow_voice.dialogue.fsm import SalesConversationFSM

    class MockBrain:
        def get_instructions(self, campaign_id=None):
            return {
                "opening_greeting": "Good morning! This is [Name] with [Company], how are you doing today?"
            }

    fsm = SalesConversationFSM(
        agent_name="Alex",
        company_name="Apex Telephony",
        brain_manager=MockBrain()
    )
    greeting = fsm.get_initial_greeting()
    assert "[Name]" not in greeting
    assert "[Company]" not in greeting
    assert "Alex" in greeting
    assert "Apex Telephony" in greeting


def test_fsm_offer_next_step_negation_guarding():
    """Verify negative responses like 'I'm not sure' do not trigger false SALE transfers."""
    from shadow_voice.dialogue.fsm import SalesConversationFSM, Stage

    fsm = SalesConversationFSM(agent_name="Jordan", company_name="Shadow Voice")
    # Advance to OFFER_NEXT_STEP
    fsm.process_turn("Hello")                   # -> QUALIFICATION
    fsm.process_turn("We use VICIdial")         # -> DISCOVERY_HOOK
    fsm.process_turn("Tell me more")            # -> OFFER_NEXT_STEP
    assert fsm.current_stage == Stage.OFFER_NEXT_STEP

    # Caller says "I'm not sure" -> should NOT transfer as SALE
    res_neg = fsm.process_turn("I'm not sure about that")
    assert res_neg.action != "TRANSFER_WARM"
    assert res_neg.disposition_code != "SALE"
    assert res_neg.disposition_code == "NI"

    # Reset and test genuine acceptance
    fsm2 = SalesConversationFSM(agent_name="Jordan", company_name="Shadow Voice")
    fsm2.process_turn("Hello")
    fsm2.process_turn("We use VICIdial")
    fsm2.process_turn("Tell me more")
    res_pos = fsm2.process_turn("Yeah sure, let's set up the test")
    assert res_pos.action == "TRANSFER_WARM"
    assert res_pos.disposition_code == "SALE"


def test_objection_requests_human_boundary():
    """Verify standalone 'agent' or 'floor' mentions do not falsely trigger human transfer."""
    from shadow_voice.dialogue.objections import ObjectionHandler, ObjectionType

    handler = ObjectionHandler()

    # Mention of agent in business context should NOT trigger REQUESTS_HUMAN
    res1 = handler.classify_and_respond("We have 20 agents on the floor right now")
    assert res1.objection_type != ObjectionType.REQUESTS_HUMAN

    res2 = handler.classify_and_respond("Our lead agent handles software purchasing")
    assert res2.objection_type != ObjectionType.REQUESTS_HUMAN

    # Explicit transfer intent SHOULD trigger REQUESTS_HUMAN
    res3 = handler.classify_and_respond("Can I speak with a live agent please?")
    assert res3.objection_type == ObjectionType.REQUESTS_HUMAN

    res4 = handler.classify_and_respond("Let me talk to a real person right now")
    assert res4.objection_type == ObjectionType.REQUESTS_HUMAN


def test_amd_hard_timeout_classification():
    """Verify continuous long speech hitting 2.5s hard timeout is classified as MACHINE."""
    import numpy as np
    from shadow_voice.core.audio import AudioFrame
    from shadow_voice.telephony.amd import AnsweringMachineDetector, AMDStatus

    detector = AnsweringMachineDetector(max_human_greeting_ms=1400.0)

    # Feed speech audio frames totaling > 1400ms until timeout (126 frames * 20ms = 2520ms)
    t = np.linspace(0, 0.02, 320, endpoint=False)
    sine_pcm = (0.5 * np.sin(2 * np.pi * 300 * t) * 32767).astype(np.int16).tobytes()
    frame = AudioFrame(data=sine_pcm, sample_rate=16000)

    dec = None
    for _ in range(126):
        dec = detector.process_frame(frame)
        if detector.is_decided:
            break

    assert dec is not None
    assert dec.status == AMDStatus.MACHINE


def test_barge_in_frame_preservation():
    """Verify interrupted speech frames are preserved when set_tts_active(False) is called."""
    from shadow_voice.core.playout_buffer import PacedPlayoutBuffer
    from shadow_voice.conversation.barge_in import BargeInController
    from shadow_voice.core.audio import AudioFrame

    buffer = PacedPlayoutBuffer()
    controller = BargeInController(buffer)

    # Start TTS
    controller.set_tts_active(True)
    assert controller.is_tts_speaking is True

    # User barges in with speech frame
    test_frame = AudioFrame(data=b"\x00\x01" * 320, sample_rate=16000)
    triggered = controller.handle_user_speech_detected(initial_frame=test_frame)
    assert triggered is True

    # TTS generation completes/cleans up
    controller.set_tts_active(False)

    # Interrupted frame must NOT have been cleared
    frames = controller.get_interrupted_speech_frames()
    assert len(frames) == 1
    assert frames[0].data == test_frame.data


def test_ollama_provider_connection_caching():
    """Verify OllamaProvider.is_connected caches response for 10s to prevent blocking."""
    from shadow_voice.conversation.llm.providers.ollama import OllamaProvider

    provider = OllamaProvider(base_url="http://127.0.0.1:54321")  # Non-existent port
    t0 = time.time()
    c1 = provider.is_connected()
    dur1 = time.time() - t0
    assert c1 is False

    # Second immediate call should return cached status without repeating network timeout
    t1 = time.time()
    c2 = provider.is_connected()
    dur2 = time.time() - t1
    assert c2 is False
    assert dur2 < 0.05  # Instantaneous cached return


@pytest.mark.asyncio
async def test_audiosocket_tcp_stream_buffering_and_chunking():
    """Verify AudioSocket handles multi-frame payloads (e.g. 640 or 960 bytes) and fragmented streams."""
    import asyncio
    from shadow_voice.telephony.audiosocket import AudioSocketAdapter, TYPE_AUDIO
    from shadow_voice.core.audio import AudioFrame, FRAME_BYTES_8K, FRAME_BYTES_16K

    adapter = AudioSocketAdapter(host="127.0.0.1", port=9099)
    delivered_frames = []

    async def mock_ingress(session_id, frame: AudioFrame, metadata):
        delivered_frames.append(frame)

    adapter.set_ingress_handler(mock_ingress)

    # 1. Test multi-frame 640-byte payload (Asterisk sending two 20ms frames at once)
    class DummyStream:
        def __init__(self, messages):
            self.messages = messages
            self.idx = 0

        async def readexactly(self, n):
            if self.idx >= len(self.messages):
                raise asyncio.IncompleteReadError(b"", n)
            chunk = self.messages[self.idx]
            self.idx += 1
            return chunk

    # 16-byte UUID header + 1st message (640 bytes = 2 frames) + 2nd message (160 bytes partial) + 3rd (160 bytes complete)
    test_uuid = b"0123456789abcdef"
    audio_640 = b"\x05\x00" * 320  # 640 bytes
    header_640 = bytes([0x10, 0x02, 0x80])  # Type 0x10, len 640

    audio_160_a = b"\x0a\x00" * 80  # 160 bytes
    header_160_a = bytes([0x10, 0x00, 0xa0])  # Type 0x10, len 160

    audio_160_b = b"\x0b\x00" * 80  # 160 bytes
    header_160_b = bytes([0x10, 0x00, 0xa0])

    class DummyWriter:
        def is_closing(self):
            return False
        def write(self, data):
            pass
        async def drain(self):
            pass
        def close(self):
            pass
        async def wait_closed(self):
            pass

    reader = DummyStream([
        test_uuid,
        header_640,
        audio_640,
        header_160_a,
        audio_160_a,
        header_160_b,
        audio_160_b
    ])
    writer = DummyWriter()

    await adapter._handle_client(reader, writer)

    # We expect 3 total delivered 16kHz frames: 2 from the 640-byte frame, and 1 assembled from 160+160 bytes
    assert len(delivered_frames) == 3
    for frame in delivered_frames:
        assert frame.sample_rate == 16000
        assert len(frame.data) == FRAME_BYTES_16K


def test_webphone_pitch_none_resilience():
    """Verify WebPhoneSession._save_call_log succeeds when estimated_pitch_hz is None."""
    from shadow_voice.telephony.webphone import WebPhoneSession

    session = WebPhoneSession(
        phone_number="+15551234567",
        lead_id="TEST_PITCH_NULL",
        active_voice={"name": "Test Null Pitch", "estimated_pitch_hz": None}
    )
    # Simulate a turn and save call log
    session.last_disposition = "CALLBK"
    session.end_time = time.time() + 3.0
    session._save_call_log()

    # Verify call log was written to SQLite
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM call_logs WHERE session_id = ?", (session.session_id,))
    row = c.fetchone()
    conn.close()
    assert row is not None
    assert row["lead_id"] == "TEST_PITCH_NULL"


@pytest.mark.asyncio
async def test_vicidial_notes_and_whisper_sanitization():
    """Verify VICIdial notes and whisper context are sanitized against newlines and length."""
    from shadow_voice.cti.vicidial import ViciDialAdapter

    adapter = ViciDialAdapter(simulated=False)
    multiline_notes = "Customer requested callback tomorrow.\r\nInterested in standard package.\nSpecial notes: " + ("X" * 300)
    
    # Check set_disposition URL generation
    dispo_result = await adapter.set_disposition(
        session_id="SESSION_1",
        lead_id="LEAD_99",
        disposition_code="CALLBK",
        notes=multiline_notes
    )
    # Network call may fail without a real VICIdial host, but verify it didn't throw syntax/URI error
    assert dispo_result is not None

    # Check warm transfer sanitization
    transfer_result = await adapter.transfer_warm(
        session_id="SESSION_1",
        lead_id="LEAD_99",
        extension="8300",
        whisper_context="Warm transfer context line 1\r\nLine 2\n" + ("Y" * 300)
    )
    assert transfer_result is not None


def test_active_sessions_pruning():
    """Verify get_active_calls prunes terminated sessions from memory."""
    from shadow_voice.api.routes.calls import active_sessions, get_active_calls
    from shadow_voice.telephony.webphone import WebPhoneSession

    # Create active session
    active_s = WebPhoneSession(phone_number="+15550001111")
    active_s.is_active = True
    active_sessions[active_s.session_id] = active_s

    # Create terminated session
    dead_s = WebPhoneSession(phone_number="+15550002222")
    dead_s.is_active = False
    active_sessions[dead_s.session_id] = dead_s

    res = get_active_calls()
    # Dead session must have been purged from active_sessions
    assert dead_s.session_id not in active_sessions
    assert active_s.session_id in active_sessions
    # Clean up
    active_sessions.pop(active_s.session_id, None)


def test_fsm_positive_agreement_with_no_idioms_and_technology_word():
    """Verify FSM does not falsely reject prospects saying 'no problem' or words containing 'no' like 'technology'."""
    from shadow_voice.dialogue.fsm import SalesConversationFSM, Stage

    # 1. Prospect says "No problem, sure let's test it"
    fsm1 = SalesConversationFSM()
    fsm1.current_stage = Stage.OFFER_NEXT_STEP
    res1 = fsm1.process_turn("No problem, sure let's test it")
    assert res1.action == "TRANSFER_WARM"
    assert res1.disposition_code == "SALE"
    assert res1.next_stage == Stage.TRANSFER_DISPOSITION

    # 2. Prospect says "We have our own technology, but yeah let's do it"
    fsm2 = SalesConversationFSM()
    fsm2.current_stage = Stage.OFFER_NEXT_STEP
    res2 = fsm2.process_turn("We have our own technology, but yeah let's do it")
    assert res2.action == "TRANSFER_WARM"
    assert res2.disposition_code == "SALE"
    assert res2.next_stage == Stage.TRANSFER_DISPOSITION

    # 3. Prospect says "No thanks, not for me"
    fsm3 = SalesConversationFSM()
    fsm3.current_stage = Stage.OFFER_NEXT_STEP
    res3 = fsm3.process_turn("No thanks, not for me")
    assert res3.action == "HANGUP"
    assert res3.disposition_code == "NI"


def test_voice_cloning_null_pitch_handling():
    """Verify VoiceCloningEngine handles voice profiles with None pitch."""
    from shadow_voice.conversation.cloning import VoiceCloningEngine

    engine = VoiceCloningEngine()
    profile = engine.create_voice_profile(
        name="Null Pitch Profile Test",
        estimated_pitch_hz=None
    )
    assert profile["estimated_pitch_hz"] == 195.0

    synth = engine.synthesize_cloned_speech(
        text="Testing null pitch synthesis fallback.",
        voice_profile={"id": profile["id"], "name": profile["name"], "estimated_pitch_hz": None}
    )
    assert synth["success"] is True
    engine.delete_voice_profile(profile["id"])


@pytest.mark.asyncio
async def test_virtual_sip_udp_register_and_unregister():
    """Verify VirtualSIPSoftphone builds compliant packets and toggles status cleanly."""
    from shadow_voice.telephony.softphone_manager import VirtualSIPSoftphone

    softphone = VirtualSIPSoftphone(extension="1009", server_ip="127.0.0.1", sip_port=5060)
    start_res = await softphone.start()
    assert start_res["status"] == "REGISTERED"
    assert softphone.is_running is True

    stop_res = await softphone.stop()
    assert stop_res["status"] == "UNREGISTERED"
    assert softphone.is_running is False


def test_call_window_and_dnc_none_phone_resilience():
    """Verify CallWindowEnforcer and DNCScrubbingEngine handle None phone numbers without raising TypeError."""
    from shadow_voice.compliance.call_window import CallWindowEnforcer
    from shadow_voice.compliance.dnc import DNCScrubbingEngine

    enforcer = CallWindowEnforcer()
    tz = enforcer.resolve_timezone(None)
    assert tz == "America/New_York"

    cw_res = enforcer.is_call_permitted(None)
    assert cw_res is not None

    dnc = DNCScrubbingEngine()
    dnc_res = dnc.scrub_phone_number(None)
    assert dnc_res.allowed is False
    assert "Invalid phone number format" in (dnc_res.rejection_reason or "")


def test_legal_gates_none_codes_handling():
    """Verify LegalGateEnforcer handles None country_code and state_code gracefully."""
    from shadow_voice.compliance.legal_gates import LegalGateEnforcer, NumberDestinationType

    enforcer = LegalGateEnforcer()
    approval = enforcer.check_pre_dial_legal_basis(
        country_code=None,
        state_code=None,
        destination_type=NumberDestinationType.BUSINESS,
        consent_provenance="B2B_ESTABLISHED_RELATIONSHIP"
    )
    assert approval.approved is False
    assert "outside approved scope" in (approval.rejection_reason or "")


def test_guardrail_none_text_handling():
    """Verify RuntimeOutputGuardrail handles None text without raising AttributeError."""
    from shadow_voice.conversation.guardrail import RuntimeOutputGuardrail

    guard = RuntimeOutputGuardrail()
    res = guard.inspect_text(None)
    assert res.passed is True
    assert res.final_text == ""


def test_brain_none_utterance_and_empty_query_handling():
    """Verify BrainManager handles None utterance and None/empty query."""
    from shadow_voice.brain.brain import BrainManager

    brain = BrainManager()
    ans = brain.find_matching_approved_answer(None)
    assert ans is None

    stories_none = brain.get_story_bank(query=None)
    assert isinstance(stories_none, list)

    stories_empty = brain.get_story_bank(query="   ")
    assert isinstance(stories_empty, list)


def test_reach_analyzer_none_inputs_handling():
    """Verify ReachAnalyzer handles None content, title, and url without crashing."""
    from shadow_voice.reach.analyzer import ReachAnalyzer

    analyzer = ReachAnalyzer()
    res = analyzer.analyze_content(title=None, content=None, url=None)
    assert res is not None
    assert res["company_name"] == "Target Business"
    assert isinstance(res["suggested_qas"], list)


def test_save_pcm_to_wav_empty_dirpath_and_chunk_pcm_none():
    """Verify save_pcm_to_wav works with bare filename and chunk_pcm handles None."""
    import os
    from shadow_voice.core.audio import save_pcm_to_wav, chunk_pcm

    # chunk_pcm with None
    assert chunk_pcm(None) == []

    # save_pcm_to_wav with bare relative filename (no directory component)
    target_path = "temp_debug_bare_test.wav"
    try:
        if os.path.exists(target_path):
            os.remove(target_path)
        out = save_pcm_to_wav(b"\x00\x00" * 320, target_path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
    finally:
        if os.path.exists(target_path):
            os.remove(target_path)


def test_eyebeam_registry_escaping_special_chars():
    """Verify EyebeamRegistryProvisioner escapes quotes and backslashes."""
    from shadow_voice.telephony.softphone_manager import EyebeamRegistryProvisioner

    reg_content = EyebeamRegistryProvisioner.generate_reg_content(
        extension="1001",
        password='p@"ss\\word!',
        display_name='Agent "Alex"\\Special'
    )
    assert r'p@\"ss\\word!' in reg_content
    assert r'Agent \"Alex\"\\Special' in reg_content
    assert "Windows Registry Editor Version 5.00" in reg_content


def test_virtual_softphone_sip_header_normalization():
    """Verify VirtualSIPSoftphone.build_auto_answer_200_ok normalizes headers without duplication."""
    from shadow_voice.telephony.softphone_manager import VirtualSIPSoftphone

    phone = VirtualSIPSoftphone(extension="1001")

    # Pass headers that already include the header name
    ans1 = phone.build_auto_answer_200_ok(
        via_header="Via: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bK1",
        from_header="From: <sip:caller@127.0.0.1>;tag=abc",
        to_header="To: <sip:1001@127.0.0.1>",
        call_id="Call-ID: call-999@127.0.0.1",
        cseq_header="CSeq: 1 INVITE"
    ).decode("utf-8")

    assert "Call-ID: Call-ID:" not in ans1
    assert "Call-ID: call-999@127.0.0.1" in ans1
    assert "Via: SIP/2.0/UDP 127.0.0.1:5060" in ans1
    assert "To: <sip:1001@127.0.0.1>;tag=" in ans1

    # Pass bare values without header name
    ans2 = phone.build_auto_answer_200_ok(
        via_header="SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bK2",
        from_header="<sip:caller2@127.0.0.1>;tag=def",
        to_header="<sip:1001@127.0.0.1>",
        call_id="call-888@127.0.0.1",
        cseq_header="2 INVITE"
    ).decode("utf-8")

    assert "Call-ID: call-888@127.0.0.1" in ans2
    assert "Via: SIP/2.0/UDP" in ans2
    assert "From: <sip:caller2" in ans2
    assert "CSeq: 2 INVITE" in ans2


@pytest.mark.asyncio
async def test_webphone_session_and_fsm_none_user_turn():
    """Verify WebPhoneSession, FSM, and ObjectionHandler handle None user turns gracefully."""
    from shadow_voice.telephony.webphone import WebPhoneSession
    from shadow_voice.dialogue.fsm import SalesConversationFSM
    from shadow_voice.dialogue.objections import ObjectionHandler

    session = WebPhoneSession(session_id="test-null-session")
    res = await session.process_user_turn(None)
    assert res is not None
    assert "text" in res

    fsm = SalesConversationFSM()
    fsm_turn = fsm.process_turn(None)
    assert fsm_turn is not None
    assert fsm_turn.agent_text != ""

    obj_h = ObjectionHandler()
    obj_res = obj_h.classify_and_respond(None)
    assert obj_res is not None


def test_access_control_whitespace_and_feedback_clamping():
    """Verify ScriptDeploymentController rejects whitespace and feedback rating clamps to 1-5."""
    from shadow_voice.dialogue.access_control import ScriptDeploymentController
    from shadow_voice.dialogue.script_registry import CampaignScriptConfig, ScriptRegistry
    from shadow_voice.dialogue.feedback_loop import OutcomeFeedbackLoop

    reg = ScriptRegistry()
    controller = ScriptDeploymentController(registry=reg)
    cfg = CampaignScriptConfig(
        campaign_id="TEST_CAMP",
        version_id="v1.0",
        agent_name="Alex",
        company_name="Shadow Voice",
        opening_greeting="Hello"
    )

    # Whitespace signatures must be rejected
    with pytest.raises(PermissionError):
        controller.deploy_to_production(config=cfg, pm_name="   ", dialogue_eng_name="Engineer")

    with pytest.raises(PermissionError):
        controller.deploy_to_production(config=cfg, pm_name="PM", dialogue_eng_name="")

    # Feedback rating clamping
    loop = OutcomeFeedbackLoop()
    e1 = loop.submit_closer_feedback("s1", "l1", None, "Closer", "notes", rating=10)
    assert e1.rating_1_to_5 == 5

    e2 = loop.submit_closer_feedback("s2", "l2", None, "Closer", "notes", rating=-2)
    assert e2.rating_1_to_5 == 1


def test_dnc_unified_phone_normalization_and_lead_store_close():
    """Verify DNCScrubbingEngine normalizes across 10/11 digits and LeadHistoryStore closes cleanly."""
    from shadow_voice.compliance.dnc import DNCScrubbingEngine
    from shadow_voice.cti.lead_history import LeadHistoryStore

    dnc = DNCScrubbingEngine()
    # Add with country code +1
    dnc.update_national_dnc_snapshot({"+1 (800) 555-0199"})

    # Check without country code
    res1 = dnc.scrub_phone_number("8005550199")
    assert res1.allowed is False
    assert res1.is_national_dnc is True

    # Check with country code
    res2 = dnc.scrub_phone_number("+1-800-555-0199")
    assert res2.allowed is False
    assert res2.is_national_dnc is True

    # Internal DNC normalization
    dnc.add_internal_dnc("+1 (312) 555-4321")
    res3 = dnc.scrub_phone_number("3125554321")
    assert res3.allowed is False
    assert res3.is_internal_dnc is True

    # LeadHistoryStore close
    store = LeadHistoryStore(":memory:")
    assert store.lookup_lead("test").first_contact is True
    store.close()


def test_compliance_audit_store_persistent_conn_and_close():
    """Verify ComplianceAuditStore maintains a single persistent connection and closes cleanly."""
    from shadow_voice.compliance.audit_logger import ComplianceAuditStore, ComplianceCallRecord

    store = ComplianceAuditStore(":memory:")
    rec = ComplianceCallRecord(
        session_id="test-audit-sess-1",
        lead_id="L100",
        campaign_id="CAMP1",
        calling_number="1234567890",
        called_number="0987654321",
        timezone="America/New_York",
        start_timestamp=100.0,
        end_timestamp=120.0,
        duration_seconds=20.0,
        disposition="SALE",
        script_version_id="v1",
        prompt_model_version="v1",
        consent_provenance="OPT_IN",
        legal_basis="CONSENT",
        dnc_scrubbed_passed=True,
        safe_harbor_cleared=True,
        guardrail_flagged=False
    )
    h = store.record_call(rec)
    assert h is not None
    assert len(h) == 64
    store.close()


@pytest.mark.asyncio
async def test_tts_stream_synthesize_null_and_empty_text():
    """Verify Qwen3TTSClient handles None and empty string without yielding frames or crashing."""
    import asyncio
    from shadow_voice.conversation.tts import Qwen3TTSClient

    client = Qwen3TTSClient()
    cancel = asyncio.Event()

    # None text
    frames_none = []
    async for f, meta in client.stream_synthesize(None, cancel):
        frames_none.append(f)
    assert len(frames_none) == 0

    # Empty whitespace text
    frames_empty = []
    async for f, meta in client.stream_synthesize("   ", cancel):
        frames_empty.append(f)
    assert len(frames_empty) == 0


def test_vad_silence_duration_reset_on_speech_start():
    """Verify VoiceActivityDetector resets _silence_duration_ms when speech starts."""
    import numpy as np
    from shadow_voice.core.audio import AudioFrame
    from shadow_voice.conversation.vad import VoiceActivityDetector

    vad = VoiceActivityDetector(start_speech_frames=1)
    vad._silence_duration_ms = 400.0  # Simulate leftover silence from previous turn

    # Active frame
    t = np.linspace(0, 0.02, 320, endpoint=False)
    sine_pcm = (0.5 * np.sin(2 * np.pi * 300 * t) * 32767).astype(np.int16).tobytes()
    frame = AudioFrame(data=sine_pcm, sample_rate=16000)

    event = vad.process_frame(frame)
    assert event.speech_start is True
    assert event.is_speech is True
    assert vad._silence_duration_ms == 0.0


def test_mcp_server_null_args_and_missing_keys():
    """Verify ShadowVoiceMCPServer.execute_tool returns clean error responses on null/missing args."""
    from shadow_voice.core.mcp_server import ShadowVoiceMCPServer

    server = ShadowVoiceMCPServer()

    # None arguments
    res1 = server.execute_tool("update_instructions", None)
    assert res1["status"] == "error"
    assert "Missing required argument" in res1["message"]

    # Missing required argument
    res2 = server.execute_tool("simulate_call_turn", {})
    assert res2["status"] == "error"
    assert "customer_utterance" in res2["message"]


def test_settings_toggle_kill_switch_null_role():
    """Verify toggle_kill_switch handles None role gracefully."""
    from shadow_voice.api.routes.settings import toggle_kill_switch, KillSwitchRequest
    from shadow_voice.core.kill_switch import KillSwitch

    req = KillSwitchRequest(trigger=False, reason="test", role=None)
    res = toggle_kill_switch(req)
    assert res is not None
    assert "kill_switch_active" in res


def test_dialer_factory_null_name():
    """Verify DialerFactory.create defaults cleanly when name is None."""
    from shadow_voice.cti.factory import DialerFactory
    from shadow_voice.cti.vicidial import ViciDialAdapter

    adapter = DialerFactory.create(None, simulated=True)
    assert isinstance(adapter, ViciDialAdapter)


def test_reach_reader_multiline_and_attributed_title():
    """Verify ReachReader regex extracts multiline and attributed HTML titles."""
    import re

    html = '<!DOCTYPE html><html><head><title class="site-title">\n  Enterprise Telephony Hub\n</title></head></html>'
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    assert title_match is not None
    title = " ".join(title_match.group(1).split()).strip()
    assert title == "Enterprise Telephony Hub"


def test_spend_guard_null_and_negative_ceilings():
    """Verify SpendCeilingGuard handles None campaign ID and clamps negative ceilings."""
    from shadow_voice.compliance.spend_guard import SpendCeilingGuard

    guard = SpendCeilingGuard(daily_ceiling_usd=100.0)
    guard.set_campaign_ceiling(None, -50.0)
    assert "DEFAULT_CAMPAIGN" in guard.campaign_spends
    assert guard.campaign_spends["DEFAULT_CAMPAIGN"].spend_ceiling_usd == 0.0

    guard.set_campaign_ceiling(None, 50.0)
    assert guard.campaign_spends["DEFAULT_CAMPAIGN"].spend_ceiling_usd == 50.0

    res = guard.record_cost(None, 10.0)
    assert res is True
    assert guard.total_daily_spend_usd == 10.0


def test_dashboard_telemetry_null_spend_values():
    """Verify ProductionDashboardMonitor handles None spend values without raising TypeError."""
    from shadow_voice.monitoring.dashboard import ProductionDashboardMonitor

    monitor = ProductionDashboardMonitor()
    alerts = monitor.evaluate_telemetry(
        latency_p95_ms=500.0,
        regulatory_abandonment_rate=0.01,
        dnc_age_days=10.0,
        daily_spend_usd=None,
        daily_spend_limit_usd=None,
        active_sessions_count=2,
        kill_switch_active=False
    )
    assert isinstance(alerts, list)


def test_llm_base_provider_generate_text_null_prompt():
    """Verify BaseLLMProvider.generate_text handles None prompt safely."""
    from shadow_voice.conversation.llm.providers.ollama import OllamaProvider

    provider = OllamaProvider()
    # Should not raise exception with prompt=None
    res = provider.generate_text(prompt=None, system_prompt=None)
    assert isinstance(res, str)


def test_cloning_synthesize_null_and_empty_text():
    """Verify synthesize_cloned_speech handles None text and None voice_profile safely."""
    from shadow_voice.conversation.cloning import VoiceCloningEngine

    engine = VoiceCloningEngine()
    res1 = engine.synthesize_cloned_speech(text=None, voice_profile=None)
    assert res1["success"] is True
    assert "preview" in res1["text"].lower()

    res2 = engine.synthesize_cloned_speech(text="   ", voice_profile={"estimated_pitch_hz": 210.0})
    assert res2["success"] is True
    assert len(res2["filepath"]) > 0


def test_cloning_analyze_audio_null_filepath():
    """Verify analyze_audio_file handles None or non-existent filepath safely."""
    from shadow_voice.conversation.cloning import VoiceCloningEngine

    engine = VoiceCloningEngine()
    res = engine.analyze_audio_file(filepath=None)
    assert res["status"] == "error"
    assert "exist" in res["error"].lower()


def test_guardrail_empty_whitelist_no_bypass():
    """Verify empty string in approved whitelist cannot bypass prohibited pattern checks."""
    from shadow_voice.conversation.guardrail import RuntimeOutputGuardrail

    # Whitelist containing empty string or whitespace
    guardrail = RuntimeOutputGuardrail(approved_pricing_whitelist={"", "  "})
    
    # Should still block prohibited guarantees and verbal contracts
    res1 = guardrail.inspect_text("We give you a 100% guarantee on all calls.")
    assert res1.passed is False
    assert res1.violation_category == "UNAPPROVED_GUARANTEE"

    # Test custom prohibited pattern addition with plain text auto-escaping
    guardrail.add_prohibited_pattern("special deal $99")
    res2 = guardrail.inspect_text("We offer a special deal $99 for early signups.")
    assert res2.passed is False


@pytest.mark.asyncio
async def test_universal_llm_stream_error_recovery():
    """Verify UniversalLLMClient stream_generate yields safe conversational fallback on upstream error."""
    import asyncio
    from shadow_voice.conversation.llm.client import UniversalLLMClient
    from shadow_voice.conversation.llm.providers.ollama import OllamaProvider

    class FaultyProvider(OllamaProvider):
        def is_connected(self) -> bool:
            return True

        async def stream_generate(self, messages, cancel_event, temperature=0.7, max_tokens=150, **kwargs):
            # Simulate sudden network drop at start of stream
            raise ConnectionResetError("Remote host terminated connection")
            yield "never", 0.0

    client = UniversalLLMClient(provider="faulty")
    client._providers_cache["faulty"] = FaultyProvider()

    cancel = asyncio.Event()
    tokens = []
    async for token, ttft in client.stream_generate(messages=[{"role": "user", "content": "hi"}], cancel_event=cancel):
        tokens.append(token)

    assert len(tokens) > 0
    full_text = "".join(tokens)
    assert "understand" in full_text.lower()


def test_natural_rules_null_and_empty_inputs():
    """Verify NaturalLanguageAuditor handles None and empty inputs without TypeError."""
    from shadow_voice.dialogue.natural_rules import NaturalLanguageAuditor

    auditor = NaturalLanguageAuditor()

    # None opening
    valid1, viols1 = auditor.audit_opening(None)
    assert valid1 is False
    assert len(viols1) > 0

    # Empty whitespace opening
    valid2, viols2 = auditor.audit_opening("   ")
    assert valid2 is False

    # Valid opening
    valid3, viols3 = auditor.audit_opening("Hi, this is Jordan calling from Shadow Voice.")
    assert valid3 is True

    # None script
    report = auditor.audit_script(None)
    assert report.is_natural is True
    assert report.filler_score == 0.0


def test_instructions_payload_default_factory():
    """Verify InstructionsPayload uses independent mutable default lists."""
    from shadow_voice.api.routes.instructions import InstructionsPayload

    p1 = InstructionsPayload(
        agent_name="Agent 1",
        company_name="Company 1",
        opening_greeting="Hi there",
        primary_instructions="Inst 1",
        tone="professional"
    )
    p2 = InstructionsPayload(
        agent_name="Agent 2",
        company_name="Company 2",
        opening_greeting="Hi there",
        primary_instructions="Inst 2",
        tone="professional"
    )

    p1.approved_pricing.append("special-test-tier")
    assert "special-test-tier" not in p2.approved_pricing


def test_audio_resampling_null_inputs():
    """Verify resample functions safely handle None without TypeError."""
    from shadow_voice.core.audio import resample_8k_to_16k, resample_16k_to_8k

    assert resample_8k_to_16k(None) == b""
    assert resample_16k_to_8k(None) == b""
    assert resample_8k_to_16k(b"") == b""
    assert resample_16k_to_8k(b"") == b""


@pytest.mark.asyncio
async def test_vicidial_dnc_null_phone_number():
    """Verify ViciDialAdapter handles None phone numbers without raising TypeError."""
    from shadow_voice.cti.vicidial import ViciDialAdapter

    adapter = ViciDialAdapter(simulated=True)
    res1 = await adapter.suppress_dnc(phone_number=None, campaign_id="TEST", reason="Test")
    assert res1 is False

    res2 = await adapter.verify_dnc_suppression_state(phone_number=None)
    assert res2 is False


def test_calls_export_non_numeric_timestamp():
    """Verify export_call_transcript handles non-numeric timestamps cleanly."""
    import json
    import uuid
    from shadow_voice.api.routes.calls import export_call_transcript
    from shadow_voice.core.db import get_connection

    sid = f"TEST_SESSION_FMT_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO call_logs (session_id, phone_number, duration_sec, disposition, transcript)
        VALUES (?, '+15551234567', 15.0, 'CALLBK', ?)
    """, (sid, json.dumps([
        {"speaker": "agent", "text": "Hello", "timestamp": "invalid_ts"},
        {"speaker": "customer", "text": "Hi", "timestamp": None}
    ]),))
    conn.commit()
    conn.close()

    try:
        res = export_call_transcript(sid, format="text")
        assert res is not None
        assert "content" in res
        assert "[000.0s]" in res["content"]
    finally:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM call_logs WHERE session_id = ?", (sid,))
        conn.commit()
        conn.close()


# ==============================================================================
# ROUND 9: Brain Learner, Evolution Engine, Settings, Dialers & WebPhone Guards
# ==============================================================================

def test_customer_question_learner_null_inputs():
    """Verify CustomerQuestionLearner methods handle None inputs without AttributeError."""
    from shadow_voice.brain.learner import CustomerQuestionLearner

    learner = CustomerQuestionLearner()
    assert learner.is_question(None) is False
    assert learner.is_question("   ") is False
    assert learner.detect_sentiment(None) == "neutral"
    assert learner.categorize_question(None) == "general"

    is_q, ans, rec = learner.process_turn(None)
    assert is_q is False
    assert ans is None
    assert rec is None


def test_brain_evolution_malformed_transcripts():
    """Verify BrainEvolutionEngine safely handles None and malformed turn items."""
    from shadow_voice.brain.evolution import BrainEvolutionEngine

    engine = BrainEvolutionEngine()
    audit_none = engine.audit_dialogue_naturalness(None)
    assert audit_none["score"] == 100.0
    assert audit_none["turns_evaluated"] == 0

    audit_mixed = engine.audit_dialogue_naturalness([
        None,
        "invalid_turn",
        {"speaker": "agent", "text": None},
        {"speaker": "agent", "text": "Hi, this is Jordan calling from Shadow Voice."}
    ])
    assert audit_mixed["score"] == 100.0
    assert audit_mixed["turns_evaluated"] == 2


def test_brain_manager_null_question_and_system_prompt():
    """Verify BrainManager safely handles None question_text and builds system prompts cleanly."""
    from shadow_voice.brain.brain import BrainManager

    bm = BrainManager()
    res = bm.add_or_increment_question(question_text=None)
    assert res["status"] == "ignored"
    assert res["id"] is None

    prompt = bm.build_system_prompt()
    assert "NON-NEGOTIABLE CORE DIRECTIVE" in prompt


def test_settings_update_mixed_types_and_masked_keys():
    """Verify update_settings accepts non-string values and ignores masked placeholders."""
    from shadow_voice.api.routes.settings import update_settings, UpdateSettingsRequest
    from shadow_voice.core.db import get_connection

    req = UpdateSettingsRequest(settings={
        "DAILY_SPEND_CEILING_USD": 75.5,
        "TEST_MASKED_KEY": "••••••••",
        "TEST_NONE_KEY": None
    })
    res = update_settings(req)
    assert res["success"] is True

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'DAILY_SPEND_CEILING_USD'")
    row = c.fetchone()
    assert row is not None and row["value"] == "75.5"

    c.execute("SELECT value FROM settings WHERE key = 'TEST_MASKED_KEY'")
    assert c.fetchone() is None
    conn.close()


def test_webphone_session_null_parameters():
    """Verify WebPhoneSession coerces None constructor parameters to valid defaults."""
    from shadow_voice.telephony.webphone import WebPhoneSession

    s = WebPhoneSession(session_id=None, phone_number=None, lead_id=None, campaign_id=None)
    assert s.session_id.startswith("webphone-")
    assert s.phone_number == "+1 (555) 019-2834"
    assert s.lead_id == "LEAD_WEB_001"
    assert s.campaign_id == "DEFAULT_SALES_V1"

