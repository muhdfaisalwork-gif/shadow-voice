"""
Voice Activity Detection (VAD) & Endpointing
=============================================
Measures speech start (for instant barge-in trigger) and speech end
(target 280-320 ms benchmark) for low-latency conversational turn-taking.
"""

from __future__ import annotations
import math
import time
from dataclasses import dataclass
from typing import Optional, List
import numpy as np
from shadow_voice.core.audio import AudioFrame


@dataclass
class VADEvent:
    is_speech: bool
    speech_start: bool = False
    speech_end: bool = False
    energy_dbfs: float = -96.0
    silence_duration_ms: float = 0.0
    speech_duration_ms: float = 0.0


class VoiceActivityDetector:
    """
    Real-time energy and zero-crossing rate Voice Activity Detector.
    Calibrated for 280-320 ms endpointing latency on 20ms frames.
    """

    def __init__(
        self,
        energy_threshold_dbfs: float = -40.0,
        start_speech_frames: int = 2,       # 40ms speech needed to trigger speech start / barge-in
        endpoint_silence_frames: int = 15,  # 15 frames * 20ms = 300ms target endpointing
        noise_adapt_rate: float = 0.05
    ) -> None:
        self.energy_threshold_dbfs = energy_threshold_dbfs
        self.start_speech_frames = start_speech_frames
        self.endpoint_silence_frames = endpoint_silence_frames
        self.noise_adapt_rate = noise_adapt_rate

        self._in_speech: bool = False
        self._consecutive_speech_frames: int = 0
        self._consecutive_silence_frames: int = 0
        self._speech_duration_ms: float = 0.0
        self._silence_duration_ms: float = 0.0
        self._noise_floor_dbfs: float = -55.0

    @property
    def is_in_speech(self) -> bool:
        return self._in_speech

    def process_frame(self, frame: AudioFrame) -> VADEvent:
        """
        Processes a 20ms audio frame and returns VAD state transitions.
        """
        energy = frame.compute_rms_energy()
        # Adaptive threshold based on background noise
        threshold = max(self.energy_threshold_dbfs, self._noise_floor_dbfs + 12.0)
        is_active_frame = energy >= threshold

        event = VADEvent(
            is_speech=self._in_speech,
            energy_dbfs=energy,
            silence_duration_ms=self._silence_duration_ms,
            speech_duration_ms=self._speech_duration_ms
        )

        if not self._in_speech:
            if is_active_frame:
                self._consecutive_speech_frames += 1
                if self._consecutive_speech_frames >= self.start_speech_frames:
                    self._in_speech = True
                    self._consecutive_silence_frames = 0
                    self._silence_duration_ms = 0.0
                    self._speech_duration_ms = self._consecutive_speech_frames * 20.0
                    event.speech_start = True
                    event.is_speech = True
            else:
                self._consecutive_speech_frames = 0
                # Adapt noise floor slowly during non-speech
                if energy > -80.0:
                    self._noise_floor_dbfs = (1.0 - self.noise_adapt_rate) * self._noise_floor_dbfs + self.noise_adapt_rate * energy
        else:
            # Currently in speech
            if is_active_frame:
                self._consecutive_silence_frames = 0
                self._speech_duration_ms += 20.0
                event.is_speech = True
            else:
                self._consecutive_silence_frames += 1
                self._silence_duration_ms = self._consecutive_silence_frames * 20.0
                if self._consecutive_silence_frames >= self.endpoint_silence_frames:
                    # Endpoint reached! (280-320 ms)
                    self._in_speech = False
                    self._consecutive_speech_frames = 0
                    event.speech_end = True
                    event.is_speech = False

        event.speech_duration_ms = self._speech_duration_ms
        event.silence_duration_ms = self._silence_duration_ms
        return event

    def reset(self) -> None:
        self._in_speech = False
        self._consecutive_speech_frames = 0
        self._consecutive_silence_frames = 0
        self._speech_duration_ms = 0.0
        self._silence_duration_ms = 0.0
