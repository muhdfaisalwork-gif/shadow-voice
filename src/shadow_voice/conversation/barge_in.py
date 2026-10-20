"""
Barge-In Controller & State Machine
===================================
Orchestrates instant interruption when user speaks while TTS is playing:
1. Detect speech start via VAD during playback
2. Purge paced playout buffer (<5 ms)
3. Cancel active LLM streaming task
4. Cancel active TTS audio generation task
5. Prevent stale audio from reaching egress
6. Preserve and re-feed user speech frames into STT
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional, List
from shadow_voice.core.playout_buffer import PacedPlayoutBuffer
from shadow_voice.core.audio import AudioFrame

logger = logging.getLogger("shadow_voice.barge_in")


@dataclass
class BargeInMetrics:
    total_barge_in_count: int = 0
    last_flush_latency_ms: float = 0.0
    frames_purged_last_event: int = 0


class BargeInController:
    """
    Coordinates sub-millisecond barge-in execution across playout buffer, TTS, and LLM tasks.
    """

    def __init__(self, playout_buffer: PacedPlayoutBuffer) -> None:
        self.playout_buffer = playout_buffer
        self.metrics = BargeInMetrics()

        self._active_llm_cancel_event: Optional[asyncio.Event] = None
        self._active_tts_cancel_event: Optional[asyncio.Event] = None
        self._is_speaking_tts: bool = False
        self._interrupted_frames: List[AudioFrame] = []

    def set_tts_active(
        self,
        is_active: bool,
        llm_cancel_event: Optional[asyncio.Event] = None,
        tts_cancel_event: Optional[asyncio.Event] = None
    ) -> None:
        """Called when TTS generation & playback starts or finishes."""
        self._is_speaking_tts = is_active
        self._active_llm_cancel_event = llm_cancel_event
        self._active_tts_cancel_event = tts_cancel_event
        if is_active:
            # Reset captured interruption frames at the start of a new playback turn
            self._interrupted_frames.clear()

    @property
    def is_tts_speaking(self) -> bool:
        return self._is_speaking_tts or self.playout_buffer.has_audio

    def handle_user_speech_detected(self, initial_frame: Optional[AudioFrame] = None) -> bool:
        """
        Invoked immediately when VAD signals speech start while TTS is active.
        Executes emergency flush and cancellation.
        Returns True if a barge-in was executed, False if system was already idle.
        """
        if not self.is_tts_speaking:
            return False

        t0 = time.time() * 1000.0

        # 1. Signal cancellation to LLM task
        if self._active_llm_cancel_event and not self._active_llm_cancel_event.is_set():
            self._active_llm_cancel_event.set()

        # 2. Signal cancellation to TTS task
        if self._active_tts_cancel_event and not self._active_tts_cancel_event.is_set():
            self._active_tts_cancel_event.set()

        # 3. Purge playout buffer instantly
        purged = self.playout_buffer.flush()

        t1 = time.time() * 1000.0
        flush_latency = max(0.01, t1 - t0)

        # 4. Track metrics
        self.metrics.total_barge_in_count += 1
        self.metrics.frames_purged_last_event = purged
        self.metrics.last_flush_latency_ms = flush_latency
        self._is_speaking_tts = False

        # 5. Capture the initial speech frame that caused the trigger
        if initial_frame:
            self._interrupted_frames.append(initial_frame)

        logger.info(
            f"[BARGE-IN TRIGGERED] Flushed {purged} frames ({purged * 20}ms audio) in {flush_latency:.2f}ms. "
            f"Cancelled active LLM & TTS tasks."
        )
        return True

    def get_interrupted_speech_frames(self) -> List[AudioFrame]:
        """Returns and clears captured frames from the start of the user's interruption."""
        frames = list(self._interrupted_frames)
        self._interrupted_frames.clear()
        return frames
