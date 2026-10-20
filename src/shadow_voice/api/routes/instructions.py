"""
Instruction Studio & Persona API Router
========================================
Handles:
- Reading & updating campaign instructions
- Live Section 7.1 Natural Quality & Humanizer validation
- Prompt simulation sandbox for instant response testing
"""

from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from shadow_voice.brain.brain import BrainManager
from shadow_voice.dialogue.natural_rules import NaturalLanguageAuditor
from shadow_voice.dialogue.fsm import SalesConversationFSM

logger = logging.getLogger("shadow_voice.api.instructions")
router = APIRouter(prefix="/api/instructions", tags=["Instruction Studio"])

brain_manager = BrainManager()
auditor = NaturalLanguageAuditor()


class InstructionsPayload(BaseModel):
    campaign_id: str = "DEFAULT_SALES_V1"
    agent_name: str
    company_name: str
    industry: str = "Telephony Automation"
    opening_greeting: str
    primary_instructions: str
    tone: str
    approved_pricing: List[str] = Field(default_factory=lambda: ["usage-based", "custom quote"])
    qualification_criteria: List[str] = Field(default_factory=lambda: ["Decision maker", "Call volume > 5,000 mins/mo"])
    forbidden_phrases: List[str] = Field(default_factory=lambda: ["I am an AI", "automated calling", "virtual assistant"])
    transfer_ext: str = "8300"


class AuditRequest(BaseModel):
    text: str


class SimulationRequest(BaseModel):
    user_message: str
    campaign_id: str = "DEFAULT_SALES_V1"


@router.get("/")
def get_instructions(campaign_id: str = "DEFAULT_SALES_V1") -> Dict[str, Any]:
    """Retrieves current instructions and persona settings."""
    inst = brain_manager.get_instructions(campaign_id)
    # Check current opening against Section 7.1 auditor
    is_valid, violations = auditor.audit_opening(inst.get("opening_greeting", ""))
    inst["section_7_1_compliant"] = is_valid
    inst["violations"] = violations
    return inst


@router.post("/")
def save_instructions(payload: InstructionsPayload) -> Dict[str, Any]:
    """Saves updated instructions and persona settings after running Section 7.1 audit."""
    is_valid, violations = auditor.audit_opening(payload.opening_greeting)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Section 7.1 Violation: The opening greeting must NOT contain robotic or AI disclosures. Violations: {violations}"
        )

    saved = brain_manager.save_instructions(
        campaign_id=payload.campaign_id,
        agent_name=payload.agent_name,
        company_name=payload.company_name,
        industry=payload.industry,
        opening_greeting=payload.opening_greeting,
        primary_instructions=payload.primary_instructions,
        tone=payload.tone,
        approved_pricing=payload.approved_pricing,
        qualification_criteria=payload.qualification_criteria,
        forbidden_phrases=payload.forbidden_phrases,
        transfer_ext=payload.transfer_ext
    )

    return {
        "success": saved,
        "message": "Instructions and persona saved successfully.",
        "section_7_1_compliant": True
    }


@router.post("/audit")
def audit_greeting(req: AuditRequest) -> Dict[str, Any]:
    """Audits any opening or script line against Section 7.1 & 7.3 writing rules."""
    report = auditor.audit_script(req.text)
    is_opening_valid, opening_violations = auditor.audit_opening(req.text)

    return {
        "is_natural": report.is_natural and is_opening_valid,
        "has_banned_ai_disclosure": report.has_banned_ai_disclosure or (not is_opening_valid),
        "violations": list(set(report.violations + opening_violations)),
        "filler_score": report.filler_score
    }


@router.post("/simulate")
def simulate_turn(req: SimulationRequest) -> Dict[str, Any]:
    """Simulates how the agent will respond to a test prompt using current instructions."""
    inst = brain_manager.get_instructions(req.campaign_id)
    fsm = SalesConversationFSM(
        agent_name=inst.get("agent_name", "Jordan"),
        company_name=inst.get("company_name", "Shadow Voice"),
        brain_manager=brain_manager
    )

    # If greeting simulation
    msg = (req.user_message or "").strip()
    if not msg:
        return {
            "speaker": "agent",
            "text": fsm.get_initial_greeting(),
            "stage": "CONNECTION"
        }

    turn_res = fsm.process_turn(msg)
    return {
        "speaker": "agent",
        "text": turn_res.agent_text,
        "stage": turn_res.next_stage.value,
        "action": turn_res.action,
        "disposition": turn_res.disposition_code,
        "objection_handled": turn_res.objection_handled
    }
