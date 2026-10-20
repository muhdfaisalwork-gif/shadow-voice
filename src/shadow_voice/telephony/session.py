"""
Telephony Session Lifecycle Manager
====================================
Maintains strict session isolation:
- Audio buffers (ingress jitter buffer, egress paced playout buffer)
- AMD detector state
- Call metadata
- Cancellation tokens & cleanup tasks
"""

from __future__ import annotations
import asyncio
import logging
import time
from enum import Enum
from typing import Optional, Dict, Any
from shadow_voice.core.jitter_buffer import IngressJitterBuffer
from shadow_voice.core.playout_buffer import PacedPlayoutBuffer
from shadow_voice.telephony.metadata import CallMetadata
from shadow_voice.telephony.amd import AnsweringMachineDetector, AMDStatus

logger = logging.getLogger("shadow_voice.session")


class SessionState(str, Enum):
    INITIALIZING = "INITIALIZING"
    AMD_ANALYZING = "AMD_ANALYZING"
    ACTIVE_CONVERSATION = "ACTIVE_CONVERSATION"
    BARGING_IN = "BARGING_IN"
    TRANSFERRING = "TRANSFERRING"
    WINDING_DOWN = "WINDING_DOWN"
    TERMINATED = "TERMINATED"


class TelephonySession:
    """Represents an isolated live call session."""

    def __init__(
        self,
        session_id: str,
        metadata: CallMetadata,
        sample_rate: int = 16000
    ) -> None:
        self.session_id = session_id
        self.metadata = metadata
        self.sample_rate = sample_rate

        self.state = SessionState.INITIALIZING
        self.created_at = time.time()
        self.connected_at: Optional[float] = None
        self.ended_at: Optional[float] = None

        # Isolated audio buffers
        self.jitter_buffer = IngressJitterBuffer(sample_rate=sample_rate)
        self.playout_buffer = PacedPlayoutBuffer(sample_rate=sample_rate)

        # Answering Machine Detector
        self.amd = AnsweringMachineDetector()

        # Cancellation and lifecycle control
        self.stop_event = asyncio.Event()
        self.is_active = True
        self.turn_index = 0
        self.disposition: Optional[str] = None
        self.transfer_destination: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or time.time()
        start = self.connected_at or self.created_at
        return max(0.0, end - start)

    def mark_connected(self) -> None:
        self.connected_at = time.time()
        self.state = SessionState.AMD_ANALYZING

    def mark_active(self) -> None:
        self.state = SessionState.ACTIVE_CONVERSATION

    def mark_winding_down(self) -> None:
        """Signals session to conclude naturally without abrupt cutoff."""
        if self.state != SessionState.TERMINATED:
            self.state = SessionState.WINDING_DOWN
            logger.info(f"[SESSION {self.session_id}] Marked for graceful wind-down.")

    def terminate(self, disposition: Optional[str] = None) -> None:
        """Tears down the session and cleans all resources."""
        self.state = SessionState.TERMINATED
        self.is_active = False
        self.ended_at = time.time()
        if disposition:
            self.disposition = disposition
        self.stop_event.set()
        self.jitter_buffer.clear()
        self.playout_buffer.flush()
        logger.info(f"[SESSION {self.session_id}] Terminated with disposition={self.disposition} duration={self.duration_seconds:.1f}s")
