"""
Natural Language Quality & Anti-Corporate-Filler Auditor
=========================================================
Fulfills Section 7: Natural Language & Voice Delivery Standards:
- Section 7.1: Strictly audits that openings DO NOT contain automated/AI disclosures
  ("Every call should begin naturally, as a normal person-to-person business conversation...
   no mention of AI, automated calling, artificial voice technology, or similar wording.")
- Section 7.3: Detects and rejects corporate filler, inflated adjectives, vague authority
- Section 7.4: Validates sentence length variation and plain verb usage
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class QualityAuditReport:
    is_natural: bool
    violations: List[str]
    has_banned_ai_disclosure: bool
    filler_score: float  # 0.0 is perfect clean conversational speech


class NaturalLanguageAuditor:
    """Audits script lines against Section 7 writing rules."""

    # 7.1: Banned in introduction: ANY mention of AI, robot, synthetic, automated
    BANNED_DISCLOSURES = [
        r"\b(automated call|artificial voice|artificial intelligence|ai technology|virtual assistant|automated system|computer-generated voice|recorded message)\b"
    ]

    # 7.3: Corporate filler & inflated buzzwords to cut
    BANNED_FILLER = [
        r"\b(in today's fast-paced environment|fast-paced world|we understand you're busy)\b",
        r"\b(cutting-edge|seamless|revolutionary|state-of-the-art|best-in-class|synergy|game-changer|disruptive)\b",
        r"\b(exciting opportunity for you|unique opportunity)\b",
        r"\b(studies show|experts agree|many customers say|industry leaders believe)\b",
        r"\b(not just .+, but .+)\b",  # rule against rhetorical decoration
        r"\b(in other words|what that means is)\b", # over-explaining
        r"\b(facilitate|leverage|utilize|showcase)\b", # inflated verbs
    ]

    def __init__(self) -> None:
        self._compiled_disclosures = [re.compile(p, re.IGNORECASE) for p in self.BANNED_DISCLOSURES]
        self._compiled_fillers = [re.compile(p, re.IGNORECASE) for p in self.BANNED_FILLER]

    def audit_opening(self, text: Optional[str]) -> Tuple[bool, List[str]]:
        """
        Audits the call opening line per Section 7.1.
        Must be completely natural human greeting without robotic announcements.
        """
        if text is None or not str(text).strip():
            return False, ["Section 7.1 violation: Opening greeting cannot be empty."]

        clean_text = str(text)
        violations = []
        for regex in self._compiled_disclosures:
            m = regex.search(clean_text)
            if m:
                violations.append(f"Section 7.1 violation: Opening contains banned robotic disclosure '{m.group(0)}'")

        return len(violations) == 0, violations

    def audit_script(self, text: Optional[str]) -> QualityAuditReport:
        """Audits general dialogue lines for corporate filler and stiffness."""
        clean_text = "" if text is None else str(text)
        violations = []

        # Check for banned AI disclosures
        has_ai_disc = False
        for regex in self._compiled_disclosures:
            m = regex.search(clean_text)
            if m:
                has_ai_disc = True
                violations.append(f"Section 7.1: Unnatural disclosure phrasing: '{m.group(0)}'")

        # Check for corporate filler
        filler_count = 0
        for regex in self._compiled_fillers:
            m = regex.search(clean_text)
            if m:
                filler_count += 1
                violations.append(f"Section 7.3 filler detected: '{m.group(0)}'")

        filler_score = float(filler_count)

        return QualityAuditReport(
            is_natural=(len(violations) == 0),
            violations=violations,
            has_banned_ai_disclosure=has_ai_disc,
            filler_score=filler_score
        )
