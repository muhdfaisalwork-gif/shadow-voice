"""
Shadow Voice Cognitive Brain Manager
====================================
Manages:
- Dynamic Campaign Instructions & Tone
- Customer Question Learning & Approval Workflow
- Story Bank & Verified Receipts
- Real-time Conversational Context Injection
"""

from __future__ import annotations
import json
import logging
import re
from typing import List, Dict, Any, Optional
from shadow_voice.core.db import get_connection

logger = logging.getLogger("shadow_voice.brain")


class BrainManager:
    """Core interface for the agent's long-term memory, evolving knowledge, and receipts."""

    def __init__(self) -> None:
        pass

    # =========================================================================
    # 1. INSTRUCTIONS & PERSONA MANAGEMENT
    # =========================================================================

    def get_instructions(self, campaign_id: str = "DEFAULT_SALES_V1") -> Dict[str, Any]:
        """Retrieves active campaign instructions and persona configuration."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM instructions WHERE campaign_id = ?", (campaign_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            # Fallback default
            return {
                "campaign_id": campaign_id,
                "agent_name": "Jordan",
                "company_name": "Shadow Voice",
                "industry": "Telephony & AI Automation",
                "opening_greeting": "Hi, this is Jordan calling from Shadow Voice — do you have a quick minute?",
                "primary_instructions": "Speak naturally as a normal person-to-person business conversation. Never disclose or state you are an AI or automated system in the opening.",
                "tone": "Confident, friendly, consultative, concise",
                "approved_pricing": ["usage-based", "custom quote", "per-connected-minute", "$0.02 to $0.05/min"],
                "qualification_criteria": ["Decision-maker status", "Call volume > 5,000 mins/mo"],
                "forbidden_phrases": ["I am an AI", "automated calling", "virtual assistant"],
                "transfer_ext": "8300"
            }

        res = dict(row)
        for key in ["approved_pricing", "qualification_criteria", "forbidden_phrases"]:
            if isinstance(res.get(key), str):
                try:
                    res[key] = json.loads(res[key])
                except Exception:
                    res[key] = [res[key]]
        return res

    def save_instructions(
        self,
        campaign_id: str,
        agent_name: str,
        company_name: str,
        opening_greeting: str,
        primary_instructions: str,
        tone: str,
        industry: str = "Telephony Automation",
        approved_pricing: Optional[List[str]] = None,
        qualification_criteria: Optional[List[str]] = None,
        forbidden_phrases: Optional[List[str]] = None,
        transfer_ext: str = "8300"
    ) -> bool:
        """Saves or updates campaign instructions and persona settings."""
        conn = get_connection()
        cursor = conn.cursor()

        pricing_json = json.dumps(approved_pricing or ["usage-based", "custom quote"])
        qual_json = json.dumps(qualification_criteria or ["Decision maker", "High volume"])
        forbid_json = json.dumps(forbidden_phrases or ["I am an AI", "automated calling"])

        cursor.execute("""
            INSERT INTO instructions (
                campaign_id, agent_name, company_name, industry, opening_greeting,
                primary_instructions, tone, approved_pricing, qualification_criteria,
                forbidden_phrases, transfer_ext, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(campaign_id) DO UPDATE SET
                agent_name = excluded.agent_name,
                company_name = excluded.company_name,
                industry = excluded.industry,
                opening_greeting = excluded.opening_greeting,
                primary_instructions = excluded.primary_instructions,
                tone = excluded.tone,
                approved_pricing = excluded.approved_pricing,
                qualification_criteria = excluded.qualification_criteria,
                forbidden_phrases = excluded.forbidden_phrases,
                transfer_ext = excluded.transfer_ext,
                updated_at = CURRENT_TIMESTAMP
        """, (
            campaign_id, agent_name, company_name, industry, opening_greeting,
            primary_instructions, tone, pricing_json, qual_json, forbid_json, transfer_ext
        ))

        conn.commit()
        conn.close()
        return True

    # =========================================================================
    # 2. CUSTOMER QUESTION LEARNING & EVOLUTION
    # =========================================================================

    def get_customer_questions(
        self,
        status: Optional[str] = None,
        query: str = "",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Retrieves learned customer questions filtered by review status and query."""
        conn = get_connection()
        cursor = conn.cursor()

        sql = "SELECT * FROM customer_questions WHERE 1=1"
        params: List[Any] = []

        if status and status.lower() != "all":
            sql += " AND status = ?"
            params.append(status.lower())

        if query:
            sql += " AND (question_text LIKE ? OR proposed_answer LIKE ? OR approved_answer LIKE ?)"
            q_like = f"%{query.strip()}%"
            params.extend([q_like, q_like, q_like])

        sql += " ORDER BY frequency DESC, id DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_or_increment_question(
        self,
        question_text: str,
        session_id: Optional[str] = None,
        sentiment: str = "neutral",
        category: str = "general",
        proposed_answer: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Dynamically records or increments a customer question learned during calls.
        Normalizes text to detect recurrent questions.
        """
        clean_q = (question_text or "").strip()
        norm_query = re.sub(r"[^\w\s]", "", clean_q.lower()).strip()
        if len(norm_query) < 3:
            return {
                "id": None,
                "question_text": clean_q,
                "status": "ignored",
                "approved_answer": None
            }

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, frequency, approved_answer, status FROM customer_questions WHERE normalized_query = ?", (norm_query,))
        existing = cursor.fetchone()

        if existing:
            new_freq = existing["frequency"] + 1
            cursor.execute("""
                UPDATE customer_questions
                SET frequency = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_freq, existing["id"]))
            conn.commit()
            q_id = existing["id"]
            approved = existing["approved_answer"]
            status = existing["status"]
        else:
            draft_answer = proposed_answer or f"We can certainly assist with {question_text}. Our team has specialized solutions in place for this."
            cursor.execute("""
                INSERT INTO customer_questions (
                    question_text, normalized_query, session_id, frequency, sentiment,
                    category, proposed_answer, status, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, 'pending_review', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (question_text, norm_query, session_id, sentiment, category, draft_answer))
            conn.commit()
            q_id = cursor.lastrowid
            approved = None
            status = "pending_review"

        conn.close()
        return {
            "id": q_id,
            "question_text": question_text,
            "status": status,
            "approved_answer": approved
        }

    def update_question_status(
        self,
        question_id: int,
        status: str,
        approved_answer: Optional[str] = None
    ) -> bool:
        """Approves, edits, or archives a customer question."""
        conn = get_connection()
        cursor = conn.cursor()

        if approved_answer is not None:
            cursor.execute("""
                UPDATE customer_questions
                SET status = ?, approved_answer = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (status, approved_answer, question_id))
        else:
            cursor.execute("""
                UPDATE customer_questions
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (status, question_id))

        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    def delete_question(self, question_id: int) -> bool:
        """Deletes a learned customer question from the brain."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM customer_questions WHERE id = ?", (question_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def find_matching_approved_answer(self, user_utterance: str) -> Optional[str]:
        """Checks if a customer question matches an existing approved answer in the brain."""
        norm_utterance = re.sub(r"[^\w\s]", "", (user_utterance or "").lower()).strip()
        stopwords = {
            "what", "how", "why", "when", "who", "do", "does", "did", "you", "guys",
            "we", "the", "a", "an", "is", "are", "can", "could", "would", "to", "for",
            "with", "your", "our", "it", "support", "have", "has", "about", "tell", "me"
        }
        utterance_words = set(w for w in norm_utterance.split() if w not in stopwords)
        if not utterance_words:
            return None

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT question_text, approved_answer
            FROM customer_questions
            WHERE status IN ('approved', 'active') AND approved_answer IS NOT NULL
        """)
        rows = cursor.fetchall()
        conn.close()

        best_match = None
        best_overlap = 0.0

        for r in rows:
            q_text = re.sub(r"[^\w\s]", "", (r["question_text"] or "").lower()).strip()
            q_words = set(w for w in q_text.split() if w not in stopwords)
            if not q_words:
                continue
            intersection = q_words.intersection(utterance_words)
            if not intersection:
                continue
            score = len(intersection) / len(utterance_words)
            if score > best_overlap:
                best_overlap = score
                best_match = r["approved_answer"]

        if best_overlap >= 0.5 and best_match:
            return best_match

        return None

    # =========================================================================
    # 3. STORY BANK & VERIFIED RECEIPTS
    # =========================================================================

    def get_story_bank(self, query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        """Queries verified technical receipts, case studies, and numbers."""
        conn = get_connection()
        cursor = conn.cursor()

        if query and query.strip():
            sql = """
                SELECT * FROM story_bank
                WHERE title LIKE ? OR detail LIKE ? OR verified_metrics LIKE ? OR tags LIKE ?
                ORDER BY id DESC LIMIT ?
            """
            q_like = f"%{query.strip()}%"
            cursor.execute(sql, (q_like, q_like, q_like, q_like, limit))
        else:
            cursor.execute("SELECT * FROM story_bank ORDER BY id DESC LIMIT ?", (limit,))

        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_story(
        self,
        category: str,
        title: str,
        detail: str,
        verified_metrics: str = "",
        tags: str = ""
    ) -> int:
        """Adds a verified proof receipt or benchmark to the story bank."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO story_bank (category, title, detail, verified_metrics, tags, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (category, title, detail, verified_metrics, tags))
        conn.commit()
        story_id = cursor.lastrowid
        conn.close()
        return story_id

    def delete_story(self, story_id: int) -> bool:
        """Deletes a story from the story bank."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM story_bank WHERE id = ?", (story_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    # =========================================================================
    # 4. CONVERSATIONAL CONTEXT BUILDER
    # =========================================================================

    def build_system_prompt(self, campaign_id: str = "DEFAULT_SALES_V1") -> str:
        """
        Builds the unified conversational system prompt combining:
        1. Plain-English User Instructions & Persona
        2. Natural Opening Rule (Section 7.1)
        3. Verified Story Bank Receipts
        4. Approved Customer Q&A Learnings
        5. Guardrails (No unapproved pricing, no fake AI disclosures)
        """
        inst = self.get_instructions(campaign_id)
        stories = self.get_story_bank(limit=4)
        approved_qas = self.get_customer_questions(status="approved", limit=5)

        story_receipts_text = "\n".join([
            f"- [{s['title']}]: {s['detail']} (Receipts: {s.get('verified_metrics', 'N/A')})"
            for s in stories
        ])

        qa_learnings_text = "\n".join([
            f"Q: {q['question_text']}\nA: {q['approved_answer']}"
            for q in approved_qas if q.get("approved_answer")
        ]) or "No prior questions recorded yet."

        approved_pricing_str = ", ".join(inst.get("approved_pricing") or [])
        qual_criteria_str = ", ".join(inst.get("qualification_criteria") or [])
        forbidden_str = ", ".join(inst.get("forbidden_phrases") or [])

        prompt = f"""You are {inst['agent_name']}, representing {inst['company_name']} in the {inst['industry']} sector.

### NON-NEGOTIABLE CORE DIRECTIVE:
1. Every call MUST begin as a natural, person-to-person business conversation.
2. Opening greeting strictly: "{inst['opening_greeting']}"
3. NEVER state or disclose that you are an AI, a computer, a robot, an automated voice, or a virtual assistant. Speak as a confident, knowledgeable human representative.
4. Listen attentively to customer questions, acknowledge them naturally (e.g., "Understood", "Makes sense", "Great question"), and answer directly without corporate jargon.

### USER-PROVIDED INSTRUCTIONS:
{inst['primary_instructions']}

### TONE & DELIVERY:
{inst['tone']}

### VERIFIED STORY BANK (REAL NUMBERS & METRICS TO CITE):
{story_receipts_text}

### APPROVED CUSTOMER Q&A (LEARNED FROM REAL CALLS):
{qa_learnings_text}

### BOUNDARIES & GUARDRAILS:
- Approved Pricing Terms: {approved_pricing_str}
- Qualification Criteria: {qual_criteria_str}
- Forbidden Phrases / Claims: {forbidden_str}
- When ready for transfer or consultative handoff: Offer transfer to extension {inst['transfer_ext']} cleanly.
"""
        return prompt
