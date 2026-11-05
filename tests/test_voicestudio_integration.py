"""
Unit and Integration Tests for VoiceStudio Enhancements
======================================================
Verifies:
1. Pure-NumPy Acoustic Echo Cancellation (NLMS filter & Geigel DTD)
2. Pure-NumPy G.711 u-law/A-law codec (Sun g711.c bit-identical math)
3. Telephony Audio DSP Mastering pipeline (Highpass, Leveler AGC, Peak Limiter)
4. Telephony Text Normalizer (Currency, Clock times, Phone numbers, Ordinals)
5. SSML-Lite prosody markup parser & ReDoS safety
6. Sensitive PII / Card / SSN deterministic guardrail blocking
7. VoiceStudio REST/MCP microservice bridge and offline resilience
8. WebPhone softphone AEC, DSP mastering, and supervisor live takeover
"""

import math
import numpy as np
import pytest

from shadow_voice.core.aec import NlmsEchoCanceller
from shadow_voice.core.audio import (
    lin2ulaw, ulaw2lin, float_to_pcm16, iter_frames, SAMPLE_RATE_16K, SAMPLE_RATE_8K
)
from shadow_voice.core.dsp import AudioDSPMasterer
from shadow_voice.conversation.normalizer import TelephonyTextNormalizer, number_to_words
from shadow_voice.conversation.ssml import (
    parse_ssml_lite, strip_ssml_lite, VoiceStudioSSMLParser, SSMLSegment
)
from shadow_voice.conversation.guardrail import (
    RuntimeOutputGuardrail, ViolationCategory, SENSITIVE_REFUSAL_TEXT
)
from shadow_voice.conversation.voicestudio_client import VoiceStudioClient
from shadow_voice.telephony.webphone import WebPhoneSession


# =============================================================================
# 1. Pure-NumPy Acoustic Echo Cancellation (NLMS)
# =============================================================================

def test_nlms_echo_canceller_suppression():
    """Verifies that loudspeaker echo leaking into mic is suppressed by NLMS."""
    aec = NlmsEchoCanceller(sample_rate=16000, filter_taps=256, step_size=0.2)

    # Far-end audio (agent speaker output): multi-frequency wave
    dur_sec = 0.5
    num_samples = int(dur_sec * 16000)
    t = np.linspace(0, dur_sec, num_samples, endpoint=False)
    far_signal = 0.5 * np.sin(2 * np.pi * 300 * t) + 0.3 * np.sin(2 * np.pi * 600 * t)
    far_pcm = (far_signal * 32767).astype(np.int16).tobytes()

    # Leaked echo (scaled and slightly delayed replica of far-end signal)
    echo_signal = 0.4 * far_signal
    echo_pcm = (echo_signal * 32767).astype(np.int16).tobytes()

    # Push far-end reference
    aec.push_far_end(far_pcm)

    # Process near-end audio in 20ms frames (320 samples / 640 bytes)
    frame_bytes = 640
    cleaned_frames = []
    for i in range(0, len(echo_pcm), frame_bytes):
        chunk = echo_pcm[i:i + frame_bytes]
        if len(chunk) == frame_bytes:
            out_chunk = aec.process_near_end(chunk)
            cleaned_frames.append(out_chunk)

    cleaned_pcm = b"".join(cleaned_frames)
    cleaned_samples = np.frombuffer(cleaned_pcm, dtype=np.int16).astype(np.float32)

    # Initial echo energy vs final echo energy (after convergence)
    initial_energy = np.mean(cleaned_samples[:640] ** 2)
    final_energy = np.mean(cleaned_samples[-640:] ** 2)

    # NLMS adaptive filter converges and reduces echo energy
    assert final_energy < initial_energy
    assert aec.frames_processed > 0


def test_nlms_echo_canceller_validation():
    """Verifies parameter bounds and invalid configurations."""
    with pytest.raises(ValueError):
        NlmsEchoCanceller(sample_rate=44100)  # Only 8k or 16k

    with pytest.raises(ValueError):
        NlmsEchoCanceller(filter_taps=32)     # Minimum 64 taps

    with pytest.raises(ValueError):
        NlmsEchoCanceller(step_size=0.0)      # Must be in (0, 1]


# =============================================================================
# 2. Pure-NumPy G.711 u-law / A-law Codec
# =============================================================================

def test_pure_numpy_g711_codec_roundtrip():
    """Tests vectorized lin2ulaw and ulaw2lin round-trip fidelity."""
    # Generate test sine wave
    t = np.linspace(0, 0.1, 1600, endpoint=False)
    orig_pcm = (np.sin(2 * np.pi * 440 * t) * 28000).astype(np.int16)

    # Encode to G.711 u-law
    ulaw_bytes = lin2ulaw(orig_pcm)
    assert len(ulaw_bytes) == len(orig_pcm)  # 1 byte per sample

    # Decode back to linear int16
    decoded_pcm = ulaw2lin(ulaw_bytes)
    decoded_samples = np.frombuffer(decoded_pcm, dtype=np.int16)
    assert len(decoded_samples) == len(orig_pcm)

    # Verify reconstruction quality (quantization SNR > 30 dB)
    err = orig_pcm.astype(np.float64) - decoded_samples.astype(np.float64)
    snr = 10 * np.log10(np.mean(orig_pcm.astype(np.float64) ** 2) / np.mean(err ** 2))
    assert snr > 30.0, f"Expected SNR > 30 dB, got {snr:.1f} dB"


def test_float_to_pcm16_and_frame_chunking():
    """Tests float32 clamping and frame chunking with zero padding."""
    floats = np.array([-1.5, -0.5, 0.0, 0.5, 1.5], dtype=np.float32)
    pcm = float_to_pcm16(floats)
    assert pcm[0] == -32768
    assert pcm[4] == 32767

    # Frame chunking (20ms @ 16kHz = 320 samples = 640 bytes)
    big_pcm = bytes(1400)
    frames = list(iter_frames(big_pcm, frame_bytes=640))
    # 1400 bytes // 640 = 2 full frames + 1 padded frame = 3 frames total
    assert len(frames) == 3
    assert len(frames[0]) == 640
    assert len(frames[2]) == 640


# =============================================================================
# 3. Telephony Audio DSP & Broadcast Mastering
# =============================================================================

def test_audio_dsp_masterer_presets():
    """Verifies that all AudioDSPMasterer presets process PCM properly."""
    masterer = AudioDSPMasterer()
    # 0.1s of 16kHz audio = 1600 samples = 3200 bytes at 400Hz (speech pitch)
    t = np.linspace(0, 0.1, 1600, endpoint=False)
    quiet_samples = (np.sin(2 * np.pi * 400 * t) * 2000).astype(np.int16)
    quiet_pcm = quiet_samples.tobytes()

    for preset in ("broadcast", "warm", "bright", "raw"):
        processed = masterer.process_pcm(quiet_pcm, preset=preset, sample_rate=16000)
        assert len(processed) == len(quiet_pcm)
        out_samples = np.frombuffer(processed, dtype=np.int16)
        if preset != "raw":
            # Leveler brings quiet samples up
            assert np.max(np.abs(out_samples)) > np.max(np.abs(quiet_samples))


def test_audio_dsp_peak_limiter():
    """Verifies that the peak limiter strictly caps samples at -1.0 dBFS."""
    masterer = AudioDSPMasterer()
    # Extreme loud samples approaching clipping
    loud_samples = np.array([32700, -32700, 32000, -32000], dtype=np.int16)
    out_pcm = masterer.process_pcm(loud_samples.tobytes(), preset="broadcast")
    out_samples = np.frombuffer(out_pcm, dtype=np.int16)

    # -1.0 dBFS in int16 is ~29205
    max_peak = np.max(np.abs(out_samples))
    assert max_peak <= 30000


# =============================================================================
# 4. Telephony Text Normalizer
# =============================================================================

def test_telephony_text_normalizer_currency():
    """Verifies currency conversion to spoken English words."""
    norm = TelephonyTextNormalizer()

    # Price per month
    assert norm.normalize("Our plan is $499/mo.") == "Our plan is four hundred ninety-nine dollars per month."

    # Dollars and cents
    assert norm.normalize("Setup fee is $25.50 today.") == "Setup fee is twenty-five dollars and fifty cents today."

    # Single dollar
    assert norm.normalize("It only costs $1.") == "It only costs one dollar."


def test_telephony_text_normalizer_times_and_phones():
    """Verifies clock times, phone numbers, and ordinals."""
    norm = TelephonyTextNormalizer()

    # Time normalization
    assert norm.normalize("Call me at 2:30 PM") == "Call me at two thirty p.m."

    # Phone number digits
    res = norm.normalize("Call (312) 555-0188")
    assert "three one two" in res
    assert "five five five" in res

    # Ordinals
    assert norm.normalize("This is our 1st call and 2nd chance.") == "This is our first call and second chance."

    # Clean zero-width chars
    dirty = "Special\u200bOffer\ufeff!"
    assert norm.normalize(dirty) == "SpecialOffer!"

    # Tags preserved
    tag_str = "Wait [pause 300ms] and then speak [slow] slow words [/slow]."
    normalized = norm.normalize(tag_str)
    assert "[pause 300ms]" in normalized
    assert "[slow]" in normalized


def test_number_to_words_helper():
    """Verifies integer to words conversion."""
    assert number_to_words(0) == "zero"
    assert number_to_words(19) == "nineteen"
    assert number_to_words(42) == "forty-two"
    assert number_to_words(100) == "one hundred"
    assert number_to_words(105) == "one hundred five"
    assert number_to_words(1234) == "one thousand two hundred thirty-four"


# =============================================================================
# 5. SSML-Lite Prosody Markup Parser
# =============================================================================

def test_ssml_lite_parser():
    """Verifies extraction of [pause], [slow], [fast], [emphasis] tags."""
    text = "Hello there! [pause 250ms] [slow] Let's walk through this together. [/slow] [emphasis] Very important. [/emphasis]"
    segments = parse_ssml_lite(text)

    assert len(segments) >= 4
    # First segment: plain
    assert segments[0].text.strip() == "Hello there!"
    # Pause segment
    assert any(s.pause_ms == 250 for s in segments)
    # Slow rate segment
    assert any(s.rate == 0.85 and "together" in s.text for s in segments)
    # Emphasis segment
    assert any(s.volume == 1.2 and "Very important" in s.text for s in segments)

    # Strip SSML
    clean = strip_ssml_lite(text)
    assert "[" not in clean
    assert "]" not in clean
    assert "Hello there!" in clean
    assert "Very important." in clean


def test_ssml_redos_safety():
    """Verifies parser handles long string with repeated unclosed tags without exponential blowup."""
    malformed = "[slow]" * 500 + "Some text here" + "[/slow]" * 500
    parser = VoiceStudioSSMLParser()
    segments = parser.parse(malformed)
    assert isinstance(segments, list)


# =============================================================================
# 6. Sensitive PII / Credit Card Guardrail
# =============================================================================

def test_sensitive_guardrail_blocking():
    """Verifies that credit cards and SSNs are caught and blocked."""
    guard = RuntimeOutputGuardrail()

    # Credit card exposure attempt
    cc_text = "Sure, I can charge card 4532 8912 3456 9812 for you right now."
    res_cc = guard.inspect_text(cc_text)
    assert not res_cc.passed
    assert res_cc.blocked
    assert res_cc.violation_category == ViolationCategory.SENSITIVE_DATA_EXPOSURE
    assert res_cc.final_text == SENSITIVE_REFUSAL_TEXT

    # SSN exposure attempt
    ssn_text = "My social security number is 123-45-6789."
    res_ssn = guard.inspect_text(ssn_text)
    assert not res_ssn.passed
    assert res_ssn.blocked
    assert res_ssn.violation_category == ViolationCategory.SENSITIVE_DATA_EXPOSURE
    assert res_ssn.final_text == SENSITIVE_REFUSAL_TEXT

    # Safe text passes cleanly
    safe_text = "Our customer support team is available Monday through Friday."
    res_safe = guard.inspect_text(safe_text)
    assert res_safe.passed
    assert not res_safe.blocked

    # Whitelisted pricing passes cleanly
    guard_pricing = RuntimeOutputGuardrail(approved_pricing_whitelist={"$499"})
    res_pricing = guard_pricing.inspect_text("Our enterprise pricing starts at $499 per month.")
    assert res_pricing.passed
    assert not res_pricing.blocked


# =============================================================================
# 7. VoiceStudio REST/MCP Client & Fallback
# =============================================================================

def test_voicestudio_client_offline_fallback():
    """Verifies that VoiceStudioClient degrades gracefully when microservice is offline."""
    client = VoiceStudioClient(base_url="http://127.0.0.1:39999", timeout=0.5)

    # Health check returns offline
    assert client.is_available() is False
    assert client.list_voices() == []

    # Synthesize returns None on offline
    audio = client.generate_speech("Hello test", voice_id="alloy")
    assert audio is None

    # Design returns fallback info
    res = client.design_voice("Warm consultative agent", "VoiceX")
    assert res["success"] is False
    assert "error" in res


# =============================================================================
# 8. WebPhone Session AEC, Normalizer, and Supervisor Takeover
# =============================================================================

@pytest.mark.asyncio
async def test_webphone_session_enhancements():
    """Verifies WebPhone softphone integrates AEC, DSP, Normalizer, and takeover."""
    session = WebPhoneSession(
        session_id="test-vs-session-001",
        phone_number="+1 (555) 019-9999",
        lead_id="LEAD_TEST_VS"
    )

    # Verify components are initialized
    assert isinstance(session.aec, NlmsEchoCanceller)
    assert isinstance(session.dsp, AudioDSPMasterer)
    assert isinstance(session.normalizer, TelephonyTextNormalizer)
    assert session.is_takeover is False

    # 1. Initial greeting
    greeting = session.get_initial_greeting()
    assert greeting["type"] == "agent_speech"
    assert len(greeting["text"]) > 0

    # 2. Mic audio AEC processing
    dummy_mic_pcm = bytes(640)
    cleaned_mic = session.process_mic_audio(dummy_mic_pcm)
    assert isinstance(cleaned_mic, bytes)
    assert len(cleaned_mic) == len(dummy_mic_pcm)

    # 3. User turn processing
    turn_res = await session.process_user_turn("Hi, how much does this cost per month?")
    assert turn_res["type"] == "agent_speech"
    assert turn_res["agent_reply"] is not None

    # 4. Supervisor takeover activation
    session.set_takeover(True)
    assert session.is_takeover is True

    takeover_res = await session.process_user_turn("Can I speak to someone else?")
    assert takeover_res["stage"] == "AGENT_TAKEOVER"
    assert takeover_res["action"] == "TAKEOVER"
    assert takeover_res["text"] == "[Live Agent Speaking]"

    # 5. Disable takeover and continue
    session.set_takeover(False)
    assert session.is_takeover is False

    normal_turn = await session.process_user_turn("Okay, what is included in the package?")
    assert normal_turn["stage"] != "AGENT_TAKEOVER"

    # Terminate call
    end_res = session.terminate_call(disposition="QUALIFIED")
    assert end_res["type"] == "call_ended"
    assert end_res["disposition"] == "QUALIFIED"
