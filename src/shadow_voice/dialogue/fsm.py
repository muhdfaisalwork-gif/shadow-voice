"""
Six-Stage Sales Conversation FSM
=================================
Fulfills Phase 3 Dialogue Deliverable:
Connection -> Qualification -> Discovery/Hook -> Objection Handling -> Offer/Next Step -> Transfer/Disposition

Section 7.1 Enforced:
Call begins naturally without robotic AI / automated-voice disclosure announcements.
Lead history context dynamically adapts opening.
"""

from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from shadow_voice.dialogue.objections import ObjectionHandler, ObjectionType, ObjectionResponse
from shadow_voice.cti.lead_history import LeadHistoryRecord
from shadow_voice.brain.brain import BrainManager
from shadow_voice.brain.learner import CustomerQuestionLearner

logger = logging.getLogger("shadow_voice.fsm")


class Stage(str, Enum):
    CONNECTION = "CONNECTION"
    QUALIFICATION = "QUALIFICATION"
    DISCOVERY_HOOK = "DISCOVERY_HOOK"
    OBJECTION_HANDLING = "OBJECTION_HANDLING"
    OFFER_NEXT_STEP = "OFFER_NEXT_STEP"
    TRANSFER_DISPOSITION = "TRANSFER_DISPOSITION"
    COMPLETED = "COMPLETED"


@dataclass
class FSMTurnResult:
    current_stage: Stage
    next_stage: Stage
    agent_text: str
    action: str  # "CONTINUE", "TRANSFER_WARM", "TRANSFER_BLIND", "DNC", "SCHEDULE_CALLBACK", "HANGUP"
    disposition_code: Optional[str] = None
    transfer_notes: str = ""
    objection_handled: Optional[str] = None


class SalesConversationFSM:
    """
    Finite State Machine driving the six-stage sales / CSR conversation.
    Integrates with Cognitive Brain and Customer Question Learner.
    """

    def __init__(
        self,
        lead_history: Optional[LeadHistoryRecord] = None,
        agent_name: str = "Alex",
        company_name: str = "Shadow Voice",
        campaign_name: str = "Dialer Optimization",
        brain_manager: Optional[BrainManager] = None,
        learner: Optional[CustomerQuestionLearner] = None
    ) -> None:
        self.lead_history = lead_history or LeadHistoryRecord(lead_id="UNKNOWN", first_contact=True)
        self.agent_name = agent_name
        self.company_name = company_name
        self.campaign_name = campaign_name
        self.brain = brain_manager
        self.learner = learner

        self.current_stage: Stage = Stage.CONNECTION
        self.objection_handler = ObjectionHandler()
        self.turn_count: int = 0
        self.last_objection: Optional[str] = None

    def get_initial_greeting(self) -> str:
        """
        Section 7.1 Non-Negotiable:
        Natural person-to-person business conversation opening without robotic AI disclosure.
        Adapts dynamically if lead has prior history or custom brain instructions.
        """
        agent_n = self.agent_name or "Jordan"
        company_n = self.company_name or "Shadow Voice"

        if not self.lead_history.first_contact and self.lead_history.has_pending_callback:
            return f"Hi, this is {agent_n} from {company_n}  -  following up on our scheduled callback. Do you have a quick minute?"
        elif not self.lead_history.first_contact and self.lead_history.last_disposition == "CALLBK":
            return f"Hi! It's {agent_n} calling back from {company_n} like we discussed. How has your day been?"
        else:
            # Check if brain has a custom configured opening greeting
            if self.brain:
                try:
                    inst = self.brain.get_instructions()
                    if inst.get("opening_greeting"):
                        greeting = inst["opening_greeting"]
                        greeting = greeting.replace("[Name]", agent_n).replace("{agent_name}", agent_n)
                        greeting = greeting.replace("[Company]", company_n).replace("{company_name}", company_n)
                        return greeting
                except Exception:
                    pass
            # Clean, natural person-to-person opening
            return f"Hi, this is {agent_n} calling from {company_n}  -  do you have a quick minute?"

    def process_turn(self, user_transcript: str) -> FSMTurnResult:
        """
        Advances the FSM based on user utterance and current stage.
        """
        self.turn_count += 1
        text = (user_transcript or "").strip()

        # Always check for priority objections (DNC, Human Transfer, Bot inquiry) regardless of stage
        obj_resp = self.objection_handler.classify_and_respond(text)
        if obj_resp.objection_type in (ObjectionType.DNC_REQUEST, ObjectionType.REQUESTS_HUMAN):
            self.last_objection = obj_resp.objection_type.value
            if obj_resp.objection_type == ObjectionType.DNC_REQUEST:
                self.current_stage = Stage.TRANSFER_DISPOSITION
                return FSMTurnResult(
                    current_stage=Stage.OBJECTION_HANDLING,
                    next_stage=Stage.TRANSFER_DISPOSITION,
                    agent_text=obj_resp.response_text,
                    action="DNC",
                    disposition_code="DNC",
                    objection_handled=self.last_objection
                )
            elif obj_resp.objection_type == ObjectionType.REQUESTS_HUMAN:
                self.current_stage = Stage.TRANSFER_DISPOSITION
                return FSMTurnResult(
                    current_stage=Stage.OBJECTION_HANDLING,
                    next_stage=Stage.TRANSFER_DISPOSITION,
                    agent_text=obj_resp.response_text,
                    action="TRANSFER_WARM",
                    disposition_code="XFER",
                    transfer_notes="Customer requested live human representative",
                    objection_handled=self.last_objection
                )

        # Check for customer inquiry using the Cognitive Brain learner
        if self.learner:
            is_q, approved_ans, recorded = self.learner.process_turn(text, session_id=self.lead_history.lead_id)
            if is_q and approved_ans:
                return FSMTurnResult(
                    current_stage=self.current_stage,
                    next_stage=self.current_stage,
                    agent_text=f"Understood. {approved_ans}",
                    action="CONTINUE"
                )

        # STAGE TRANSITIONS
        if self.current_stage == Stage.CONNECTION:
            # Caller responded to opening greeting
            if obj_resp.objection_type == ObjectionType.NOT_INTERESTED:
                self.current_stage = Stage.OBJECTION_HANDLING
                self.last_objection = "NOT_INTERESTED"
                return FSMTurnResult(
                    current_stage=Stage.CONNECTION,
                    next_stage=Stage.OBJECTION_HANDLING,
                    agent_text=obj_resp.response_text,
                    action="CONTINUE",
                    objection_handled=self.last_objection
                )

            # Move to Qualification
            self.current_stage = Stage.QUALIFICATION
            return FSMTurnResult(
                current_stage=Stage.CONNECTION,
                next_stage=Stage.QUALIFICATION,
                agent_text=f"Great! The reason for my call is we're helping outbound teams cut dropped calls and boost connection rates. Are you guys currently running VICIdial or another dialer platform?",
                action="CONTINUE"
            )

        elif self.current_stage == Stage.QUALIFICATION:
            if obj_resp.objection_type != ObjectionType.UNKNOWN and obj_resp.action != "CONTINUE":
                return self._handle_objection_action(obj_resp)

            # Move to Discovery / Hook
            self.current_stage = Stage.DISCOVERY_HOOK
            return FSMTurnResult(
                current_stage=Stage.QUALIFICATION,
                next_stage=Stage.DISCOVERY_HOOK,
                agent_text=f"Got it. What we do is sit right at your telephony boundary to give your lines ultra-fast voice responses under 650 milliseconds, so callers never hear awkward dead air. How has your current response latency been holding up?",
                action="CONTINUE"
            )

        elif self.current_stage == Stage.DISCOVERY_HOOK:
            if obj_resp.objection_type in (ObjectionType.PRICE, ObjectionType.INCUMBENT_PROVIDER, ObjectionType.NOT_INTERESTED):
                self.current_stage = Stage.OBJECTION_HANDLING
                self.last_objection = obj_resp.objection_type.value
                return FSMTurnResult(
                    current_stage=Stage.DISCOVERY_HOOK,
                    next_stage=Stage.OBJECTION_HANDLING,
                    agent_text=obj_resp.response_text,
                    action=obj_resp.action,
                    objection_handled=self.last_objection
                )

            # Advance to Offer / Next Step
            self.current_stage = Stage.OFFER_NEXT_STEP
            return FSMTurnResult(
                current_stage=Stage.DISCOVERY_HOOK,
                next_stage=Stage.OFFER_NEXT_STEP,
                agent_text="We'd love to run a 5-minute side-by-side test on a single test line so you can hear the latency difference yourself. Would you be open to checking that out with our engineering desk tomorrow?",
                action="CONTINUE"
            )

        elif self.current_stage == Stage.OBJECTION_HANDLING:
            # Overcome objection and pivot to Offer
            self.current_stage = Stage.OFFER_NEXT_STEP
            return FSMTurnResult(
                current_stage=Stage.OBJECTION_HANDLING,
                next_stage=Stage.OFFER_NEXT_STEP,
                agent_text="I completely get where you're coming from. How about I connect you with our technical lead for 30 seconds right now just to see if it's even a fit?",
                action="CONTINUE"
            )

        elif self.current_stage == Stage.OFFER_NEXT_STEP:
            # Check acceptance vs rejection
            lower = text.lower().strip()

            # Positive idioms that contain the word 'no'
            positive_no_idioms = ["no problem", "no worries", "no doubt", "no issue"]
            cleaned_lower = lower
            for idiom in positive_no_idioms:
                cleaned_lower = cleaned_lower.replace(idiom, "agreeable_phrase")

            neg_pattern = re.compile(
                r"\b(not sure|unsure|not ok|no thanks|don't|dont|nah|never|can't|cant|no)\b",
                re.IGNORECASE
            )
            pos_pattern = re.compile(
                r"\b(sure|yes|yeah|yep|ok|okay|go ahead|connect me|sounds good|absolutely|definitely|interested|let's do it|lets do it)\b",
                re.IGNORECASE
            )

            is_negative = bool(neg_pattern.search(cleaned_lower))
            is_positive = bool(pos_pattern.search(cleaned_lower)) or any(idiom in lower for idiom in positive_no_idioms)

            if is_positive and not (is_negative and not any(idiom in lower for idiom in positive_no_idioms)):
                self.current_stage = Stage.TRANSFER_DISPOSITION
                return FSMTurnResult(
                    current_stage=Stage.OFFER_NEXT_STEP,
                    next_stage=Stage.TRANSFER_DISPOSITION,
                    agent_text="Fantastic! Connecting you to our team lead right now  -  hang tight for just two seconds.",
                    action="TRANSFER_WARM",
                    disposition_code="SALE",
                    transfer_notes="Qualified prospect accepted engineer live demo"
                )
            elif obj_resp.objection_type == ObjectionType.BUSY_CALLBACK:
                self.current_stage = Stage.TRANSFER_DISPOSITION
                return FSMTurnResult(
                    current_stage=Stage.OFFER_NEXT_STEP,
                    next_stage=Stage.TRANSFER_DISPOSITION,
                    agent_text=obj_resp.response_text,
                    action="SCHEDULE_CALLBACK",
                    disposition_code="CALLBK"
                )
            else:
                self.current_stage = Stage.TRANSFER_DISPOSITION
                return FSMTurnResult(
                    current_stage=Stage.OFFER_NEXT_STEP,
                    next_stage=Stage.TRANSFER_DISPOSITION,
                    agent_text="No problem at all! Thanks for your time today, and have a wonderful afternoon.",
                    action="HANGUP",
                    disposition_code="NI"
                )

        else:
            # Terminal
            return FSMTurnResult(
                current_stage=Stage.COMPLETED,
                next_stage=Stage.COMPLETED,
                agent_text="Thank you, goodbye.",
                action="HANGUP",
                disposition_code="DROP"
            )

    def _handle_objection_action(self, obj_resp: ObjectionResponse) -> FSMTurnResult:
        self.last_objection = obj_resp.objection_type.value
        self.current_stage = Stage.OBJECTION_HANDLING
        return FSMTurnResult(
            current_stage=Stage.OBJECTION_HANDLING,
            next_stage=Stage.TRANSFER_DISPOSITION if obj_resp.action in ("TRANSFER", "DNC", "HANGUP") else Stage.OFFER_NEXT_STEP,
            agent_text=obj_resp.response_text,
            action=obj_resp.action,
            disposition_code="XFER" if obj_resp.action == "TRANSFER" else ("DNC" if obj_resp.action == "DNC" else "CALLBK"),
            objection_handled=self.last_objection
        )
