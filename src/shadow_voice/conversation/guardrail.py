"""
Runtime Output Guardrail
========================
Fulfills Principle 11 & Conversational AI Deliverable:
- Real-time classification/filter pass between LLM output and TTS input
- Evaluates text against approved script space before ANY audio is synthesized or spoken
- Blocks unapproved pricing, promises, guarantees, commitments, or legal claims
- On violation: replaces turn with safe fallback line and routes call to human transfer
"""

from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, Set

logger = logging.getLogger("shadow_voice.guardrail")

DEFAULT_SAFE_FALLBACK_TEXT = "Let me get you the exact details directly from one of our specialists so you have the right information."


@dataclass
class GuardrailResult:
    passed: bool
    final_text: str
    flag_reason: Optional[str] = None
    violation_category: Optional[str] = None
    matched_pattern: Optional[str] = None
    should_route_to_human: bool = False


class RuntimeOutputGuardrail:
    """
    Runtime filter ensuring zero unauthorized claims or pricing slip through to the TTS engine.
    """

    # Prohibited patterns: Unapproved guarantees, pricing, verbal contracts, legal assertions
    PROHIBITED_PATTERNS = [
        # Unapproved Guarantees & Absolute Promises
        (r"\b(100%|guarantee|guaranteed|promise|we promise|swear|zero risk|no risk)\b", "UNAPPROVED_GUARANTEE"),
        # Unauthorized Pricing / Dollar amounts / Discounts
        (r"(\$\s*\d+(?:\.\d{1,2})?|\b\d+\s*dollars|\bpercent off|\bdiscount of|\bfree for life\b)", "UNAPPROVED_PRICING"),
        # Legal and Contractual Claims
        (r"\b(verbal agreement|binding contract|waive your rights|court approved|legal requirement to buy)\b", "LEGAL_CLAIM"),
        # Unauthorized Regulatory Claims
        (r"\b(fcc certified us|tcpa exempt|government authorized deal)\b", "REGULATORY_MISREPRESENTATION"),
        # Vulgar or unprofessional phrases
        (r"\b(scam|shut up|idiot|stupid)\b", "UNPROFESSIONAL_LANGUAGE"),
    ]

    def __init__(
        self,
        approved_pricing_whitelist: Optional[Set[str]] = None,
        safe_fallback_text: str = DEFAULT_SAFE_FALLBACK_TEXT
    ) -> None:
        self.approved_pricing_whitelist = {
            str(s).strip().lower()
            for s in (approved_pricing_whitelist or set())
            if s and str(s).strip()
        }
        self.safe_fallback_text = safe_fallback_text
        self._compiled_rules = [
            (re.compile(pattern, re.IGNORECASE), category)
            for pattern, category in self.PROHIBITED_PATTERNS
        ]

    def add_prohibited_pattern(self, pattern: str, category: str = "CUSTOM_RULE", is_regex: bool = False) -> None:
        """Adds a custom prohibited pattern, safely escaping plain text patterns."""
        if not pattern or not str(pattern).strip():
            return
        pat = str(pattern).strip() if is_regex else rf"\b{re.escape(str(pattern).strip())}\b"
        self._compiled_rules.append((re.compile(pat, re.IGNORECASE), category))

    def inspect_text(self, text: str) -> GuardrailResult:
        """
        Evaluates LLM text before TTS processing.
        Returns GuardrailResult. If failed, text is substituted with fallback line and
        should_route_to_human is set to True.
        """
        normalized = (text or "").strip()

        for regex, category in self._compiled_rules:
            match = regex.search(normalized)
            if match:
                matched_str = match.group(0).lower()
                # Check if it was explicitly whitelisted (e.g. approved pricing)
                is_whitelisted = bool(
                    matched_str in self.approved_pricing_whitelist
                    or any(
                        bool(w and (matched_str in w or w in matched_str))
                        for w in self.approved_pricing_whitelist
                    )
                )
                if is_whitelisted:
                    continue

                logger.warning(
                    f"[RUNTIME GUARDRAIL TRIPPED] Category={category} Matched='{matched_str}' in text: '{text}'"
                )
                return GuardrailResult(
                    passed=False,
                    final_text=self.safe_fallback_text,
                    flag_reason=f"Detected prohibited phrase '{matched_str}' in category {category}",
                    violation_category=category,
                    matched_pattern=matched_str,
                    should_route_to_human=True
                )

        return GuardrailResult(
            passed=True,
            final_text=normalized,
            should_route_to_human=False
        )
