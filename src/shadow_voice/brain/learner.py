"""
Customer Question Learner
=========================
Linguistic turn analyzer that:
- Detects customer inquiries during live calls
- Distinguishes questions from statements or objections
- Queries the Cognitive Brain for existing approved answers
- Adds novel questions to the brain for review and approval
"""

from __future__ import annotations
import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from shadow_voice.brain.brain import BrainManager

logger = logging.getLogger("shadow_voice.learner")


class CustomerQuestionLearner:
    """Extracts, categorizes, and learns from caller inquiries during conversations."""

    # Common English interrogative cues & patterns
    QUESTION_TRIGGERS = [
        r"^(what|how|why|when|where|who)\b",
        r"^(can|could|would|will|do|does|did|is|are|have|has)\s+(you|we|your|the|it)\b",
        r"\b(tell me about|explain|how much does|how does it work|do you guys support|can you do)\b",
        r"\?$"
    ]

    # Sentiment indicators
    POSITIVE_WORDS = {"great", "good", "cool", "awesome", "interesting", "nice", "love", "sounds good", "perfect"}
    NEGATIVE_WORDS = {"expensive", "scam", "bad", "slow", "broken", "hate", "unhappy", "waste", "problem", "annoyed"}

    def __init__(self, brain_manager: Optional[BrainManager] = None) -> None:
        self.brain = brain_manager or BrainManager()
        self._compiled_triggers = [re.compile(p, re.IGNORECASE) for p in self.QUESTION_TRIGGERS]

    def is_question(self, utterance: Optional[str]) -> bool:
        """Determines if the caller utterance contains a substantive question."""
        text = (utterance or "").strip()
        if len(text) < 8:
            return False

        if "?" in text:
            return True

        for pat in self._compiled_triggers:
            if pat.search(text):
                return True

        return False

    def detect_sentiment(self, text: Optional[str]) -> str:
        """Simple, fast rule-based sentiment detection for live calls."""
        lower = (text or "").lower()
        pos_hits = sum(1 for w in self.POSITIVE_WORDS if w in lower)
        neg_hits = sum(1 for w in self.NEGATIVE_WORDS if w in lower)

        if pos_hits > neg_hits:
            return "positive"
        elif neg_hits > pos_hits:
            return "negative"
        return "neutral"

    def categorize_question(self, text: Optional[str]) -> str:
        """Categorizes questions by business domain."""
        lower = (text or "").lower()
        if any(w in lower for w in ["price", "cost", "quote", "rate", "fee", "dollar", "$", "expensive"]):
            return "pricing"
        elif any(w in lower for w in ["dialer", "vicidial", "asterisk", "sip", "api", "telephony", "latency", "setup"]):
            return "technical"
        elif any(w in lower for w in ["tcpa", "dnc", "compliance", "legal", "safe harbor", "fcc"]):
            return "compliance"
        elif any(w in lower for w in ["support", "training", "guarantee", "sla"]):
            return "service"
        return "general"

    def process_turn(self, utterance: Optional[str], session_id: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Processes a user turn:
        Returns:
            (is_question, existing_approved_answer_or_none, recorded_question_info_or_none)
        """
        clean_utterance = (utterance or "").strip()
        if not self.is_question(clean_utterance):
            return False, None, None

        # Check if the Brain already knows the approved answer
        existing_answer = self.brain.find_matching_approved_answer(clean_utterance)

        # Record or increment in the brain
        sentiment = self.detect_sentiment(clean_utterance)
        category = self.categorize_question(clean_utterance)

        draft_proposal = f"We provide direct support and dedicated solutions for {clean_utterance.rstrip('?')}. Let me share the specifics."
        recorded = self.brain.add_or_increment_question(
            question_text=clean_utterance,
            session_id=session_id,
            sentiment=sentiment,
            category=category,
            proposed_answer=draft_proposal
        )

        return True, existing_answer, recorded
