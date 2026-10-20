"""
Outcome Feedback Loop
=====================
Fulfills Section 8.5 Gap-Fill:
- Aggregates objection branch outcomes (Conversion to Transfer vs Lost Lead)
- Captures human closer qualitative feedback
- Informs structured, version-controlled script iterations
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time

logger = logging.getLogger("shadow_voice.feedback_loop")


@dataclass
class ObjectionOutcomeStats:
    total_triggered: int = 0
    transferred_count: int = 0
    callback_count: int = 0
    lost_count: int = 0
    dnc_count: int = 0

    @property
    def conversion_rate(self) -> float:
        if self.total_triggered == 0:
            return 0.0
        return (self.transferred_count + self.callback_count) / self.total_triggered


@dataclass
class CloserFeedbackEntry:
    session_id: str
    lead_id: str
    objection_branch: Optional[str]
    closer_name: str
    feedback_notes: str
    rating_1_to_5: int
    timestamp: float = field(default_factory=time.time)


class OutcomeFeedbackLoop:
    """Tracks objection effectiveness and captures closer feedback."""

    def __init__(self) -> None:
        self.stats: Dict[str, ObjectionOutcomeStats] = {}
        self.feedback_entries: List[CloserFeedbackEntry] = []

    def record_call_outcome(
        self,
        objection_branch: Optional[str],
        final_disposition: str
    ) -> None:
        key = objection_branch or "NO_OBJECTION"
        if key not in self.stats:
            self.stats[key] = ObjectionOutcomeStats()

        stat = self.stats[key]
        stat.total_triggered += 1

        if final_disposition in ("SALE", "XFER"):
            stat.transferred_count += 1
        elif final_disposition == "CALLBK":
            stat.callback_count += 1
        elif final_disposition == "DNC":
            stat.dnc_count += 1
        else:
            stat.lost_count += 1

    def submit_closer_feedback(
        self,
        session_id: str,
        lead_id: str,
        objection_branch: Optional[str],
        closer_name: str,
        notes: str,
        rating: int
    ) -> CloserFeedbackEntry:
        clamped_rating = max(1, min(5, int(rating)))
        entry = CloserFeedbackEntry(
            session_id=session_id,
            lead_id=lead_id,
            objection_branch=objection_branch,
            closer_name=closer_name,
            feedback_notes=notes,
            rating_1_to_5=clamped_rating
        )
        self.feedback_entries.append(entry)
        logger.info(f"[FEEDBACK LOOP] Logged closer feedback for session={session_id} rating={clamped_rating}/5")
        return entry
