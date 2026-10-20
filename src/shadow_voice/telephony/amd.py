"""
Answering Machine Detection (AMD)
=================================
Fulfills Section 8.1 Gap-Fill:
- Distinguishes live human voice from voicemail / answering machine / fax / silence
- Gates whether conversational engine engages or call is dispositioned as Answering Machine (AAM)
- Enforces 2-second live-connection safe-harbor timing
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List
import numpy as np

from shadow_voice.core.audio import AudioFrame, SAMPLE_RATE_16K, SAMPLE_RATE_8K


class AMDStatus(str, Enum):
    HUMAN = "HUMAN"
    MACHINE = "MACHINE"
    FAX = "FAX"
    SILENCE = "SILENCE"
    TIMEOUT = "TIMEOUT"
    ANALYZING = "ANALYZING"


@dataclass
class AMDDecision:
    status: AMDStatus
    confidence: float
    speech_duration_ms: float
    silence_duration_ms: float
    total_analyzed_ms: float
    safe_harbor_cleared: bool  # True if connected to live human within 2000ms safe harbor window


class AnsweringMachineDetector:
    """
    Real-time energy and cadence Answering Machine Detector operating on 20ms audio frames.
    """

    def __init__(
        self,
        energy_threshold_dbfs: float = -42.0,
        max_human_greeting_ms: float = 1400.0,  # Human hello is rarely > 1.4s
        min_machine_greeting_ms: float = 1600.0, # Voicemail greeting usually runs > 1.6s uninterrupted
        after_greeting_silence_ms: float = 600.0, # Human pauses after saying hello
        safe_harbor_max_ms: float = 2000.0        # Regulatory 2-second live-connection window
    ) -> None:
        self.energy_threshold_dbfs = energy_threshold_dbfs
        self.max_human_greeting_ms = max_human_greeting_ms
        self.min_machine_greeting_ms = min_machine_greeting_ms
        self.after_greeting_silence_ms = after_greeting_silence_ms
        self.safe_harbor_max_ms = safe_harbor_max_ms

        self._total_ms: float = 0.0
        self._initial_silence_ms: float = 0.0
        self._speech_ms: float = 0.0
        self._post_speech_silence_ms: float = 0.0
        self._speech_detected: bool = False
        self._speech_completed: bool = False
        self._decision: Optional[AMDDecision] = None

    @property
    def is_decided(self) -> bool:
        return self._decision is not None and self._decision.status != AMDStatus.ANALYZING

    def process_frame(self, frame: AudioFrame) -> AMDDecision:
        """Processes a single 20ms frame and updates AMD state machine."""
        if self.is_decided:
            assert self._decision is not None
            return self._decision

        duration = frame.duration_ms
        self._total_ms += duration
        dbfs = frame.compute_rms_energy()
        is_speech = dbfs >= self.energy_threshold_dbfs

        # Check for tone frequencies (Beep / Fax) using FFT
        if is_speech:
            tone_status = self._detect_tones(frame)
            if tone_status == AMDStatus.FAX:
                self._decision = AMDDecision(
                    status=AMDStatus.FAX,
                    confidence=0.98,
                    speech_duration_ms=self._speech_ms,
                    silence_duration_ms=self._post_speech_silence_ms,
                    total_analyzed_ms=self._total_ms,
                    safe_harbor_cleared=False
                )
                return self._decision

        # Timing and energy cadence state machine
        if not self._speech_detected:
            if is_speech:
                self._speech_detected = True
                self._speech_ms += duration
            else:
                self._initial_silence_ms += duration
                # If silent for entire safe harbor window
                if self._initial_silence_ms >= self.safe_harbor_max_ms:
                    self._decision = AMDDecision(
                        status=AMDStatus.SILENCE,
                        confidence=0.85,
                        speech_duration_ms=0.0,
                        silence_duration_ms=self._initial_silence_ms,
                        total_analyzed_ms=self._total_ms,
                        safe_harbor_cleared=False
                    )
                    return self._decision
        else:
            # Speech was already detected
            if is_speech:
                if self._speech_completed:
                    # Spoke again after pausing: likely machine continuing message
                    self._speech_ms += duration
                else:
                    self._speech_ms += duration
                    if self._speech_ms >= self.min_machine_greeting_ms:
                        # Long uninterrupted greeting -> Voicemail
                        self._decision = AMDDecision(
                            status=AMDStatus.MACHINE,
                            confidence=0.92,
                            speech_duration_ms=self._speech_ms,
                            silence_duration_ms=self._post_speech_silence_ms,
                            total_analyzed_ms=self._total_ms,
                            safe_harbor_cleared=False
                        )
                        return self._decision
            else:
                # Silence after speech started
                self._speech_completed = True
                self._post_speech_silence_ms += duration

                # If speech was short (human hello) and followed by sufficient pause
                if (
                    self._speech_ms <= self.max_human_greeting_ms
                    and self._post_speech_silence_ms >= self.after_greeting_silence_ms
                ):
                    safe_harbor = self._total_ms <= self.safe_harbor_max_ms
                    self._decision = AMDDecision(
                        status=AMDStatus.HUMAN,
                        confidence=0.90,
                        speech_duration_ms=self._speech_ms,
                        silence_duration_ms=self._post_speech_silence_ms,
                        total_analyzed_ms=self._total_ms,
                        safe_harbor_cleared=safe_harbor
                    )
                    return self._decision

        # Hard timeout check
        if self._total_ms >= 2500.0:
            if self._speech_detected:
                if self._speech_ms > self.max_human_greeting_ms:
                    status = AMDStatus.MACHINE
                    conf = 0.88
                else:
                    status = AMDStatus.HUMAN
                    conf = 0.75
            else:
                status = AMDStatus.TIMEOUT
                conf = 0.70

            self._decision = AMDDecision(
                status=status,
                confidence=conf,
                speech_duration_ms=self._speech_ms,
                silence_duration_ms=self._post_speech_silence_ms,
                total_analyzed_ms=self._total_ms,
                safe_harbor_cleared=(status == AMDStatus.HUMAN and self._total_ms <= self.safe_harbor_max_ms)
            )
            return self._decision

        return AMDDecision(
            status=AMDStatus.ANALYZING,
            confidence=0.5,
            speech_duration_ms=self._speech_ms,
            silence_duration_ms=self._post_speech_silence_ms,
            total_analyzed_ms=self._total_ms,
            safe_harbor_cleared=False
        )

    def _detect_tones(self, frame: AudioFrame) -> Optional[AMDStatus]:
        """FFT analysis for Fax tones (1100Hz / 2100Hz)."""
        samples = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32)
        if len(samples) < 128:
            return None
        fft = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), 1.0 / frame.sample_rate)

        peak_idx = np.argmax(fft)
        peak_freq = freqs[peak_idx]
        peak_mag = fft[peak_idx]
        total_mag = np.sum(fft) + 1e-6

        # Check for pure tone concentration
        if (peak_mag / total_mag) > 0.45:
            # 1100Hz CNG or 2100Hz CED fax tone
            if 1050 <= peak_freq <= 1150 or 2050 <= peak_freq <= 2150:
                return AMDStatus.FAX
        return None
