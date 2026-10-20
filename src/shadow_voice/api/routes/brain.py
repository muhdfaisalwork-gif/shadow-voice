"""
Cognitive Brain & Customer Learning API Router
===============================================
Handles:
- Customer learned questions review & approval workflow
- Story Bank receipts (latency numbers, metrics, case studies)
- Memory statistics & search
"""

from __future__ import annotations
import logging
from dataclasses import asdict
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shadow_voice.brain.brain import BrainManager
from shadow_voice.brain.evolution import BrainEvolutionEngine

logger = logging.getLogger("shadow_voice.api.brain")
router = APIRouter(prefix="/api/brain", tags=["Cognitive Brain & Learning"])

brain_manager = BrainManager()


class ApproveQuestionRequest(BaseModel):
    approved_answer: str
    status: str = "approved"


class UpdateQuestionRequest(BaseModel):
    status: str  # "approved", "active", "pending_review", "rejected"
    approved_answer: Optional[str] = None


class CreateQuestionRequest(BaseModel):
    question_text: str
    proposed_answer: Optional[str] = None
    approved_answer: Optional[str] = None
    category: str = "general"
    status: str = "approved"


class StoryBankItem(BaseModel):
    category: str
    title: str
    detail: str
    verified_metrics: str = ""
    tags: str = ""


class EvolveRequest(BaseModel):
    limit_calls: int = 15
    auto_approve: bool = True


@router.get("/stats")
def get_brain_stats() -> Dict[str, Any]:
    """Returns overview statistics of the Cognitive Brain."""
    all_q = brain_manager.get_customer_questions(limit=500)
    pending = [q for q in all_q if q.get("status") == "pending_review"]
    approved = [q for q in all_q if q.get("status") in ("approved", "active")]
    stories = brain_manager.get_story_bank(limit=500)

    engine = BrainEvolutionEngine(brain_manager=brain_manager)
    history = engine.get_evolution_history(limit=1)
    latest_nat = history[0].get("naturalness_score", 98.0) if history else 98.0

    return {
        "total_learned_questions": len(all_q),
        "pending_review_count": len(pending),
        "approved_count": len(approved),
        "story_bank_receipts_count": len(stories),
        "evolution_rounds_count": len(engine.get_evolution_history(limit=100)),
        "naturalness_score": latest_nat,
        "memory_status": "synced_and_evolving"
    }


@router.get("/questions")
def get_customer_questions(
    status: Optional[str] = None,
    query: str = "",
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Retrieves customer questions learned from calls."""
    return brain_manager.get_customer_questions(status=status, query=query, limit=limit)


@router.put("/questions/{question_id}/approve")
def approve_question(question_id: int, req: ApproveQuestionRequest) -> Dict[str, Any]:
    """Approves a learned customer question and sets the definitive agent answer."""
    success = brain_manager.update_question_status(
        question_id=question_id,
        status=req.status,
        approved_answer=req.approved_answer
    )
    if not success:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"success": True, "message": "Question approved. Agent will now use this answer live."}


@router.put("/questions/{question_id}")
def update_question(question_id: int, req: UpdateQuestionRequest) -> Dict[str, Any]:
    """Updates question status or approved answer."""
    success = brain_manager.update_question_status(
        question_id=question_id,
        status=req.status,
        approved_answer=req.approved_answer
    )
    if not success:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"success": True, "message": "Question updated successfully"}


@router.post("/questions")
def create_question(req: CreateQuestionRequest) -> Dict[str, Any]:
    """Creates a customer question with an optional approved answer."""
    if not (req.question_text or "").strip():
        raise HTTPException(status_code=400, detail="question_text cannot be empty")
    res = brain_manager.add_or_increment_question(
        question_text=req.question_text.strip(),
        category=req.category or "general",
        proposed_answer=req.proposed_answer or req.approved_answer
    )
    if req.approved_answer and res.get("id"):
        brain_manager.update_question_status(res["id"], status=req.status, approved_answer=req.approved_answer)
    return {"success": True, "question_id": res["id"], "message": "Question created successfully"}


@router.delete("/questions/{question_id}")
def delete_question(question_id: int) -> Dict[str, Any]:
    """Deletes a customer question from the brain."""
    deleted = brain_manager.delete_question(question_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"success": True, "message": "Question deleted from memory"}


@router.get("/stories")
def get_story_bank(query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves verified technical receipts and case studies from the Story Bank."""
    return brain_manager.get_story_bank(query=query, limit=limit)


@router.post("/stories")
def add_story(item: StoryBankItem) -> Dict[str, Any]:
    """Adds a new verified receipt or case study to the Story Bank."""
    if not (item.title or "").strip() or not (item.detail or "").strip():
        raise HTTPException(status_code=400, detail="Story title and detail cannot be empty")
    story_id = brain_manager.add_story(
        category=item.category or "case_study",
        title=item.title.strip(),
        detail=item.detail.strip(),
        verified_metrics=item.verified_metrics or "",
        tags=item.tags or ""
    )
    return {"success": True, "story_id": story_id, "message": "Receipt added to Story Bank."}


@router.delete("/stories/{story_id}")
def delete_story(story_id: int) -> Dict[str, Any]:
    """Deletes a story from the Story Bank."""
    deleted = brain_manager.delete_story(story_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"success": True, "message": "Story deleted."}


@router.post("/evolve")
def trigger_evolution(req: EvolveRequest) -> Dict[str, Any]:
    """Triggers an autonomous self-reflection and brain memory evolution pass."""
    engine = BrainEvolutionEngine(brain_manager=brain_manager)
    res = engine.evolve_from_transcripts(
        limit_calls=req.limit_calls,
        auto_approve_high_confidence=req.auto_approve
    )
    return asdict(res)


@router.get("/evolution-history")
def get_evolution_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieves records of past autonomous evolution rounds."""
    engine = BrainEvolutionEngine(brain_manager=brain_manager)
    return engine.get_evolution_history(limit=limit)
