"""
Telephony Session Metadata Normalizer
======================================
Normalizes heterogeneous telephony and CTI metadata:
SIP headers, X-headers, UUI, Asterisk channel variables, VICIdial lead context.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class CallMetadata:
    """Normalized call session metadata across carriers and dialers."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    call_id: Optional[str] = None
    lead_id: Optional[str] = None
    campaign_id: Optional[str] = None
    list_id: Optional[str] = None
    called_number: str = ""       # Destination phone number (E.164)
    caller_id_number: str = ""    # Outbound caller ID / ANI
    caller_id_name: str = ""
    dialer_type: str = "vicidial"
    source_ip: str = ""
    sip_call_id: Optional[str] = None
    uui_data: Optional[str] = None
    custom_headers: Dict[str, str] = field(default_factory=dict)
    answered_at: Optional[float] = None
    is_inbound: bool = False

    @classmethod
    def from_asterisk_headers(
        cls,
        session_uuid: str,
        headers: Dict[str, str],
        channel_vars: Optional[Dict[str, Any]] = None
    ) -> "CallMetadata":
        """Builds normalized metadata from Asterisk channel / SIP headers."""
        cv = channel_vars or {}
        return cls(
            session_id=session_uuid,
            call_id=cv.get("UNIQUEID") or headers.get("X-Asterisk-Uniqueid"),
            lead_id=cv.get("VICI_LEAD_ID") or headers.get("X-VICI-Lead-ID") or headers.get("X-Lead-ID"),
            campaign_id=cv.get("VICI_CAMPAIGN") or headers.get("X-VICI-Campaign") or "DEFAULT_CAMPAIGN",
            list_id=cv.get("VICI_LIST_ID") or headers.get("X-VICI-List-ID"),
            called_number=cv.get("CONNECTEDLINE(num)") or cv.get("EXTEN") or headers.get("X-Called-Number", ""),
            caller_id_number=cv.get("CALLERID(num)") or headers.get("X-Caller-ID", ""),
            caller_id_name=cv.get("CALLERID(name)") or headers.get("X-Caller-Name", ""),
            sip_call_id=headers.get("Call-ID") or cv.get("SIPCALLID"),
            uui_data=headers.get("User-to-User"),
            custom_headers=headers
        )
