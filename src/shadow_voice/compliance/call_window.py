"""
Call-Window Enforcement
=======================
Enforces TCPA / TSR local-time restrictions:
Calls permitted only between 8:00 AM and 9:00 PM in the called-party local timezone.
Resolves local time using phone number NPA area code mapping.
"""

from __future__ import annotations
import datetime
import logging
from dataclasses import dataclass
from typing import Optional, Dict
from zoneinfo import ZoneInfo

logger = logging.getLogger("shadow_voice.call_window")

# Representative North American Area Code to IANA Timezone mapping
AREA_CODE_TIMEZONE_MAP: Dict[str, str] = {
    # Eastern (ET)
    "212": "America/New_York", "718": "America/New_York", "516": "America/New_York",
    "305": "America/New_York", "407": "America/New_York", "813": "America/New_York",
    "202": "America/New_York", "404": "America/New_York", "617": "America/New_York",
    # Central (CT)
    "312": "America/Chicago", "773": "America/Chicago", "847": "America/Chicago",
    "713": "America/Chicago", "214": "America/Chicago", "512": "America/Chicago",
    "615": "America/Chicago", "612": "America/Chicago",
    # Mountain (MT)
    "303": "America/Denver", "720": "America/Denver", "801": "America/Denver",
    "480": "America/Phoenix", "602": "America/Phoenix", # Arizona no DST
    # Pacific (PT)
    "213": "America/Los_Angeles", "310": "America/Los_Angeles", "415": "America/Los_Angeles",
    "619": "America/Los_Angeles", "206": "America/Los_Angeles", "503": "America/Los_Angeles",
}


@dataclass
class CallWindowCheckResult:
    allowed: bool
    called_number: str
    resolved_timezone: str
    local_time_str: str
    local_hour: float
    reason: str

    @property
    def is_permitted(self) -> bool:
        """Compatibility property for allowed status."""
        return self.allowed


class CallWindowEnforcer:
    """Restricts dialing to permissible legal daytime hours."""

    def __init__(
        self,
        start_hour: float = 8.0,   # 8:00 AM
        end_hour: float = 21.0,    # 9:00 PM
        default_tz: str = "America/New_York"
    ) -> None:
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.default_tz = default_tz

    def resolve_timezone(self, phone_number: str) -> str:
        clean = "".join(filter(str.isdigit, phone_number or ""))
        if clean.startswith("1") and len(clean) == 11:
            clean = clean[1:]
        if len(clean) >= 3:
            area_code = clean[:3]
            return AREA_CODE_TIMEZONE_MAP.get(area_code, self.default_tz)
        return self.default_tz

    def is_call_permitted(
        self,
        phone_number: str,
        simulated_now_utc: Optional[datetime.datetime] = None
    ) -> CallWindowCheckResult:
        tz_str = self.resolve_timezone(phone_number)
        try:
            tz = ZoneInfo(tz_str)
        except Exception:
            tz_str = self.default_tz
            tz = ZoneInfo(self.default_tz)

        now_utc = simulated_now_utc or datetime.datetime.now(datetime.timezone.utc)
        local_dt = now_utc.astimezone(tz)
        local_hour = local_dt.hour + (local_dt.minute / 60.0)

        is_within_window = (self.start_hour <= local_hour < self.end_hour)
        local_time_str = local_dt.strftime("%Y-%m-%d %I:%M %p %Z")

        if is_within_window:
            reason = f"Call permitted: Local time {local_time_str} is within 8:00 AM - 9:00 PM window"
        else:
            reason = f"CALL BLOCKED: Local time {local_time_str} is outside permitted 8:00 AM - 9:00 PM legal calling window"
            logger.warning(f"[CALL-WINDOW] {reason} for number {phone_number}")

        return CallWindowCheckResult(
            allowed=is_within_window,
            called_number=phone_number,
            resolved_timezone=tz_str,
            local_time_str=local_time_str,
            local_hour=local_hour,
            reason=reason
        )
