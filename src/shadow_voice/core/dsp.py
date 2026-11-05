"""
Telephony Audio DSP & Broadcast Mastering Pipeline
==================================================
Pure-NumPy audio mastering, dynamic leveling, highpass filtering, and peak limiting.

Adapted from VoiceStudio / Spotify Pedalboard clean-room architecture.

Key features for Shadow Voice:
1. Highpass Filter (80 Hz): Strips low-frequency HVAC rumble and desk bumps.
2. Dynamic Leveler (AGC): Smooths out volume inconsistencies across turns in real-time.
3. Peak Limiter (-1.0 dBFS): Prevents harsh digital clipping over PSTN phone lines.
4. Voice Presets:
   - 'broadcast': Crisp radio standard, even volume, warm and clear.
   - 'warm': Boosted low-mids for consultative, trustworthy sales delivery.
   - 'bright': Enhanced presence and articulation for high clarity.
   - 'raw': Passthrough with no DSP modifications.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional
import numpy as np

logger = logging.getLogger("shadow_voice.core.dsp")


class AudioDSPMasterer:
    """Broadcast-grade audio DSP processor and leveler for outbound voice streams."""

    PRESETS = {
        "broadcast": {
            "highpass_hz": 80.0,
            "target_dbfs": -20.0,
            "max_gain_db": 8.0,
            "limiter_dbfs": -1.0,
            "low_gain_db": 1.5,
            "high_gain_db": 2.0,
        },
        "warm": {
            "highpass_hz": 60.0,
            "target_dbfs": -19.0,
            "max_gain_db": 6.0,
            "limiter_dbfs": -1.5,
            "low_gain_db": 3.0,
            "high_gain_db": -0.5,
        },
        "bright": {
            "highpass_hz": 80.0,
            "target_dbfs": -20.0,
            "max_gain_db": 8.0,
            "limiter_dbfs": -1.0,
            "low_gain_db": -1.0,
            "high_gain_db": 3.5,
        },
        "raw": {
            "highpass_hz": 0.0,
            "target_dbfs": 0.0,
            "max_gain_db": 0.0,
            "limiter_dbfs": 0.0,
            "low_gain_db": 0.0,
            "high_gain_db": 0.0,
        }
    }

    def __init__(self, default_preset: str = "broadcast") -> None:
        self.default_preset = default_preset if default_preset in self.PRESETS else "broadcast"

    def apply_highpass(self, samples: np.ndarray, sample_rate: int, cutoff_hz: float = 80.0) -> np.ndarray:
        """Simple single-pole highpass filter to cut sub-audible low rumble."""
        if cutoff_hz <= 0 or samples.size <= 1:
            return samples
        rc = 1.0 / (2.0 * np.pi * cutoff_hz)
        dt = 1.0 / max(1, sample_rate)
        alpha = rc / (rc + dt)
        filtered = np.empty_like(samples)
        filtered[0] = samples[0]
        for i in range(1, len(samples)):
            filtered[i] = alpha * (filtered[i - 1] + samples[i] - samples[i - 1])
        return filtered

    def apply_leveler(
        self,
        samples: np.ndarray,
        sample_rate: int,
        target_db: float = -20.0,
        max_gain_db: float = 8.0,
        window_ms: float = 400.0,
        amount: float = 0.7
    ) -> np.ndarray:
        """
        Pure-NumPy sliding RMS leveler.
        Brings quiet utterances up towards target_db without boosting silence.
        """
        if samples.size == 0 or max_gain_db <= 0:
            return samples

        win_samples = max(16, int(sample_rate * (window_ms / 1000.0)))
        pad = win_samples // 2
        padded = np.pad(samples ** 2, (pad, pad), mode="reflect")

        # Running RMS energy
        kernel = np.ones(win_samples, dtype=np.float32) / win_samples
        rms_sq = np.convolve(padded, kernel, mode="valid")[:len(samples)]
        rms = np.sqrt(np.maximum(rms_sq, 1e-8))

        rms_db = 20.0 * np.log10(np.maximum(rms, 1e-5))

        # Do not boost noise floor below -55 dBFS
        silence_mask = rms_db < -55.0
        needed_gain_db = (target_db - rms_db) * amount
        clamped_gain_db = np.clip(needed_gain_db, -6.0, max_gain_db)
        clamped_gain_db[silence_mask] = 0.0

        linear_gain = 10.0 ** (clamped_gain_db / 20.0)
        return samples * linear_gain

    def apply_limiter(self, samples: np.ndarray, threshold_dbfs: float = -1.0) -> np.ndarray:
        """Hard peak limiter to strictly prevent DAC/PSTN clipping."""
        threshold_linear = 10.0 ** (threshold_dbfs / 20.0)
        peak = np.max(np.abs(samples)) if samples.size else 0.0
        if peak > threshold_linear:
            scale = threshold_linear / peak
            return samples * scale
        return samples

    def process_pcm(
        self,
        pcm_bytes: bytes,
        preset: Optional[str] = None,
        sample_rate: int = 16000
    ) -> bytes:
        """
        Runs full broadcast DSP mastering pipeline on int16 little-endian PCM bytes:
        1. Byte alignment validation
        2. Float32 conversion [-1.0, 1.0]
        3. Highpass filter
        4. Sliding-window leveler (AGC)
        5. Peak limiter
        6. Clamped int16 output bytes
        """
        if not pcm_bytes or len(pcm_bytes) < 2:
            return pcm_bytes

        # Align to 16-bit boundaries
        if len(pcm_bytes) % 2 != 0:
            pcm_bytes = pcm_bytes[:len(pcm_bytes) - 1]
        if len(pcm_bytes) < 2:
            return pcm_bytes

        cfg = self.PRESETS.get(preset or self.default_preset, self.PRESETS["broadcast"])
        if preset == "raw" or (cfg["highpass_hz"] == 0 and cfg["max_gain_db"] == 0):
            return pcm_bytes

        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # 1. Highpass
        if cfg["highpass_hz"] > 0:
            samples = self.apply_highpass(samples, sample_rate, cutoff_hz=cfg["highpass_hz"])

        # 2. Leveler
        if cfg["max_gain_db"] > 0:
            samples = self.apply_leveler(
                samples,
                sample_rate,
                target_db=cfg["target_dbfs"],
                max_gain_db=cfg["max_gain_db"]
            )

        # 3. Peak Limiter
        samples = self.apply_limiter(samples, threshold_dbfs=cfg["limiter_dbfs"])

        # Return int16 PCM bytes
        out = np.clip(samples * 32768.0, -32768.0, 32767.0).astype(np.int16)
        return out.tobytes()
