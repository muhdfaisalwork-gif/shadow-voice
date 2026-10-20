"""
Do-Not-Call (DNC) Compliance Engine
====================================
Implements multi-tiered DNC suppression:
1. National DNC Registry:
   - Enforces strict 31-day maximum staleness threshold
   - Rule: Outbound dialing is BLOCKED if National DNC snapshot exceeds 31 days!
2. State-Level DNC Registries (Section 8.2 Gap-Fill):
   - Supports state-specific lists for targeted campaign states
3. Internal / Company DNC:
   - Instant real-time suppression and propagation
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Set, Dict, Optional, Tuple

logger = logging.getLogger("shadow_voice.dnc")

SECONDS_PER_DAY = 86400.0
MAX_NATIONAL_DNC_STALENESS_DAYS = 31.0


@dataclass
class DNCCheckResult:
    allowed: bool
    phone_number: str
    is_national_dnc: bool
    is_state_dnc: bool
    is_internal_dnc: bool
    national_dnc_stale: bool
    rejection_reason: Optional[str] = None

    @property
    def is_clean(self) -> bool:
        """Compatibility property for clean/allowed status."""
        return self.allowed

    @property
    def block_reason(self) -> Optional[str]:
        """Compatibility property for rejection reason."""
        return self.rejection_reason


class DNCScrubbingEngine:
    """
    Central DNC scrubbing engine enforcing National, State, and Internal suppression lists.
    """

    def __init__(self) -> None:
        self.internal_dnc_list: Set[str] = set()
        self.state_dnc_lists: Dict[str, Set[str]] = {}
        self.national_dnc_list: Set[str] = set()
        self.national_dnc_last_updated: float = time.time()  # Timestamp of latest downloaded snapshot

    @staticmethod
    def _normalize(phone_number: Optional[str]) -> str:
        clean = "".join(filter(str.isdigit, phone_number or ""))
        if clean.startswith("1") and len(clean) == 11:
            clean = clean[1:]
        return clean

    def update_national_dnc_snapshot(self, numbers: Set[str], snapshot_timestamp: Optional[float] = None) -> None:
        """Loads a fresh National DNC registry snapshot."""
        self.national_dnc_list = {self._normalize(num) for num in numbers if self._normalize(num)}
        self.national_dnc_last_updated = snapshot_timestamp or time.time()
        logger.info(f"[NATIONAL DNC] Loaded {len(self.national_dnc_list)} numbers. Updated at: {self.national_dnc_last_updated}")

    def is_national_dnc_fresh(self, current_time: Optional[float] = None) -> bool:
        """Verifies that the National DNC registry snapshot is <= 31 days old."""
        now = current_time or time.time()
        age_days = (now - self.national_dnc_last_updated) / SECONDS_PER_DAY
        return age_days <= MAX_NATIONAL_DNC_STALENESS_DAYS

    def add_internal_dnc(self, phone_number: str, reason: str = "CONSUMER_REQUEST") -> None:
        clean = self._normalize(phone_number)
        if clean:
            self.internal_dnc_list.add(clean)
            logger.warning(f"[INTERNAL DNC] Suppressed number {clean}. Reason: {reason}")

    def add_state_dnc(self, state: str, numbers: Set[str]) -> None:
        state_upper = (state or "").strip().upper()
        self.state_dnc_lists[state_upper] = {self._normalize(num) for num in numbers if self._normalize(num)}
        logger.info(f"[STATE DNC] Loaded {len(numbers)} numbers for state {state_upper}")

    def scrub_phone_number(
        self,
        phone_number: str,
        state: Optional[str] = None,
        current_time: Optional[float] = None
    ) -> DNCCheckResult:
        """
        Pre-dial compliance check against all DNC tiers.
        """
        clean = self._normalize(phone_number)

        if len(clean) < 7:
            return DNCCheckResult(
                allowed=False,
                phone_number=phone_number,
                is_national_dnc=False,
                is_state_dnc=False,
                is_internal_dnc=False,
                national_dnc_stale=False,
                rejection_reason="BLOCKED: Invalid phone number format (must contain at least 7 digits)."
            )

        now = current_time or time.time()
        is_fresh = self.is_national_dnc_fresh(now)

        # 1. CRITICAL STALENESS GATE: If National DNC is older than 31 days, ALL dialing is halted!
        if not is_fresh:
            age_days = (now - self.national_dnc_last_updated) / SECONDS_PER_DAY
            reason = f"CRITICAL: Outbound dialing BLOCKED. National DNC snapshot is {age_days:.1f} days old (exceeds 31-day legal limit)."
            logger.critical(f"[DNC STALENESS BLOCK] {reason}")
            return DNCCheckResult(
                allowed=False,
                phone_number=phone_number,
                is_national_dnc=False,
                is_state_dnc=False,
                is_internal_dnc=False,
                national_dnc_stale=True,
                rejection_reason=reason
            )

        # 2. Check Internal / Company DNC
        if clean in self.internal_dnc_list:
            reason = f"BLOCKED: Phone number is on Internal Company DNC list."
            return DNCCheckResult(
                allowed=False,
                phone_number=phone_number,
                is_national_dnc=False,
                is_state_dnc=False,
                is_internal_dnc=True,
                national_dnc_stale=False,
                rejection_reason=reason
            )

        # 3. Check State-level DNC
        if state:
            state_key = state.strip().upper()
            state_list = self.state_dnc_lists.get(state_key, set())
            if clean in state_list:
                reason = f"BLOCKED: Phone number is on {state_key} State DNC list."
                return DNCCheckResult(
                    allowed=False,
                    phone_number=phone_number,
                    is_national_dnc=False,
                    is_state_dnc=True,
                    is_internal_dnc=False,
                    national_dnc_stale=False,
                    rejection_reason=reason
                )

        # 4. Check National DNC
        if clean in self.national_dnc_list:
            reason = f"BLOCKED: Phone number is on the National DNC Registry."
            return DNCCheckResult(
                allowed=False,
                phone_number=phone_number,
                is_national_dnc=True,
                is_state_dnc=False,
                is_internal_dnc=False,
                national_dnc_stale=False,
                rejection_reason=reason
            )

        return DNCCheckResult(
            allowed=True,
            phone_number=phone_number,
            is_national_dnc=False,
            is_state_dnc=False,
            is_internal_dnc=False,
            national_dnc_stale=False,
            rejection_reason=None
        )
