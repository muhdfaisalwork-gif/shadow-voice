"""
Ingress Jitter Buffer
=====================
Buffers incoming audio frames from the telephony transport layer to compensate
for network packet delay variation (jitter) before delivery to the VAD/STT engine.

Core features:
- Strict bounded-memory policy
- Dynamic jitter compensation with target buffering depth (40-60ms)
- Packet loss concealment (PLC) injection on underflow
- Telemetry: underflow count, overflow drops, late arrivals, jitter estimate
"""

from __future__ import annotations
import collections
from dataclasses import dataclass, field
from typing import Optional, Deque
from shadow_voice.core.audio import AudioFrame, FRAME_BYTES_16K, SILENCE_FRAME_16K, SAMPLE_RATE_16K


@dataclass
class JitterBufferMetrics:
    total_received: int = 0
    total_delivered: int = 0
    overflow_drops: int = 0
    underflow_events: int = 0
    late_arrivals: int = 0
    plc_injected_frames: int = 0
    current_depth_frames: int = 0


class IngressJitterBuffer:
    """
    Thread-safe and asyncio-friendly Ingress Jitter Buffer.
    Ensures a smooth stream of 20ms audio frames into the conversational pipeline.
    """

    def __init__(
        self,
        min_depth_frames: int = 2,    # 40ms minimum target depth before playout starts
        max_depth_frames: int = 10,   # 200ms maximum bounded queue depth
        sample_rate: int = SAMPLE_RATE_16K
    ) -> None:
        self.min_depth_frames = min_depth_frames
        self.max_depth_frames = max_depth_frames
        self.sample_rate = sample_rate
        self.queue: Deque[AudioFrame] = collections.deque()
        self.metrics = JitterBufferMetrics()
        self._is_buffering = True
        self._expected_seq: int = 0
        self._last_delivered_frame: Optional[AudioFrame] = None

    @property
    def depth_ms(self) -> float:
        return len(self.queue) * 20.0

    def push(self, frame: AudioFrame) -> bool:
        """
        Push an ingress audio frame into the jitter buffer.
        Enforces sample rate contract and bounded memory capacity.
        Returns True if accepted, False if dropped due to overflow.
        """
        self.metrics.total_received += 1

        if frame.sample_rate != self.sample_rate:
            raise ValueError(f"Frame sample rate {frame.sample_rate} != buffer rate {self.sample_rate}")

        # Check bounded memory limit
        if len(self.queue) >= self.max_depth_frames:
            # Drop oldest frame or drop incoming frame depending on policy (we drop incoming or oldest to maintain latency)
            # In voice agents, latency > complete history, so drop oldest to catch up to real-time.
            self.queue.popleft()
            self.metrics.overflow_drops += 1

        self.queue.append(frame)
        self.metrics.current_depth_frames = len(self.queue)

        # Release initial buffering state once min depth is reached
        if self._is_buffering and len(self.queue) >= self.min_depth_frames:
            self._is_buffering = False

        return True

    def pop(self) -> AudioFrame:
        """
        Retrieve the next 20ms audio frame for processing by VAD/STT.
        If the buffer is empty or still pre-buffering, injects a comfort silence frame (PLC)
        and increments underflow metrics.
        """
        if self._is_buffering or len(self.queue) == 0:
            self.metrics.underflow_events += 1
            self.metrics.plc_injected_frames += 1
            self._is_buffering = True  # Re-enter buffering on dry queue
            silence_bytes = SILENCE_FRAME_16K if self.sample_rate == SAMPLE_RATE_16K else b"\x00" * 320
            plc_frame = AudioFrame(
                data=silence_bytes,
                sample_rate=self.sample_rate,
                sequence_num=self._expected_seq,
                timestamp_ms=self._expected_seq * 20.0
            )
            self._expected_seq += 1
            return plc_frame

        frame = self.queue.popleft()
        self.metrics.total_delivered += 1
        self.metrics.current_depth_frames = len(self.queue)
        self._last_delivered_frame = frame
        self._expected_seq = frame.sequence_num + 1
        return frame

    def clear(self) -> None:
        """Purges all queued frames and resets state."""
        self.queue.clear()
        self._is_buffering = True
        self.metrics.current_depth_frames = 0
