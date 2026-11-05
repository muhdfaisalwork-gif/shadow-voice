"""
SSML-Lite Inline Prosody & Pacing Parser
=======================================
Lightweight, linear ReDoS-safe inline markup parser for sales pacing control.

Adapted from VoiceStudio SSML-Lite architecture.

Supported tags:
- [slow]...[/slow]       -> Pacing speed multiplier ~0.85 (e.g. for pricing & compliance disclosures)
- [fast]...[/fast]       -> Pacing speed multiplier ~1.15
- [emphasis]...[/emphasis] -> Subtle slow-down ~0.92 with emphasis flag
- [pause <ms>]           -> Synthetic silence insertion (e.g. [pause 250ms], [pause 300 ms])
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

SLOW_SPEED: float = 0.85
FAST_SPEED: float = 1.15
EMPHASIS_SPEED: float = 0.92

_TAGS: Dict[str, Dict[str, Any]] = {
    "slow": {"speed": SLOW_SPEED, "emphasis": False},
    "fast": {"speed": FAST_SPEED, "emphasis": False},
    "emphasis": {"speed": EMPHASIS_SPEED, "emphasis": True},
}

_TAG_RE = re.compile(
    r"\[(/?)((?:slow|fast|emphasis)|pause(?:\s*(\d+)(?:\s*ms)?)?)\]",
    re.IGNORECASE
)


@dataclass
class SSMLSegment:
    """Represents an ordered segment of speech with prosody instructions."""
    text: str
    speed: Optional[float] = None
    emphasis: bool = False
    pause_ms: int = 0

    @property
    def rate(self) -> Optional[float]:
        return self.speed

    @property
    def volume(self) -> float:
        return 1.2 if self.emphasis else 1.0


def parse_ssml_lite(text: Optional[str]) -> List[SSMLSegment]:
    """
    Parses inline prosody tags into an ordered list of SSMLSegment objects.
    ReDoS-safe: linear scan with fixed token alternations.
    """
    if not text:
        return []

    if "[" not in text:
        return [SSMLSegment(text=text.strip(), speed=None, emphasis=False, pause_ms=0)]

    segments: List[SSMLSegment] = []
    stack: List[str] = []
    last_idx = 0

    for match in _TAG_RE.finditer(text):
        start, end = match.span()
        # Text preceding tag
        if start > last_idx:
            chunk = text[last_idx:start].strip()
            if chunk:
                # Resolve current stack
                cur_speed = None
                cur_emp = False
                for tag_name in stack:
                    cur_speed = _TAGS[tag_name]["speed"]
                    if _TAGS[tag_name]["emphasis"]:
                        cur_emp = True
                segments.append(SSMLSegment(text=chunk, speed=cur_speed, emphasis=cur_emp, pause_ms=0))

        is_close = bool(match.group(1))
        tag_content = match.group(2).lower()

        if tag_content.startswith("pause"):
            raw_ms = int(match.group(3) or 200)
            # Bound pause duration between 10ms and 5000ms (prevent dead-air abandonment)
            pause_val = max(10, min(5000, raw_ms))
            segments.append(SSMLSegment(text="", speed=None, emphasis=False, pause_ms=pause_val))
        elif is_close:
            clean_tag = tag_content.strip()
            if clean_tag in stack:
                stack.remove(clean_tag)
        else:
            clean_tag = tag_content.strip()
            if clean_tag in _TAGS:
                stack.append(clean_tag)

        last_idx = end

    if last_idx < len(text):
        chunk = text[last_idx:].strip()
        if chunk:
            cur_speed = None
            cur_emp = False
            for tag_name in stack:
                cur_speed = _TAGS[tag_name]["speed"]
                if _TAGS[tag_name]["emphasis"]:
                    cur_emp = True
            segments.append(SSMLSegment(text=chunk, speed=cur_speed, emphasis=cur_emp, pause_ms=0))

    return segments


def strip_ssml_tags(text: Optional[str]) -> str:
    """Strips all inline SSML tags, returning clean plain text."""
    if not text:
        return ""
    return re.sub(r"\[/?(?:slow|fast|emphasis|pause(?:\s*\d+(?:\s*ms)?)?)\]", "", text, flags=re.IGNORECASE).strip()


strip_ssml_lite = strip_ssml_tags


class VoiceStudioSSMLParser:
    """Parser wrapper for SSML-Lite prosody markup."""

    @staticmethod
    def parse(text: Optional[str]) -> List[SSMLSegment]:
        return parse_ssml_lite(text)

    @staticmethod
    def strip(text: Optional[str]) -> str:
        return strip_ssml_tags(text)
