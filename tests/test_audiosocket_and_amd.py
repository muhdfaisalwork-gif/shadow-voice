"""Tests for AudioSocket Protocol, Resampling, and Answering Machine Detection (AMD)."""

import pytest
import numpy as np
from shadow_voice.core.audio import (
    AudioFrame,
    SAMPLE_RATE_16K,
    SAMPLE_RATE_8K,
    FRAME_BYTES_8K,
    FRAME_BYTES_16K,
)
from shadow_voice.telephony.resampler import GatewayResampler
from shadow_voice.telephony.amd import AnsweringMachineDetector, AMDStatus
from shadow_voice.telephony.metadata import CallMetadata


def test_gateway_resampler():
    frame_8k = AudioFrame(data=b"\x00" * FRAME_BYTES_8K, sample_rate=SAMPLE_RATE_8K)
    frame_16k = GatewayResampler.ingress_pstn_to_internal(frame_8k)
    assert frame_16k.sample_rate == SAMPLE_RATE_16K
    assert len(frame_16k.data) == FRAME_BYTES_16K

    frame_back_8k = GatewayResampler.egress_internal_to_pstn(frame_16k)
    assert frame_back_8k.sample_rate == SAMPLE_RATE_8K
    assert len(frame_back_8k.data) == FRAME_BYTES_8K


def test_metadata_normalization():
    headers = {
        "Call-ID": "sip-call-12345@192.168.1.100",
        "X-VICI-Lead-ID": "887123",
        "X-VICI-Campaign": "SALES_US_WEST",
        "X-Called-Number": "+13125550199",
        "X-Caller-ID": "+18005550100",
        "X-Caller-Name": "Shadow Voice",
    }
    meta = CallMetadata.from_asterisk_headers("sess-uuid-999", headers)
    assert meta.session_id == "sess-uuid-999"
    assert meta.lead_id == "887123"
    assert meta.campaign_id == "SALES_US_WEST"
    assert meta.called_number == "+13125550199"
    assert meta.caller_id_number == "+18005550100"


def test_amd_human_greeting():
    detector = AnsweringMachineDetector()
    # Create speech frames: 500ms speech (25 frames) with voice audio
    t = np.linspace(0, 0.02, 320, endpoint=False)
    speech_data = (np.sin(2 * np.pi * 300 * t) * 15000).astype(np.int16).tobytes()
    silence_data = (np.zeros(320)).astype(np.int16).tobytes()

    speech_frame = AudioFrame(data=speech_data, sample_rate=SAMPLE_RATE_16K)
    silence_frame = AudioFrame(data=silence_data, sample_rate=SAMPLE_RATE_16K)

    # 1. Say "Hello?" for 400ms (20 frames)
    for _ in range(20):
        dec = detector.process_frame(speech_frame)

    # 2. Pause for 700ms (35 frames)
    final_dec = None
    for _ in range(35):
        dec = detector.process_frame(silence_frame)
        if dec.status != AMDStatus.ANALYZING:
            final_dec = dec
            break

    assert final_dec is not None
    assert final_dec.status == AMDStatus.HUMAN
    assert final_dec.safe_harbor_cleared is True
    assert final_dec.total_analyzed_ms <= 2000.0


def test_amd_machine_greeting():
    detector = AnsweringMachineDetector()
    # Machine greeting: long uninterrupted speech > 1600ms (85 frames)
    t = np.linspace(0, 0.02, 320, endpoint=False)
    speech_data = (np.sin(2 * np.pi * 250 * t) * 15000).astype(np.int16).tobytes()
    speech_frame = AudioFrame(data=speech_data, sample_rate=SAMPLE_RATE_16K)

    final_dec = None
    for _ in range(90):
        dec = detector.process_frame(speech_frame)
        if dec.status != AMDStatus.ANALYZING:
            final_dec = dec
            break

    assert final_dec is not None
    assert final_dec.status == AMDStatus.MACHINE
    assert final_dec.safe_harbor_cleared is False
