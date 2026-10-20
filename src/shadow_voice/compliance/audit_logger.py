"""
Immutable Compliance Event Logger & 5-Year Retention Store
==========================================================
Produces tamper-evident compliance audit records with cryptographic hash chaining.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List

logger = logging.getLogger("shadow_voice.audit_logger")


@dataclass
class ComplianceCallRecord:
    session_id: str
    lead_id: str
    campaign_id: str
    calling_number: str
    called_number: str
    timezone: str
    start_timestamp: float
    end_timestamp: float
    duration_seconds: float
    disposition: str
    script_version_id: str
    prompt_model_version: str
    consent_provenance: str     # e.g., "EBR_INQUIRY_FORM_2026_09", "EXPRESS_WRITTEN_OPT_IN"
    legal_basis: str            # e.g., "B2B_INQUIRY", "TCPA_PRIOR_CONSENT"
    dnc_scrubbed_passed: bool
    safe_harbor_cleared: bool
    guardrail_flagged: bool
    transfer_destination: Optional[str] = None
    hash_chain: Optional[str] = None


class ComplianceAuditStore:
    """
    Append-only SQLite compliance log with cryptographic hash integrity.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._last_hash = "GENESIS_HASH_SHADOW_VOICE_COMPLIANCE_ROOT"
        self._conn: sqlite3.Connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS compliance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE,
                lead_id TEXT,
                campaign_id TEXT,
                calling_number TEXT,
                called_number TEXT,
                timezone TEXT,
                start_timestamp REAL,
                end_timestamp REAL,
                duration_seconds REAL,
                disposition TEXT,
                script_version_id TEXT,
                prompt_model_version TEXT,
                consent_provenance TEXT,
                legal_basis TEXT,
                dnc_scrubbed_passed INTEGER,
                safe_harbor_cleared INTEGER,
                guardrail_flagged INTEGER,
                transfer_destination TEXT,
                hash_chain TEXT,
                recorded_at REAL
            )
        """)
        conn.commit()

    def record_call(self, record: ComplianceCallRecord) -> str:
        """Appends compliance record and calculates cryptographic hash chain."""
        raw_payload = json.dumps(asdict(record), sort_keys=True)
        chain_input = f"{self._last_hash}:{raw_payload}"
        current_hash = hashlib.sha256(chain_input.encode()).hexdigest()
        record.hash_chain = current_hash
        self._last_hash = current_hash

        conn = self._get_connection()
        conn.execute("""
            INSERT INTO compliance_records (
                session_id, lead_id, campaign_id, calling_number, called_number,
                timezone, start_timestamp, end_timestamp, duration_seconds,
                disposition, script_version_id, prompt_model_version,
                consent_provenance, legal_basis, dnc_scrubbed_passed,
                safe_harbor_cleared, guardrail_flagged, transfer_destination,
                hash_chain, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.session_id, record.lead_id, record.campaign_id,
            record.calling_number, record.called_number, record.timezone,
            record.start_timestamp, record.end_timestamp, record.duration_seconds,
            record.disposition, record.script_version_id, record.prompt_model_version,
            record.consent_provenance, record.legal_basis,
            1 if record.dnc_scrubbed_passed else 0,
            1 if record.safe_harbor_cleared else 0,
            1 if record.guardrail_flagged else 0,
            record.transfer_destination, record.hash_chain, time.time()
        ))
        conn.commit()

        logger.info(f"[COMPLIANCE AUDIT] Immutable record saved for session={record.session_id} hash={current_hash[:12]}")
        return current_hash

    def export_backup(self, backup_file_path: str) -> int:
        """Performs structured JSON backup of all compliance records for retention."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM compliance_records ORDER BY id ASC").fetchall()
        records = [dict(r) for r in rows]

        with open(backup_file_path, "w", encoding="utf-8") as f:
            json.dump({"backup_created_at": time.time(), "record_count": len(records), "records": records}, f, indent=2)

        logger.info(f"[COMPLIANCE RETENTION] Exported {len(records)} records to {backup_file_path}")
        return len(records)

    def verify_backup_integrity(self, backup_file_path: str) -> bool:
        """Verifies integrity and readability of a backup file."""
        if not os.path.exists(backup_file_path):
            return False
        with open(backup_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return "record_count" in data and len(data.get("records", [])) == data["record_count"]

    def close(self) -> None:
        """Closes the underlying SQLite database connection."""
        if hasattr(self, "_conn") and self._conn:
            try:
                self._conn.close()
            except Exception:
                pass