"""
Paced TTS Egress Playout Buffer
================================
Buffers generated TTS audio chunks, pacing their transmission to the telephony
transport at an exact 20ms cadence using a monotonic clock.

Core features:
- Monotonic clock timing precision
- Exactly 1 frame per 20ms cadence
- Controlled underflow behavior (silence injection / idle state)
- Sub-millisecond buffer purge for instant barge-in response
- High-resolution drift compensation
"""

from __future__ import annotations
import asyncio
import collections
import time
from dataclasses import dataclass
from typing import Optional, Deque, Callable, Awaitable
from shadow_voice.core.audio import (
    AudioFrame,
    FRAME_BYTES_16K,
    SILENCE_FRAME_16K,
    SAMPLE_RATE_16K,
    chunk_pcm
)


@dataclass
class PlayoutMetrics:
    frames_enqueued: int = 0
    frames_played: int = 0
    underflow_count: int = 0
    flush_count: int = 0
    jitter_ms_max: float = 0.0
    current_queued_frames: int = 0


class PacedPlayoutBuffer:
    """
    Egress Playout Buffer that feeds telephony transport.
    Provides sub-millisecond barge-in flushing.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE_16K,
        frame_bytes: int = FRAME_BYTES_16K,
        max_buffer_seconds: float = 10.0
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_bytes = frame_bytes
        self.max_frames: int = int((max_buffer_seconds * 1000) / 20)
        self.queue: Deque[AudioFrame] = collections.deque()
        self.metrics = PlayoutMetrics()
        self._is_active: bool = False
        self._seq: int = 0
        self._flush_event = asyncio.Event()

    @property
    def buffered_duration_ms(self) -> float:
        return len(self.queue) * 20.0

    @property
    def has_audio(self) -> bool:
        return len(self.queue) > 0

    def enqueue_pcm(self, pcm_bytes: bytes) -> int:
        """
        Takes raw PCM audio (e.g., from TTS generator), slices into 20ms frames,
        and enqueues them into the playout buffer.
        Returns the number of frames enqueued.
        """
        chunks = chunk_pcm(pcm_bytes, self.frame_bytes)
        count = 0
        for chunk in chunks:
            if len(self.queue) >= self.max_frames:
                break
            frame = AudioFrame(
                data=chunk,
                sample_rate=self.sample_rate,
                sequence_num=self._seq,
                timestamp_ms=self._seq * 20.0
            )
            self._seq += 1
            self.queue.append(frame)
            count += 1
            self.metrics.frames_enqueued += 1

        self.metrics.current_queued_frames = len(self.queue)
        return count

    def flush(self) -> int:
        """
        Instantaneously purge all queued audio.
        CRITICAL FOR BARGE-IN: Stops any unplayed TTS audio from reaching the user's ear.
        Returns the count of purged frames.
        """
        purged_count = len(self.queue)
        self.queue.clear()
        self.metrics.flush_count += 1
        self.metrics.current_queued_frames = 0
        self._flush_event.set()
        return purged_count

    def pop_frame(self) -> Optional[AudioFrame]:
        """
        Pulls a single 20ms frame from the buffer.
        Returns None if no audio is buffered (idle).
        """
        if not self.queue:
            self.metrics.underflow_count += 1
            self.metrics.current_queued_frames = 0
            return None

        frame = self.queue.popleft()
        self.metrics.frames_played += 1
        self.metrics.current_queued_frames = len(self.queue)
        return frame

    async def stream_paced(
        self,
        sink_callback: Callable[[AudioFrame], Awaitable[None]],
        stop_event: asyncio.Event
    ) -> None:
        """
        Asynchronous runner that ticks every 20ms using a monotonic clock,
        pulling frames from the buffer and sending them to the transport sink.
        """
        FRAME_NS = 20_000_000  # 20ms in nanoseconds
        next_tick = time.monotonic_ns()

        while not stop_event.is_set():
            now = time.monotonic_ns()
            sleep_ns = next_tick - now
            if sleep_ns > 0:
                await asyncio.sleep(sleep_ns / 1_000_000_000.0)

            frame = self.pop_frame()
            if frame is not None:
                await sink_callback(frame)

            next_tick += FRAME_NS
            # If we fell severely behind (e.g. OS scheduling delay), reset next_tick to prevent audio blast
            current_time = time.monotonic_ns()
            if current_time - next_tick > 50_000_000:  # >50ms drift
                next_tick = current_time + FRAME_NS
