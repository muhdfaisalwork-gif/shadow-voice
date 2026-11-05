"""
Acoustic Echo Cancellation (AEC) Engine for Softphones & Live Telephony
=======================================================================
Pure-NumPy implementation of a Normalized Least Mean Squares (NLMS) time-domain
adaptive filter with Geigel double-talk detector.

Adapted from VoiceStudio / Patter clean-room architecture (MIT License).

Why this matters for Shadow Voice:
When a softphone or WebPhone user is speaking while audio is playing out from
the agent (or barge-in occurs), speaker output leaks into the microphone.
Without AEC, the STT engine transcribes its own output, leading to self-interruption
and feedback loops. This module provides dependency-free, server-side echo cancellation.
"""

from __future__ import annotations

import logging
import time
from typing import Final, Optional
import numpy as np

logger = logging.getLogger("shadow_voice.core.aec")

_DEFAULT_FILTER_TAPS: Final[int] = 512
_DEFAULT_STEP_SIZE: Final[float] = 0.1
_DEFAULT_WARMUP_STEP_SIZE: Final[float] = 0.5
_DEFAULT_WARMUP_SECONDS: Final[float] = 0.5
_DEFAULT_LEAKAGE: Final[float] = 0.9999
_DOUBLE_TALK_RHO: Final[float] = 0.6
_FAR_END_BUFFER_SECONDS: Final[float] = 0.5


class NlmsEchoCanceller:
    """
    Time-domain NLMS adaptive filter with Geigel double-talk detection.
    Operates on narrowband mono PCM at 16 kHz or 8 kHz.
    """

    _FAR_STALE_S: float = 0.25

    def __init__(
        self,
        sample_rate: int = 16000,
        *,
        filter_taps: int = _DEFAULT_FILTER_TAPS,
        step_size: float = _DEFAULT_STEP_SIZE,
        warmup_step_size: float = _DEFAULT_WARMUP_STEP_SIZE,
        warmup_seconds: float = _DEFAULT_WARMUP_SECONDS,
        leakage: float = _DEFAULT_LEAKAGE,
        double_talk_rho: float = _DOUBLE_TALK_RHO,
    ) -> None:
        if sample_rate not in (8000, 16000):
            raise ValueError(f"NlmsEchoCanceller supports 8000 Hz or 16000 Hz only; got {sample_rate}.")
        if filter_taps < 64:
            raise ValueError(f"filter_taps must be >= 64; got {filter_taps}.")
        if not 0 < step_size <= 1:
            raise ValueError(f"step_size must be in (0, 1]; got {step_size}.")
        if not 0 < warmup_step_size <= 1:
            raise ValueError(f"warmup_step_size must be in (0, 1]; got {warmup_step_size}.")
        if warmup_seconds < 0:
            raise ValueError(f"warmup_seconds must be >= 0; got {warmup_seconds}.")
        if not 0 < leakage <= 1:
            raise ValueError(f"leakage must be in (0, 1]; got {leakage}.")

        self._sample_rate = sample_rate
        self._taps = filter_taps
        self._step = float(step_size)
        self._warmup_step = float(warmup_step_size)
        self._warmup_samples = int(warmup_seconds * sample_rate)
        self._leakage = float(leakage)
        self._rho = float(double_talk_rho)

        self._processed_samples: int = 0
        self._last_far_push_monotonic: Optional[float] = None

        # Filter coefficients (weights)
        self._w = np.zeros(filter_taps, dtype=np.float32)

        # Far-end history ring buffer
        max_buf_samples = max(
            filter_taps * 2,
            int(sample_rate * _FAR_END_BUFFER_SECONDS),
        )
        self._far_buf = np.zeros(max_buf_samples, dtype=np.float32)
        self._far_write_idx = 0
        self._far_filled = 0

        # Diagnostics metrics
        self.frames_processed: int = 0
        self.double_talk_frames: int = 0

    def push_far_end(self, pcm_bytes: bytes) -> None:
        """Append far-end (playback/egress) audio to the reference ring buffer."""
        if not pcm_bytes:
            return
        self._last_far_push_monotonic = time.monotonic()
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        n = samples.shape[0]
        buf_len = self._far_buf.shape[0]
        if n >= buf_len:
            self._far_buf[:] = samples[-buf_len:]
            self._far_write_idx = 0
            self._far_filled = buf_len
            return
        end = self._far_write_idx + n
        if end <= buf_len:
            self._far_buf[self._far_write_idx:end] = samples
        else:
            head = buf_len - self._far_write_idx
            self._far_buf[self._far_write_idx:] = samples[:head]
            self._far_buf[: n - head] = samples[head:]
        self._far_write_idx = (self._far_write_idx + n) % buf_len
        self._far_filled = min(self._far_filled + n, buf_len)

    def process_near_end(self, pcm_bytes: bytes) -> bytes:
        """
        Subtract the estimated echo from the near-end (microphone) signal.
        Returns int16 mono PCM with the estimated echo cancelled.
        """
        if not pcm_bytes:
            return pcm_bytes

        # If reference buffer isn't filled yet or far-end is stale, pass through safely
        if self._far_filled < self._taps:
            return pcm_bytes

        last_push = self._last_far_push_monotonic
        if last_push is None or (time.monotonic() - last_push) > self._FAR_STALE_S:
            return pcm_bytes

        near = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        cleaned = self._block_nlms(near)
        out = np.clip(cleaned * 32768.0, -32768.0, 32767.0).astype(np.int16)
        self.frames_processed += 1
        return out.tobytes()

    def reset(self) -> None:
        """Clear filter coefficients and far-end history."""
        self._w.fill(0)
        self._far_buf.fill(0)
        self._far_write_idx = 0
        self._far_filled = 0
        self._processed_samples = 0
        self._last_far_push_monotonic = None
        self.frames_processed = 0
        self.double_talk_frames = 0

    def _far_window(self, length: int) -> np.ndarray:
        """Most recent length far-end samples."""
        buf_len = self._far_buf.shape[0]
        if length > self._far_filled:
            length = self._far_filled
        end = self._far_write_idx
        if end >= length:
            return self._far_buf[end - length: end]
        head = self._far_buf[buf_len - (length - end):]
        tail = self._far_buf[:end]
        return np.concatenate((head, tail))

    def _block_nlms(self, near: np.ndarray) -> np.ndarray:
        """Sample-by-sample NLMS adaptive filtering over one frame."""
        taps = self._taps
        far_window = self._far_window(taps + near.shape[0] - 1)
        if far_window.shape[0] < taps + near.shape[0] - 1:
            pad = np.zeros(
                taps + near.shape[0] - 1 - far_window.shape[0], dtype=np.float32
            )
            far_window = np.concatenate((pad, far_window))

        # Geigel double-talk detector
        far_max = float(np.max(np.abs(far_window))) if far_window.size else 0.0
        near_max = float(np.max(np.abs(near)))
        if far_max <= 1e-3:
            return near
        double_talk = near_max > self._rho * far_max
        if double_talk:
            self.double_talk_frames += 1

        out = np.empty_like(near)
        w = self._w
        leakage = self._leakage
        step = self._warmup_step if self._processed_samples < self._warmup_samples else self._step

        for i in range(near.shape[0]):
            x = far_window[i: i + taps]
            y_est = float(np.dot(w, x))
            e = float(near[i] - y_est)
            out[i] = e
            if not double_talk:
                norm = float(np.dot(x, x)) + 1e-6
                w *= leakage
                w += (step * e / norm) * x
        self._processed_samples += near.shape[0]
        return out
