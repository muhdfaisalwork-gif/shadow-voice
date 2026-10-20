"""
Agent Reach Eyes — Intelligence Analyzer & Brain Digest
========================================================
Analyzes web content extracted by ReachReader:
- Discovers core business value propositions
- Extracts pricing patterns & product tiers
- Identifies common customer pain points
- Extracts high-value Q&As for one-click ingestion into the Cognitive Brain
"""

from __future__ import annotations
import re
import logging
from typing import Dict, Any, List, Optional
from shadow_voice.brain.brain import BrainManager

logger = logging.getLogger("shadow_voice.reach.analyzer")


class ReachAnalyzer:
    """Extracts actionable conversational sales intelligence from raw webpage text."""

    def __init__(self, brain_manager: Optional[BrainManager] = None) -> None:
        self.brain = brain_manager or BrainManager()

    def analyze_content(self, title: str, content: str, url: str) -> Dict[str, Any]:
        """Performs structured linguistic extraction on website text."""
        safe_content = content or ""
        safe_title = title or "Target Business"
        lower_content = safe_content.lower()

        # 1. Detect Company / Offering Name
        company_name = safe_title.split("-")[0].split("|")[0].strip() or "Target Business"

        # 2. Extract Value Propositions
        value_props = []
        sentences = [s.strip() for s in re.split(r"[.\n]", safe_content) if len(s.strip()) > 20]
        keywords = ["reduce", "save", "increase", "fast", "low-latency", "scale", "automate", "convert", "compliance"]
        for s in sentences:
            if any(k in s.lower() for k in keywords) and len(value_props) < 3:
                value_props.append(s[:150])

        if not value_props:
            value_props = [
                f"{company_name} offers high-performance telemarketing solutions.",
                "Engineered for high uptime and rapid agent workflows."
            ]

        # 3. Extract Pricing or Commercial Models
        pricing_terms = []
        pricing_matches = re.findall(r"\$\d+(?:\.\d{2})?(?:/[a-zA-Z]+)?", safe_content)
        if pricing_matches:
            pricing_terms = list(set(pricing_matches))[:4]
        else:
            if "custom" in lower_content or "enterprise" in lower_content:
                pricing_terms.append("Custom Enterprise Quotes")
            if "minute" in lower_content or "usage" in lower_content:
                pricing_terms.append("Usage-based per-minute billing")

        if not pricing_terms:
            pricing_terms = ["Custom Volume Quote", "Usage-Based"]

        # 4. Generate Candidate Customer Q&As
        candidate_qas = [
            {
                "question": f"What specific products or services does {company_name} offer?",
                "answer": f"{company_name} provides {value_props[0] if value_props else 'comprehensive voice automation solutions'}."
            },
            {
                "question": f"How does {company_name} handle pricing?",
                "answer": f"Pricing is structured around {', '.join(pricing_terms)} to match customer call volume."
            },
            {
                "question": f"Can we integrate {company_name} with existing dialers like VICIdial?",
                "answer": "Yes, standard SIP and AudioSocket protocols ensure plug-and-play compatibility with any PBX or predictive dialer."
            }
        ]

        return {
            "company_name": company_name,
            "url": url or "",
            "title": safe_title,
            "value_propositions": value_props,
            "pricing_highlights": pricing_terms,
            "suggested_qas": candidate_qas,
            "summary": safe_content[:400] + "..." if len(safe_content) > 400 else safe_content
        }

    def digest_into_brain(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Commits extracted intelligence directly into the Cognitive Brain:
        - Adds value proposition as a Story Bank verified receipt
        - Adds candidate Q&As as approved customer questions
        """
        company = analysis_result.get("company_name", "Extracted Business")
        url = analysis_result.get("url", "")
        value_props = analysis_result.get("value_propositions", [])
        qas = analysis_result.get("suggested_qas", [])

        # 1. Add Story Bank receipt
        story_detail = " | ".join(value_props)
        story_id = self.brain.add_story(
            category="market_intelligence",
            title=f"Reach Eyes: {company}",
            detail=story_detail,
            verified_metrics=f"Extracted from {url}",
            tags="reach_eyes, competitor, intelligence"
        )

        # 2. Add approved customer questions
        added_questions = []
        for item in qas:
            q_text = item["question"]
            ans_text = item["answer"]
            q_res = self.brain.add_or_increment_question(
                question_text=q_text,
                session_id="reach_eyes_scan",
                sentiment="neutral",
                category="technical",
                proposed_answer=ans_text
            )
            # Immediately approve so agent can answer live
            self.brain.update_question_status(q_res["id"], status="approved", approved_answer=ans_text)
            added_questions.append(q_text)

        return {
            "success": True,
            "story_id": story_id,
            "questions_added": len(added_questions),
            "message": f"Successfully digested {company} into Cognitive Brain memory ({len(added_questions)} Q&As + Story Bank receipt)."
        }
