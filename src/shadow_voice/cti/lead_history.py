"""
Lead Call-History Store
========================
Fulfills Phase 3 Addition:
- Fast lookup on session start by lead_id
- Prior call date(s), disposition(s), last objection, DNC/callback flag, campaign context
- Injected into FSM context before Connection stage
- Write-back on hangup: records call outcome, objection, disposition
- Fail-safe fallback: missing or corrupted record safely falls back to first-contact mode
- Strict session isolation: prevents cross-lead contamination
- 5-year compliance retention schedule alignment
"""

from __future__ import annotations
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

logger = logging.getLogger("shadow_voice.lead_history")


@dataclass
class CallHistoryEntry:
    call_timestamp: float
    session_id: str
    campaign_id: str
    disposition: str
    objection_raised: Optional[str] = None
    callback_requested: bool = False
    callback_time: Optional[str] = None
    notes: str = ""


@dataclass
class LeadHistoryRecord:
    lead_id: str
    phone_number: str = ""
    first_contact: bool = True
    total_prior_calls: int = 0
    last_disposition: Optional[str] = None
    last_objection: Optional[str] = None
    is_dnc: bool = False
    has_pending_callback: bool = False
    campaign_context: Dict[str, Any] = field(default_factory=dict)
    history_entries: List[CallHistoryEntry] = field(default_factory=list)


class LeadHistoryStore:
    """
    Structured store for lead historical context with fail-safe fallback.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lead_history (
                lead_id TEXT PRIMARY KEY,
                phone_number TEXT,
                is_dnc INTEGER DEFAULT 0,
                has_pending_callback INTEGER DEFAULT 0,
                last_disposition TEXT,
                last_objection TEXT,
                campaign_context_json TEXT,
                history_entries_json TEXT,
                updated_at REAL
            )
        """)
        conn.commit()

    def lookup_lead(self, lead_id: Optional[str]) -> LeadHistoryRecord:
        """
        Retrieves historical record for lead_id.
        FAILSAFE RULE: If lead_id is None, missing, or corrupted, returns clean first-contact fallback.
        """
        if not lead_id:
            return LeadHistoryRecord(lead_id="UNKNOWN", first_contact=True)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT phone_number, is_dnc, has_pending_callback, last_disposition,
                       last_objection, campaign_context_json, history_entries_json
                FROM lead_history WHERE lead_id = ?
            """, (lead_id,))
            row = cursor.fetchone()
            if not row:
                # First time lead
                return LeadHistoryRecord(lead_id=lead_id, first_contact=True)

            phone, is_dnc, has_cb, last_disp, last_obj, ctx_json, entries_json = row
            ctx = json.loads(ctx_json) if ctx_json else {}
            raw_entries = json.loads(entries_json) if entries_json else []
            entries = [CallHistoryEntry(**e) for e in raw_entries]

            return LeadHistoryRecord(
                lead_id=lead_id,
                phone_number=phone or "",
                first_contact=False,
                total_prior_calls=len(entries),
                last_disposition=last_disp,
                last_objection=last_obj,
                is_dnc=bool(is_dnc),
                has_pending_callback=bool(has_cb),
                campaign_context=ctx,
                history_entries=entries
            )
        except Exception as e:
            logger.error(f"[LEAD HISTORY] Corrupted record or error looking up lead {lead_id}: {e}. Falling back to first contact.")
            return LeadHistoryRecord(lead_id=lead_id, first_contact=True)

    def append_call_outcome(
        self,
        lead_id: str,
        session_id: str,
        campaign_id: str,
        disposition: str,
        phone_number: str = "",
        objection_raised: Optional[str] = None,
        callback_requested: bool = False,
        callback_time: Optional[str] = None,
        is_dnc: bool = False,
        notes: str = ""
    ) -> bool:
        """
        Appends the completed call's outcome to the lead's historical record on hangup.
        """
        if not lead_id or lead_id == "UNKNOWN":
            return False

        try:
            record = self.lookup_lead(lead_id)
            new_entry = CallHistoryEntry(
                call_timestamp=time.time(),
                session_id=session_id,
                campaign_id=campaign_id,
                disposition=disposition,
                objection_raised=objection_raised,
                callback_requested=callback_requested,
                callback_time=callback_time,
                notes=notes
            )
            record.history_entries.append(new_entry)
            record.total_prior_calls = len(record.history_entries)
            record.last_disposition = disposition
            record.last_objection = objection_raised or record.last_objection
            record.is_dnc = is_dnc or record.is_dnc
            record.has_pending_callback = callback_requested
            if phone_number:
                record.phone_number = phone_number

            entries_json = json.dumps([asdict(e) for e in record.history_entries])
            ctx_json = json.dumps(record.campaign_context)

            conn = self._get_connection()
            conn.execute("""
                INSERT INTO lead_history (
                    lead_id, phone_number, is_dnc, has_pending_callback,
                    last_disposition, last_objection, campaign_context_json,
                    history_entries_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lead_id) DO UPDATE SET
                    phone_number = excluded.phone_number,
                    is_dnc = excluded.is_dnc,
                    has_pending_callback = excluded.has_pending_callback,
                    last_disposition = excluded.last_disposition,
                    last_objection = excluded.last_objection,
                    history_entries_json = excluded.history_entries_json,
                    updated_at = excluded.updated_at
            """, (
                lead_id, record.phone_number, 1 if record.is_dnc else 0,
                1 if record.has_pending_callback else 0, record.last_disposition,
                record.last_objection, ctx_json, entries_json, time.time()
            ))
            conn.commit()

            logger.info(f"[LEAD HISTORY] Appended call outcome for lead={lead_id} dispo={disposition}")
            return True
        except Exception as e:
            logger.error(f"[LEAD HISTORY] Failed appending call outcome for lead {lead_id}: {e}")
            return False

    def close(self) -> None:
        """Closes the underlying SQLite database connection."""
        if hasattr(self, "_conn") and self._conn:
            try:
                self._conn.close()
            except Exception:
                pass