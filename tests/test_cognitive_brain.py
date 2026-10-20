"""
Test Cognitive Brain & Customer Learning Bank
=============================================
Validates:
- Instruction persistence and Section 7.1 natural opening
- Customer question detection, frequency tracking, and draft proposal
- Question approval workflow and live answering
- Story Bank receipt creation and queries
"""

import pytest
from shadow_voice.core.db import init_db
from shadow_voice.brain.brain import BrainManager
from shadow_voice.brain.learner import CustomerQuestionLearner


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    from shadow_voice.core.db import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM customer_questions WHERE question_text LIKE 'Do you guys support custom protocol%'")
    conn.commit()
    conn.close()



def test_brain_instructions_crud():
    brain = BrainManager()
    campaign_id = "TEST_CAMPAIGN_001"

    # Save custom instructions
    saved = brain.save_instructions(
        campaign_id=campaign_id,
        agent_name="Morgan",
        company_name="Acme Voice",
        opening_greeting="Hi, this is Morgan calling from Acme Voice — do you have a quick minute?",
        primary_instructions="Ask about current call center volumes and qualify.",
        tone="Friendly, consultative",
        approved_pricing=["$0.03/min", "custom tier"],
        qualification_criteria=["5+ agents", "Predictive dialer in place"]
    )
    assert saved is True

    # Retrieve
    inst = brain.get_instructions(campaign_id)
    assert inst["agent_name"] == "Morgan"
    assert inst["company_name"] == "Acme Voice"
    assert "Section 7.1" not in inst["opening_greeting"]
    assert "Hi, this is Morgan calling from Acme Voice" in inst["opening_greeting"]
    assert "$0.03/min" in inst["approved_pricing"]


def test_customer_question_learning_and_approval():
    import uuid
    brain = BrainManager()
    learner = CustomerQuestionLearner(brain)

    unique_tag = uuid.uuid4().hex[:6]
    question = f"Do you guys support custom protocol {unique_tag}?"

    # Turn 1: question asked first time
    is_q, existing_ans, rec1 = learner.process_turn(question, session_id="test-sess-1")
    assert is_q is True
    assert existing_ans is None
    assert rec1 is not None
    assert rec1["status"] == "pending_review"

    # Turn 2: question asked again in another session -> should increment frequency
    is_q2, existing_ans2, rec2 = learner.process_turn(question, session_id="test-sess-2")
    assert is_q2 is True
    assert rec2["id"] == rec1["id"]

    # Verify in DB
    all_q = brain.get_customer_questions(query=unique_tag)
    assert len(all_q) >= 1
    target = all_q[0]
    assert target["frequency"] >= 2

    # User approves question with definitive answer
    definitive_answer = f"Yes, protocol {unique_tag} is fully supported with encrypted tunneling."
    ok = brain.update_question_status(target["id"], status="approved", approved_answer=definitive_answer)
    assert ok is True

    # Turn 3: same question asked -> learner returns approved answer!
    is_q3, existing_ans3, rec3 = learner.process_turn(f"Do you guys support custom protocol {unique_tag}?", session_id="test-sess-3")
    assert is_q3 is True
    assert existing_ans3 is not None
    assert f"protocol {unique_tag}" in existing_ans3


def test_story_bank_receipts():
    brain = BrainManager()
    story_id = brain.add_story(
        category="latency",
        title="Sub-500ms P95 Playout Benchmark",
        detail="Streamlined AudioSocket direct framing with Cartesia Sonic continuation.",
        verified_metrics="P95: 480ms | 0 packet jitter",
        tags="benchmark, latency"
    )
    assert story_id > 0

    stories = brain.get_story_bank(query="Sub-500ms")
    assert len(stories) >= 1
    assert stories[0]["verified_metrics"] == "P95: 480ms | 0 packet jitter"

    # Delete
    del_ok = brain.delete_story(story_id)
    assert del_ok is True


def test_conversational_system_prompt_builder():
    brain = BrainManager()
    prompt = brain.build_system_prompt()
    assert "NON-NEGOTIABLE CORE DIRECTIVE" in prompt
    assert "NEVER state or disclose that you are an AI" in prompt
    assert "VERIFIED STORY BANK" in prompt
    assert "APPROVED CUSTOMER Q&A" in prompt
