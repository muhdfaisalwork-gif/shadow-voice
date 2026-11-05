"""
Deep Debugging Audit & Edge Case Verification (Round 10)
========================================================
Verifies:
1. NLMS Echo Canceller odd-byte and empty buffer safety, numerical stability
2. Audio DSP Masterer odd-byte, 1-byte, silent, and small array resilience
3. Pure-NumPy lin2ulaw odd-byte alignment and iter_frames frame_bytes <= 0 safety
4. Text Normalizer millions/billions recursion ($1,000,000, $50,000,000), clock time dot handling
5. SSML-Lite pause spacing ([pause 300 ms]) and duration clamping [10ms, 5000ms]
6. VoiceStudio client URL stripping, null text guards, and voice design defaults
7. WebPhone session repeated termination idempotence and mic audio odd-byte safety
8. Calls API REST supervisor takeover endpoint POST /api/calls/{session_id}/takeover
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from shadow_voice.api.app import app
from shadow_voice.core.aec import NlmsEchoCanceller
from shadow_voice.core.dsp import AudioDSPMasterer
from shadow_voice.core.audio import lin2ulaw, ulaw2lin, iter_frames
from shadow_voice.conversation.normalizer import TelephonyTextNormalizer, number_to_words
from shadow_voice.conversation.ssml import parse_ssml_lite, strip_ssml_lite
from shadow_voice.conversation.voicestudio_client import VoiceStudioClient
from shadow_voice.telephony.webphone import WebPhoneSession


client = TestClient(app)


def test_aec_odd_byte_and_empty_buffer_safety():
    """Verifies that NlmsEchoCanceller never crashes on odd byte lengths or empty buffers."""
    aec = NlmsEchoCanceller(sample_rate=16000, filter_taps=128)

    # Empty and 1-byte buffers
    aec.push_far_end(b"")
    aec.push_far_end(b"\x01")
    assert aec.process_near_end(b"") == b""
    assert aec.process_near_end(b"\x01") == b"\x01"

    # Odd-length buffers (e.g. 641 bytes)
    odd_far = bytes(641)
    aec.push_far_end(odd_far)  # Should not raise ValueError

    odd_near = bytes(641)
    cleaned = aec.process_near_end(odd_near)
    assert len(cleaned) in (640, 641)

    # Reset
    aec.reset()
    assert aec.frames_processed == 0


def test_dsp_odd_byte_and_tiny_buffer_safety():
    """Verifies AudioDSPMasterer handles odd-length, 1-byte, and tiny buffers safely."""
    dsp = AudioDSPMasterer()

    # Empty and 1-byte
    assert dsp.process_pcm(b"") == b""
    assert dsp.process_pcm(b"\x01") == b"\x01"

    # Odd-length buffer (e.g. 301 bytes)
    odd_pcm = bytes(301)
    out = dsp.process_pcm(odd_pcm, preset="broadcast")
    assert len(out) == 300  # Safely truncated to 16-bit alignment

    # All-zero silence buffer
    silent_pcm = bytes(640)
    out_silent = dsp.process_pcm(silent_pcm, preset="broadcast")
    assert len(out_silent) == 640


def test_lin2ulaw_odd_bytes_and_iter_frames_edge_cases():
    """Verifies lin2ulaw handles odd byte buffers and iter_frames handles non-positive frame_bytes."""
    # Odd byte sequence in lin2ulaw
    odd_bytes = b"\x00\x01\x02\x03\x04"
    u = lin2ulaw(odd_bytes)
    assert len(u) == 2  # Truncates trailing byte and encodes 2 samples

    # Empty bytes
    assert lin2ulaw(b"") == b""
    assert lin2ulaw(b"\x00") == b""

    # iter_frames with invalid or zero frame_bytes
    sample_ulaw = bytes(100)
    frames_zero = list(iter_frames(sample_ulaw, frame_bytes=0))
    assert len(frames_zero) == 100  # Clamped to minimum 1 byte per frame

    frames_neg = list(iter_frames(sample_ulaw, frame_bytes=-10))
    assert len(frames_neg) == 100


def test_text_normalizer_millions_and_billions():
    """Verifies millions and billions verbalization in currency and number_to_words."""
    norm = TelephonyTextNormalizer()

    # One million dollars
    assert norm.normalize("The enterprise contract is $1,000,000.") == "The enterprise contract is one million dollars."

    # Multi-million dollars
    assert norm.normalize("Funding was $50,000,000.") == "Funding was fifty million dollars."

    # Billions
    assert number_to_words(1_000_000_000) == "one billion"
    assert number_to_words(2_500_000_000) == "two billion five hundred million"


def test_text_normalizer_clock_times_with_periods():
    """Verifies clock time normalization when followed by punctuation dots."""
    norm = TelephonyTextNormalizer()

    # Time with trailing dot from sentence
    res = norm.normalize("We can meet at 2:30 pm.")
    assert "two thirty p.m." in res

    # Time with dots in a.m.
    res2 = norm.normalize("Call scheduled for 9:15 a.m.")
    assert "nine fifteen a.m." in res2


def test_ssml_pause_spacing_and_duration_bounds():
    """Verifies pause tags with spacing before ms and duration clamping."""
    # Space before ms
    text = "Hello [pause 300 ms] world."
    segments = parse_ssml_lite(text)
    assert any(s.pause_ms == 300 for s in segments)

    # Oversized pause duration clamped to 5000ms
    text_huge = "Wait [pause 99999ms] now."
    segments_huge = parse_ssml_lite(text_huge)
    assert any(s.pause_ms == 5000 for s in segments_huge)

    # Undersized pause duration clamped to 10ms
    text_tiny = "Wait [pause 2ms] now."
    segments_tiny = parse_ssml_lite(text_tiny)
    assert any(s.pause_ms == 10 for s in segments_tiny)


def test_voicestudio_client_input_sanitization():
    """Verifies VoiceStudioClient sanitizes URLs, null texts, and defaults."""
    # Whitespace and trailing slashes in base_url
    client_vs = VoiceStudioClient(base_url="  http://localhost:3900///  ", timeout=0.0)
    assert client_vs.base_url == "http://localhost:3900"
    assert client_vs.timeout >= 0.1

    # Null / empty text in generate_speech returns None
    assert client_vs.generate_speech(None) is None
    assert client_vs.generate_speech("   ") is None

    # Empty description in design_voice uses safe defaults
    res = client_vs.design_voice(None, None)
    assert res["success"] is False
    assert "fallback_customvoice" in res["voice_id"]


def test_webphone_repeated_termination_idempotence():
    """Verifies that calling terminate_call multiple times does not corrupt call duration."""
    session = WebPhoneSession(session_id="test-term-idempotence")
    assert session.is_active is True

    # First termination
    res1 = session.terminate_call(disposition="SALE")
    assert res1["disposition"] == "SALE"
    initial_dur = res1["duration_sec"]
    first_end_time = session.end_time
    assert first_end_time is not None

    # Second termination should keep initial end_time
    res2 = session.terminate_call(disposition="SALE")
    assert session.end_time == first_end_time
    assert res2["duration_sec"] == initial_dur


def test_calls_api_supervisor_takeover_endpoint():
    """Verifies POST /api/calls/{session_id}/takeover toggles takeover status."""
    # 1. Start a call
    start_resp = client.post("/api/calls/start", json={
        "phone_number": "+1 (555) 019-7777",
        "lead_id": "LEAD_TAKEOVER_TEST",
        "campaign_id": "DEFAULT_SALES_V1"
    })
    assert start_resp.status_code == 200
    session_id = start_resp.json()["session_id"]

    # 2. Toggle takeover ON
    takeover_on = client.post(f"/api/calls/{session_id}/takeover", json={"enabled": True})
    assert takeover_on.status_code == 200
    assert takeover_on.json()["is_takeover"] is True

    # 3. Process turn during takeover
    turn_resp = client.post("/api/calls/turn", json={
        "session_id": session_id,
        "user_text": "Is this an automated voice?"
    })
    assert turn_resp.status_code == 200
    turn_data = turn_resp.json()
    assert turn_data["stage"] == "AGENT_TAKEOVER"
    assert turn_data["text"] == "[Live Agent Speaking]"

    # 4. Toggle takeover OFF
    takeover_off = client.post(f"/api/calls/{session_id}/takeover", json={"enabled": False})
    assert takeover_off.status_code == 200
    assert takeover_off.json()["is_takeover"] is False

    # 5. Clean up call
    end_resp = client.post(f"/api/calls/{session_id}/end", json={"disposition": "QUALIFIED"})
    assert end_resp.status_code == 200
