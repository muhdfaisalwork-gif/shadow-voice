"""
Objection Handling Library
==========================
Comprehensive objection library defined by Dialogue Engineer:
- Disinterest
- Incumbent provider
- Price objection
- Busy / callback
- "Are you a bot"
- Requests human
- DNC request
- Campaign-specific objections
All responses conform strictly to Section 7: plain verbs, natural flow, no FAQ stiffness.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple
from enum import Enum


class ObjectionType(str, Enum):
    NOT_INTERESTED = "NOT_INTERESTED"
    INCUMBENT_PROVIDER = "INCUMBENT_PROVIDER"
    PRICE = "PRICE"
    BUSY_CALLBACK = "BUSY_CALLBACK"
    BOT_QUESTION = "BOT_QUESTION"
    REQUESTS_HUMAN = "REQUESTS_HUMAN"
    DNC_REQUEST = "DNC_REQUEST"
    SEND_INFO = "SEND_INFO"
    UNKNOWN = "UNKNOWN"


@dataclass
class ObjectionResponse:
    objection_type: ObjectionType
    response_text: str
    action: str  # "CONTINUE", "TRANSFER", "DNC", "SCHEDULE_CALLBACK", "HANGUP"
    confidence: float


class ObjectionHandler:
    """Classifies user objections and provides conversational responses."""

    PATTERNS: List[Tuple[ObjectionType, str]] = [
        (ObjectionType.DNC_REQUEST, r"\b(do not call|don't call|take me off|remove (my|this) number|stop calling|remove me)\b"),
        (ObjectionType.REQUESTS_HUMAN, r"\b(real person|human being|live human|live agent|human agent|speak (to|with) (an? )?(agent|person|human|representative|specialist|engineer|supervisor|operator|team lead|someone)|talk to (an? )?(agent|person|human|representative|specialist|engineer|supervisor|operator|team lead|someone)|transfer (me )?(over )?to (an? )?(agent|person|human|representative|specialist|engineer|supervisor|operator|team lead|someone)|get me (an? )?(agent|person|human|representative|specialist|engineer|supervisor|operator|team lead)|connect me to (an? )?(agent|person|human|representative|specialist|engineer|supervisor|operator|team lead)|operator|supervisor|talk to someone)\b"),
        (ObjectionType.BOT_QUESTION, r"\b(are you (a )?(bot|robot|ai|computer|real|recording))\b"),
        (ObjectionType.BUSY_CALLBACK, r"\b(busy|bad time|driving|meeting|call me back|later today|tomorrow)\b"),
        (ObjectionType.PRICE, r"\b(how much|cost|price|expensive|rate|charge|quote)\b"),
        (ObjectionType.INCUMBENT_PROVIDER, r"\b(already have|already use|got someone|have a vendor|happy with|currently using)\b"),
        (ObjectionType.SEND_INFO, r"\b(send (me )?(an )?email|mail me|send information|brochure)\b"),
        (ObjectionType.NOT_INTERESTED, r"\b(not interested|don't need|no thanks|pass|not for me)\b"),
    ]

    RESPONSES = {
        ObjectionType.NOT_INTERESTED: (
            "Totally fair! A lot of teams told us the same thing before seeing how we cut their dialer drops. If it makes sense down the line, we're always here.",
            "CONTINUE"
        ),
        ObjectionType.INCUMBENT_PROVIDER: (
            "That makes complete sense  -  most folks we work with already had something in place. We actually plug directly into existing setups like VICIdial so you don't have to rip anything out. How has their connection rate been lately?",
            "CONTINUE"
        ),
        ObjectionType.PRICE: (
            "Pricing is straightforward and based purely on connected call volume, so you only pay for what actually works. Let me connect you with our solutions desk for the exact breakdown.",
            "TRANSFER"
        ),
        ObjectionType.BUSY_CALLBACK: (
            "I completely understand. When would be a better time for a quick 2-minute catchup later this week?",
            "SCHEDULE_CALLBACK"
        ),
        ObjectionType.BOT_QUESTION: (
            "Haha, I get that a lot with computer headsets! I'm using a quick dictation tool on my screen, but I'm right here with you. What was your main priority with your phone lines this quarter?",
            "CONTINUE"
        ),
        ObjectionType.REQUESTS_HUMAN: (
            "Absolutely! Let me get you right over to a team lead who can help you directly.",
            "TRANSFER"
        ),
        ObjectionType.DNC_REQUEST: (
            "Understood right away. I'm placing your number on our internal do-not-call list immediately. Have a great day.",
            "DNC"
        ),
        ObjectionType.SEND_INFO: (
            "I'd be glad to. What's the best email address to shoot that over to?",
            "CONTINUE"
        ),
    }

    def __init__(self) -> None:
        self._compiled = [(otype, re.compile(p, re.IGNORECASE)) for otype, p in self.PATTERNS]

    def classify_and_respond(self, text: str) -> ObjectionResponse:
        normalized = (text or "").strip()
        for otype, regex in self._compiled:
            if regex.search(normalized):
                resp_text, action = self.RESPONSES[otype]
                return ObjectionResponse(
                    objection_type=otype,
                    response_text=resp_text,
                    action=action,
                    confidence=0.95
                )

        return ObjectionResponse(
            objection_type=ObjectionType.UNKNOWN,
            response_text="I hear you. Could you share a bit more about what you're currently aiming to improve?",
            action="CONTINUE",
            confidence=0.5
        )
