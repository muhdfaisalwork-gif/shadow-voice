"""
Audio Contract & Processing Module
===================================
Explicit internal contract:
- PCM signed linear
- 16-bit (little-endian, int16)
- Mono (1 channel)
- Canonical internal sample rate: 16 kHz
- 20 ms processing/egress cadence (640 bytes per frame)
- PSTN boundary: 8 kHz (320 bytes per frame)
"""

from __future__ import annotations
import math
import struct
from dataclasses import dataclass
from typing import Optional, List, Tuple
import numpy as np

# Canonical constants
SAMPLE_RATE_16K: int = 16000
SAMPLE_RATE_8K: int = 8000
CHANNELS: int = 1
BYTES_PER_SAMPLE: int = 2  # 16-bit signed integer
FRAME_DURATION_MS: int = 20

# Strict byte-count validations
SAMPLES_PER_FRAME_16K: int = int(SAMPLE_RATE_16K * (FRAME_DURATION_MS / 1000.0))  # 320
FRAME_BYTES_16K: int = SAMPLES_PER_FRAME_16K * BYTES_PER_SAMPLE                  # 640

SAMPLES_PER_FRAME_8K: int = int(SAMPLE_RATE_8K * (FRAME_DURATION_MS / 1000.0))    # 160
FRAME_BYTES_8K: int = SAMPLES_PER_FRAME_8K * BYTES_PER_SAMPLE                    # 320

SILENCE_FRAME_16K: bytes = b"\x00" * FRAME_BYTES_16K
SILENCE_FRAME_8K: bytes = b"\x00" * FRAME_BYTES_8K


class AudioFormatError(ValueError):
    """Raised when an audio frame violates byte-count or sample-rate contracts."""
    pass


@dataclass(slots=True)
class AudioFrame:
    """Represents a discrete 20ms audio frame conforming to the Shadow Voice contract."""
    data: bytes
    sample_rate: int = SAMPLE_RATE_16K
    sequence_num: int = 0
    timestamp_ms: float = 0.0

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        expected_bytes = FRAME_BYTES_16K if self.sample_rate == SAMPLE_RATE_16K else FRAME_BYTES_8K
        if len(self.data) != expected_bytes:
            raise AudioFormatError(
                f"Invalid frame byte length {len(self.data)} for sample rate {self.sample_rate}Hz. "
                f"Expected {expected_bytes} bytes for {FRAME_DURATION_MS}ms."
            )

    @property
    def duration_ms(self) -> float:
        return float(FRAME_DURATION_MS)

    @property
    def samples_count(self) -> int:
        return len(self.data) // BYTES_PER_SAMPLE

    def compute_rms_energy(self) -> float:
        """Compute Root Mean Square (RMS) energy in dBFS."""
        if not self.data:
            return -96.0
        samples = np.frombuffer(self.data, dtype=np.int16).astype(np.float32)
        rms = np.sqrt(np.mean(samples ** 2))
        if rms <= 1e-6:
            return -96.0
        # Reference max amplitude for signed 16-bit is 32768
        dbfs = 20.0 * math.log10(rms / 32768.0)
        return float(dbfs)

    def is_clipping(self, threshold: int = 32760) -> bool:
        """Check if any sample in the frame hits digital clipping ceiling."""
        samples = np.frombuffer(self.data, dtype=np.int16)
        return bool(np.any(np.abs(samples) >= threshold))

    def is_silence(self, threshold_dbfs: float = -50.0) -> bool:
        """Determines if the frame energy is below silence threshold."""
        return self.compute_rms_energy() < threshold_dbfs


def resample_8k_to_16k(pcm_8k: Optional[bytes]) -> bytes:
    """
    Explicit 8kHz -> 16kHz conversion at gateway boundary.
    Performs band-limited linear interpolation doubling the sample count.
    """
    if pcm_8k is None or len(pcm_8k) == 0:
        return b""

    if len(pcm_8k) % 2 != 0:
        raise AudioFormatError(f"Unaligned 16-bit PCM: length {len(pcm_8k)} must be even.")

    samples_8k = np.frombuffer(pcm_8k, dtype=np.int16).astype(np.float32)
    n_in = len(samples_8k)
    n_out = n_in * 2

    # Linear interpolation for fast 2x upsampling
    x_in = np.arange(n_in)
    x_out = np.linspace(0, n_in - 1, n_out)
    samples_16k = np.interp(x_out, x_in, samples_8k)

    # Clip to int16 range and convert
    samples_16k_clamped = np.clip(samples_16k, -32768, 32767).astype(np.int16)
    return samples_16k_clamped.tobytes()


def resample_16k_to_8k(pcm_16k: Optional[bytes]) -> bytes:
    """
    Explicit 16kHz -> 8kHz conversion at gateway boundary.
    Applies decimation with a 2-point averaging low-pass filter to prevent aliasing.
    """
    if pcm_16k is None or len(pcm_16k) == 0:
        return b""

    if len(pcm_16k) % 2 != 0:
        raise AudioFormatError(f"Unaligned 16-bit PCM: length {len(pcm_16k)} must be even.")

    samples_16k = np.frombuffer(pcm_16k, dtype=np.int16).astype(np.float32)
    # Ensure even number of samples for 2:1 decimation
    if len(samples_16k) % 2 != 0:
        samples_16k = np.append(samples_16k, samples_16k[-1])

    # Simple 2-tap moving average anti-aliasing filter before decimation
    filtered = (samples_16k[0::2] + samples_16k[1::2]) * 0.5
    samples_8k = np.clip(filtered, -32768, 32767).astype(np.int16)
    return samples_8k.tobytes()


def chunk_pcm(pcm_bytes: bytes, frame_bytes: int = FRAME_BYTES_16K) -> List[bytes]:
    """Split a PCM byte buffer into strict frames of frame_bytes."""
    pcm = pcm_bytes or b""
    return [pcm[i:i + frame_bytes] for i in range(0, len(pcm), frame_bytes) if len(pcm[i:i + frame_bytes]) == frame_bytes]


def save_pcm_to_wav(pcm_bytes: bytes, filepath: str, sample_rate: int = SAMPLE_RATE_16K) -> str:
    """Writes linear PCM int16 mono bytes to standard RIFF/WAV file."""
    import wave
    import os
    dirpath = os.path.dirname(filepath)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(BYTES_PER_SAMPLE)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes or b"")
    return filepath

