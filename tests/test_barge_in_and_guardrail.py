"""Tests for Barge-In Controller, VAD, and Runtime Output Guardrail."""

import pytest
import asyncio
from shadow_voice.core.audio import AudioFrame, SAMPLE_RATE_16K, FRAME_BYTES_16K
from shadow_voice.core.playout_buffer import PacedPlayoutBuffer
from shadow_voice.conversation.barge_in import BargeInController
from shadow_voice.conversation.guardrail import RuntimeOutputGuardrail
from shadow_voice.conversation.outage_monitor import VendorOutageMonitor, ProviderType
from shadow_voice.core.kill_switch import KillSwitch


def test_barge_in_instant_cancellation():
    playout_buf = PacedPlayoutBuffer()
    # Fill buffer with 10 frames (200ms audio)
    playout_buf.enqueue_pcm(b"\x12\x34" * (320 * 10))
    assert playout_buf.buffered_duration_ms == 200.0

    barge_in = BargeInController(playout_buf)
    llm_cancel = asyncio.Event()
    tts_cancel = asyncio.Event()
    barge_in.set_tts_active(True, llm_cancel, tts_cancel)

    test_speech_frame = AudioFrame(data=b"\x00" * FRAME_BYTES_16K, sample_rate=SAMPLE_RATE_16K)

    # User speaks while TTS is playing!
    interrupted = barge_in.handle_user_speech_detected(test_speech_frame)

    assert interrupted is True
    assert llm_cancel.is_set()
    assert tts_cancel.is_set()
    assert not playout_buf.has_audio
    assert playout_buf.buffered_duration_ms == 0.0
    assert barge_in.metrics.last_flush_latency_ms < 5.0
    assert len(barge_in.get_interrupted_speech_frames()) == 1


def test_runtime_guardrail_pass_clean_speech():
    guardrail = RuntimeOutputGuardrail()
    clean_text = "Hi there, we help high-volume dialer teams cut dropped calls and reduce dead air."
    result = guardrail.inspect_text(clean_text)

    assert result.passed is True
    assert result.final_text == clean_text
    assert result.should_route_to_human is False


def test_runtime_guardrail_catches_unauthorized_pricing():
    guardrail = RuntimeOutputGuardrail(approved_pricing_whitelist={"custom quote"})
    bad_text = "We can offer you a special rate of $49 per user this month!"
    result = guardrail.inspect_text(bad_text)

    assert result.passed is False
    assert result.violation_category == "UNAPPROVED_PRICING"
    assert "specialist" in result.final_text  # Replaced with fallback
    assert result.should_route_to_human is True


def test_runtime_guardrail_catches_unauthorized_guarantee():
    guardrail = RuntimeOutputGuardrail()
    bad_text = "I guarantee you will see a 100% boost in revenue with zero risk."
    result = guardrail.inspect_text(bad_text)

    assert result.passed is False
    assert result.violation_category == "UNAPPROVED_GUARANTEE"
    assert result.should_route_to_human is True


def test_runtime_guardrail_catches_legal_claim():
    guardrail = RuntimeOutputGuardrail()
    bad_text = "By agreeing to this call, this constitutes a verbal agreement."
    result = guardrail.inspect_text(bad_text)

    assert result.passed is False
    assert result.violation_category == "LEGAL_CLAIM"
    assert result.should_route_to_human is True


def test_vendor_outage_circuit_breaker():
    ks = KillSwitch.reset_for_test()
    monitor = VendorOutageMonitor(consecutive_failure_threshold=3, kill_switch=ks)

    assert ks.can_dial() is True
    monitor.record_failure(ProviderType.STT, "HTTP 503")
    assert ks.can_dial() is True

    monitor.record_failure(ProviderType.STT, "HTTP 503")
    assert ks.can_dial() is True

    # 3rd consecutive failure breaches threshold -> triggers kill switch!
    breached = monitor.record_failure(ProviderType.STT, "HTTP 503")
    assert breached is True
    assert ks.is_triggered is True
    assert ks.can_dial() is False
