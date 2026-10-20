"""
Base Dialer Adapter Interface (ABC)
====================================
Architecture Rule:
VICIdial is the first concrete CTI implementation, not a hard-coded dependency
of the conversational engine. The BaseDialerAdapter decouples CTI operations.
"""

from __future__ import annotations
import abc
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class TransferResult:
    success: bool
    session_id: str
    target_extension: str
    transfer_type: str  # "BLIND" or "WARM"
    message: str


@dataclass
class DispositionResult:
    success: bool
    session_id: str
    lead_id: str
    disposition_code: str
    persisted: bool
    message: str


class BaseDialerAdapter(abc.ABC):
    """Abstract dialer interface for telephony integration."""

    @abc.abstractmethod
    async def transfer_blind(self, session_id: str, lead_id: str, extension: str) -> TransferResult:
        """Executes an unannounced blind transfer to an agent queue."""
        pass

    @abc.abstractmethod
    async def transfer_warm(
        self,
        session_id: str,
        lead_id: str,
        extension: str,
        whisper_context: str
    ) -> TransferResult:
        """Executes a consultative warm transfer with context handoff."""
        pass

    @abc.abstractmethod
    async def hangup_call(self, session_id: str, reason: str = "NORMAL_CLEARING") -> bool:
        """Signals dialer to end the call."""
        pass

    @abc.abstractmethod
    async def set_disposition(
        self,
        session_id: str,
        lead_id: str,
        disposition_code: str,
        notes: str = ""
    ) -> DispositionResult:
        """Writes call disposition and agent notes back to CTI system."""
        pass

    @abc.abstractmethod
    async def suppress_dnc(self, phone_number: str, campaign_id: str, reason: str) -> bool:
        """Adds phone number to dialer-level DNC suppression list."""
        pass

    @abc.abstractmethod
    async def verify_dnc_suppression_state(self, phone_number: str) -> bool:
        """
        Reads back actual DNC database state to verify suppression.
        RULE: HTTP 200 is not proof. Must confirm record is active in suppression table.
        """
        pass
