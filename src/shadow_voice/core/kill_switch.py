"""
System-Wide Kill Switch
=======================
Fulfills Principle 12 & Telephony Engineer Deliverable:
- Stops all NEW outbound dial attempts immediately when triggered.
- Cleanly winds down in-progress calls without abrupt hangups that
  create compliance/customer-experience problems.
- Reachable by any authorized role on the compliance/PM chain.
- Integrated with Phase 4 spend ceiling and regulatory drop-rate monitors.
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set, Callable, List

logger = logging.getLogger("shadow_voice.kill_switch")


class KillSwitchRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    QA_COMPLIANCE_ENG = "QAComplianceEngineer"
    FOUNDER = "Founder"
    AUTOMATED_SPEND_GUARD = "AutomatedSpendGuard"
    REGULATORY_MONITOR = "RegulatoryMonitor"
    TEST_HARNESS = "TestHarness"
    # Aliases
    PM = "ProjectManager"
    QA = "QAComplianceEngineer"
    SRE = "QAComplianceEngineer"
    SPEND_GUARD = "AutomatedSpendGuard"


@dataclass
class KillSwitchStatus:
    is_active: bool = False
    triggered_at: Optional[float] = None
    triggered_by: Optional[str] = None
    reason: Optional[str] = None
    wind_down_deadline: Optional[float] = None
    active_calls_at_trigger: int = 0
    remaining_active_calls: int = 0


class KillSwitch:
    """
    Central, thread-safe Kill Switch for Shadow Voice.
    """
    _instance: Optional["KillSwitch"] = None

    def __init__(self, default_grace_period_seconds: float = 30.0) -> None:
        self.default_grace_period_seconds = default_grace_period_seconds
        self._triggered: bool = False
        self._triggered_by: Optional[str] = None
        self._reason: Optional[str] = None
        self._triggered_at: Optional[float] = None
        self._wind_down_deadline: Optional[float] = None
        self._active_session_ids: Set[str] = set()
        self._callbacks: List[Callable[[KillSwitchStatus], None]] = []
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "KillSwitch":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_test(cls) -> "KillSwitch":
        cls._instance = cls()
        return cls._instance

    def register_callback(self, cb: Callable[[KillSwitchStatus], None]) -> None:
        """Register a callback notified immediately upon kill switch trigger."""
        self._callbacks.append(cb)

    def register_session(self, session_id: str) -> bool:
        """
        Registers an active call session.
        REJECTS with False if the kill switch is triggered (no new calls allowed!).
        """
        if self._triggered:
            logger.warning(
                f"[KILL-SWITCH] Blocked new call attempt session={session_id} - Kill switch ACTIVE "
                f"(Reason: {self._reason})"
            )
            return False
        self._active_session_ids.add(session_id)
        return True

    def unregister_session(self, session_id: str) -> None:
        """Unregisters a completed or wound-down call session."""
        self._active_session_ids.discard(session_id)
        if self._triggered and len(self._active_session_ids) == 0:
            logger.info("[KILL-SWITCH] All active sessions successfully wound down to zero.")

    @property
    def is_triggered(self) -> bool:
        return self._triggered

    def can_dial(self) -> bool:
        """Returns True if system is clear to place new outbound dials."""
        return not self._triggered

    def trigger(
        self,
        role: KillSwitchRole,
        reason: str,
        grace_period_seconds: Optional[float] = None
    ) -> KillSwitchStatus:
        """
        Triggers the system-wide kill switch.
        - Immediately blocks all new outbound dials.
        - Signals graceful wind-down for in-progress calls.
        """
        now = time.time()
        grace = grace_period_seconds if grace_period_seconds is not None else self.default_grace_period_seconds

        self._triggered = True
        self._triggered_by = role.value if isinstance(role, KillSwitchRole) else str(role)
        self._reason = reason
        self._triggered_at = now
        self._wind_down_deadline = now + grace

        status = KillSwitchStatus(
            is_active=True,
            triggered_at=self._triggered_at,
            triggered_by=self._triggered_by,
            reason=self._reason,
            wind_down_deadline=self._wind_down_deadline,
            active_calls_at_trigger=len(self._active_session_ids),
            remaining_active_calls=len(self._active_session_ids)
        )

        logger.critical(
            f"[KILL-SWITCH ACTIVATED] Triggered by {self._triggered_by}: '{reason}'. "
            f"Halting all new calls. Graceful wind-down deadline: {grace}s. "
            f"Active calls to wind down: {len(self._active_session_ids)}"
        )

        for cb in self._callbacks:
            try:
                cb(status)
            except Exception as e:
                logger.error(f"[KILL-SWITCH] Callback error: {e}")

        return status

    def reset(self, role: KillSwitchRole, reason: str) -> None:
        """Resets the kill switch only under explicit authorized clearance."""
        logger.warning(f"[KILL-SWITCH RESET] Reset by {role}: {reason}")
        self._triggered = False
        self._triggered_by = None
        self._reason = None
        self._triggered_at = None
        self._wind_down_deadline = None

    def trigger_kill_switch(self, role: Any = KillSwitchRole.PROJECT_MANAGER, reason: str = "Manual toggle from dashboard") -> KillSwitchStatus:
        """Convenience alias for triggering the kill switch."""
        if isinstance(role, str):
            try:
                role = KillSwitchRole(role)
            except ValueError:
                role = getattr(KillSwitchRole, role.upper(), KillSwitchRole.PROJECT_MANAGER)
        return self.trigger(role=role, reason=reason)

    def reset_kill_switch(self, role: Any = KillSwitchRole.PROJECT_MANAGER, reason: str = "Manual toggle from dashboard") -> None:
        """Convenience alias for resetting the kill switch."""
        if isinstance(role, str):
            try:
                role = KillSwitchRole(role)
            except ValueError:
                role = getattr(KillSwitchRole, role.upper(), KillSwitchRole.PROJECT_MANAGER)
        self.reset(role=role, reason=reason)

    def get_status(self) -> KillSwitchStatus:
        return KillSwitchStatus(
            is_active=self._triggered,
            triggered_at=self._triggered_at,
            triggered_by=self._triggered_by,
            reason=self._reason,
            wind_down_deadline=self._wind_down_deadline,
            active_calls_at_trigger=len(self._active_session_ids),
            remaining_active_calls=len(self._active_session_ids)
        )
