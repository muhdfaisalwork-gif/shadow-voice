"""
Gateway Resampling Boundary
===========================
Converts 8 kHz PSTN AudioSocket audio to canonical 16 kHz internal audio,
and vice versa.
Validates byte counts strictly:
- 8 kHz @ 20ms = 320 bytes
- 16 kHz @ 20ms = 640 bytes
"""

from __future__ import annotations
from shadow_voice.core.audio import (
    AudioFrame,
    SAMPLE_RATE_16K,
    SAMPLE_RATE_8K,
    FRAME_BYTES_16K,
    FRAME_BYTES_8K,
    resample_8k_to_16k,
    resample_16k_to_8k,
    AudioFormatError,
)


class GatewayResampler:
    """Handles boundary audio conversion between PSTN (8kHz) and Internal (16kHz)."""

    @staticmethod
    def ingress_pstn_to_internal(frame_8k: AudioFrame) -> AudioFrame:
        """Converts incoming 8kHz AudioSocket frame to canonical 16kHz internal frame."""
        if frame_8k.sample_rate == SAMPLE_RATE_16K:
            return frame_8k  # Already 16k
        if frame_8k.sample_rate != SAMPLE_RATE_8K:
            raise AudioFormatError(f"Unsupported ingress sample rate: {frame_8k.sample_rate}")

        pcm_16k = resample_8k_to_16k(frame_8k.data)
        return AudioFrame(
            data=pcm_16k,
            sample_rate=SAMPLE_RATE_16K,
            sequence_num=frame_8k.sequence_num,
            timestamp_ms=frame_8k.timestamp_ms
        )

    @staticmethod
    def egress_internal_to_pstn(frame_16k: AudioFrame) -> AudioFrame:
        """Converts internal 16kHz frame to 8kHz PSTN AudioSocket frame."""
        if frame_16k.sample_rate == SAMPLE_RATE_8K:
            return frame_16k
        if frame_16k.sample_rate != SAMPLE_RATE_16K:
            raise AudioFormatError(f"Unsupported egress sample rate: {frame_16k.sample_rate}")

        pcm_8k = resample_16k_to_8k(frame_16k.data)
        return AudioFrame(
            data=pcm_8k,
            sample_rate=SAMPLE_RATE_8K,
            sequence_num=frame_16k.sequence_num,
            timestamp_ms=frame_16k.timestamp_ms
        )
