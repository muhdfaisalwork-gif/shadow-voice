"""
Telephony Transport Adapter Abstraction
=======================================
Architecture Rule:
SIP/RTP and AudioSocket are separate transport adapters feeding the same
audio/session core. Do not couple conversational logic directly to either protocol.
"""

from __future__ import annotations
import abc
from typing import Callable, Awaitable, Optional
from shadow_voice.core.audio import AudioFrame
from shadow_voice.telephony.metadata import CallMetadata


class BaseTransportAdapter(abc.ABC):
    """Abstract interface defining telephony audio transport."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Start the transport listener / socket."""
        pass

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop and tear down the transport."""
        pass

    @abc.abstractmethod
    async def send_audio_frame(self, session_id: str, frame: AudioFrame) -> None:
        """Transmit an egress audio frame to the remote party."""
        pass

    @abc.abstractmethod
    async def hangup_call(self, session_id: str, reason: str = "NORMAL_CLEARING") -> None:
        """Terminate the call at the telephony transport layer."""
        pass

    @abc.abstractmethod
    def set_ingress_handler(
        self,
        handler: Callable[[str, AudioFrame, CallMetadata], Awaitable[None]]
    ) -> None:
        """Set callback invoked whenever incoming audio arrives from the caller."""
        pass

    @abc.abstractmethod
    def set_session_end_handler(
        self,
        handler: Callable[[str, str], Awaitable[None]]
    ) -> None:
        """Set callback invoked when the remote transport hangs up."""
        pass
