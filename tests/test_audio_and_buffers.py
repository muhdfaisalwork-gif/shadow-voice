"""Unit tests for Core Audio Contract, Jitter Buffer, and Playout Buffer."""

import pytest
import time
from shadow_voice.core.audio import (
    AudioFrame,
    AudioFormatError,
    SAMPLE_RATE_16K,
    SAMPLE_RATE_8K,
    FRAME_BYTES_16K,
    FRAME_BYTES_8K,
    resample_8k_to_16k,
    resample_16k_to_8k,
    chunk_pcm
)
from shadow_voice.core.jitter_buffer import IngressJitterBuffer
from shadow_voice.core.playout_buffer import PacedPlayoutBuffer


def test_audio_frame_validation():
    # Valid 16kHz frame: 640 bytes
    valid_data_16k = b"\x00" * FRAME_BYTES_16K
    frame_16k = AudioFrame(data=valid_data_16k, sample_rate=SAMPLE_RATE_16K)
    assert frame_16k.duration_ms == 20.0
    assert frame_16k.samples_count == 320

    # Valid 8kHz frame: 320 bytes
    valid_data_8k = b"\x00" * FRAME_BYTES_8K
    frame_8k = AudioFrame(data=valid_data_8k, sample_rate=SAMPLE_RATE_8K)
    assert frame_8k.duration_ms == 20.0
    assert frame_8k.samples_count == 160

    # Invalid byte lengths
    with pytest.raises(AudioFormatError):
        AudioFrame(data=b"\x00" * 500, sample_rate=SAMPLE_RATE_16K)

    with pytest.raises(AudioFormatError):
        AudioFrame(data=b"\x00" * 300, sample_rate=SAMPLE_RATE_8K)


def test_audio_resampling_boundary():
    # 8kHz -> 16kHz
    pcm_8k = b"\x10\x00" * 160  # 320 bytes
    pcm_16k = resample_8k_to_16k(pcm_8k)
    assert len(pcm_16k) == FRAME_BYTES_16K  # 640 bytes

    # 16kHz -> 8kHz
    pcm_8k_decimated = resample_16k_to_8k(pcm_16k)
    assert len(pcm_8k_decimated) == FRAME_BYTES_8K  # 320 bytes


def test_ingress_jitter_buffer():
    jb = IngressJitterBuffer(min_depth_frames=2, max_depth_frames=5)
    silence_640 = b"\x00" * FRAME_BYTES_16K

    # Pop on empty buffer -> injects PLC silence frame and records underflow
    frame = jb.pop()
    assert frame.data == silence_640
    assert jb.metrics.underflow_events == 1
    assert jb.metrics.plc_injected_frames == 1

    # Push 3 frames
    for i in range(3):
        f = AudioFrame(data=silence_640, sample_rate=SAMPLE_RATE_16K, sequence_num=i)
        jb.push(f)

    assert jb.metrics.total_received == 3
    assert jb.depth_ms == 60.0

    # Read out frames
    popped = jb.pop()
    assert popped.sequence_num == 0
    assert jb.metrics.total_delivered == 1

    # Test overflow policy (bounded memory max 5 frames)
    for i in range(10):
        jb.push(AudioFrame(data=silence_640, sample_rate=SAMPLE_RATE_16K, sequence_num=10+i))

    assert len(jb.queue) <= 5
    assert jb.metrics.overflow_drops > 0


def test_paced_playout_buffer_and_barge_in_flush():
    pb = PacedPlayoutBuffer()
    raw_audio = b"\x10\x20" * 640  # 1280 bytes = 2 frames
    enqueued = pb.enqueue_pcm(raw_audio)
    assert enqueued == 2
    assert pb.buffered_duration_ms == 40.0
    assert pb.has_audio

    # Instant barge-in flush
    t0 = time.time()
    purged = pb.flush()
    elapsed_ms = (time.time() - t0) * 1000.0

    assert purged == 2
    assert not pb.has_audio
    assert pb.buffered_duration_ms == 0.0
    assert elapsed_ms < 5.0  # Must be sub-millisecond / <5ms
    assert pb.metrics.flush_count == 1
