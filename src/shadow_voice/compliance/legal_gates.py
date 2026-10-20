"""
Legal Architecture & Pre-Dial Legal Gates
=========================================
Fulfills Section 8.7 Gap-Fill & Phase 0/4 Compliance Gates:
- Jurisdiction scope check (explicit confirmation of US TCPA/TSR scope; blocks unreviewed international dials)
- Destination number type classification (Wireless, Residential, B2B)
- Consent provenance check (Prior Express Written Consent vs EBR vs B2B)
- Two-Party Call Recording Consent state resolution
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Set

logger = logging.getLogger("shadow_voice.legal_gates")

# States requiring all-party / two-party consent for audio recording
TWO_PARTY_RECORDING_STATES: Set[str] = {
    "CA", "FL", "IL", "MD", "MA", "MI", "MT", "NV", "NH", "PA", "WA", "CT"
}

ALLOWED_JURISDICTIONS: Set[str] = {"US"}


class NumberDestinationType(str, Enum):
    WIRELESS = "WIRELESS"
    RESIDENTIAL_LANDLINE = "RESIDENTIAL_LANDLINE"
    BUSINESS = "BUSINESS"
    UNKNOWN = "UNKNOWN"


@dataclass
class PreDialLegalApproval:
    approved: bool
    jurisdiction: str
    destination_type: NumberDestinationType
    consent_provenance: str
    recording_consent_required: str  # "ONE_PARTY" or "TWO_PARTY"
    rejection_reason: Optional[str] = None


class LegalGateEnforcer:
    """Pre-dial legal clearance engine."""

    def __init__(self, allowed_jurisdictions: Optional[Set[str]] = None) -> None:
        self.allowed_jurisdictions = allowed_jurisdictions or ALLOWED_JURISDICTIONS

    def check_pre_dial_legal_basis(
        self,
        country_code: str,
        state_code: Optional[str],
        destination_type: NumberDestinationType,
        consent_provenance: str
    ) -> PreDialLegalApproval:
        """
        Validates legal authorization before dialing.
        Fails safe if jurisdiction is not confirmed or consent provenance is missing for wireless/residential calls.
        """
        # 1. Jurisdiction check (Section 8.7)
        c_code = (country_code or "UNKNOWN").strip().upper()
        if c_code not in self.allowed_jurisdictions:
            reason = f"BLOCKED: Jurisdiction '{country_code}' is outside approved scope ({self.allowed_jurisdictions}). International calls require independent legal review."
            logger.error(f"[LEGAL GATE REJECTION] {reason}")
            return PreDialLegalApproval(
                approved=False,
                jurisdiction=c_code,
                destination_type=destination_type,
                consent_provenance=consent_provenance,
                recording_consent_required="UNKNOWN",
                rejection_reason=reason
            )

        # 2. Consent Provenance Check for Wireless / Residential Automated Dialing
        if destination_type in (NumberDestinationType.WIRELESS, NumberDestinationType.RESIDENTIAL_LANDLINE):
            consent_norm = (consent_provenance or "").strip().upper()
            if not consent_norm or consent_norm == "NONE":
                reason = f"BLOCKED: TCPA violation risk. Prior express written consent is legally required before dialing {destination_type.value} numbers."
                logger.error(f"[LEGAL GATE REJECTION] {reason}")
                return PreDialLegalApproval(
                    approved=False,
                    jurisdiction=c_code,
                    destination_type=destination_type,
                    consent_provenance=consent_provenance,
                    recording_consent_required="UNKNOWN",
                    rejection_reason=reason
                )

        # 3. Recording Consent Determination
        s_code = state_code.strip().upper() if state_code else None
        rec_type = "TWO_PARTY" if s_code and s_code in TWO_PARTY_RECORDING_STATES else "ONE_PARTY"

        return PreDialLegalApproval(
            approved=True,
            jurisdiction=c_code,
            destination_type=destination_type,
            consent_provenance=consent_provenance,
            recording_consent_required=rec_type,
            rejection_reason=None
        )

