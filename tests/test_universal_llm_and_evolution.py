"""
Automated Tests for Universal LLM Providers, Interactive Turn Training & Autonomous Evolution
============================================================================================
Covers:
- Local Ollama & Custom OpenAI-compatible providers
- Barge-in streaming cancellation with sub-10ms abort
- Interactive Turn Training API (/api/calls/{session_id}/train-turn)
- Transcript export in text and JSON formats (/api/calls/{session_id}/export)
- Autonomous Self-Evolution Engine & API (/api/brain/evolve)
- LLM Connection Tester (/api/settings/test-llm)
"""

import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient

from shadow_voice.api.app import app
from shadow_voice.conversation.llm import (
    UniversalLLMClient,
    StreamingLLMClient,
    OllamaProvider,
    CustomOpenAICompatibleProvider,
    GroqProvider
)
from shadow_voice.brain.brain import BrainManager
from shadow_voice.brain.evolution import BrainEvolutionEngine
from shadow_voice.core.db import get_connection

client = TestClient(app)


def test_universal_llm_client_initialization_and_routing():
    """Verifies UniversalLLMClient instantiates providers and resolves models cleanly."""
    c = UniversalLLMClient(provider="ollama", model="llama3.2:latest")
    assert c.active_provider_name == "ollama"
    assert c.current_model == "llama3.2:latest"

    prov = c.get_provider("ollama")
    assert isinstance(prov, OllamaProvider)
    assert prov.name == "ollama"

    # Test Custom local provider (LM Studio / vLLM)
    custom_prov = c.get_provider("custom")
    assert isinstance(custom_prov, CustomOpenAICompatibleProvider)
    assert custom_prov.name == "custom"
    models = custom_prov.list_models()
    assert isinstance(models, list)
    assert len(models) > 0

    # Test Groq provider
    groq_prov = c.get_provider("groq")
    assert isinstance(groq_prov, GroqProvider)
    assert groq_prov.name == "groq"


def test_llm_completion_with_mock_and_fallback():
    """Verifies that chat_completion produces responses with low latency instrumentation."""
    c = UniversalLLMClient()
    res = c.chat_completion(
        messages=[{"role": "user", "content": "What is Shadow Voice?"}],
        mock_response="Shadow Voice delivers high-volume telephony with sub-second response times."
    )
    assert "Shadow Voice" in res["content"]
    assert res["ttft_ms"] > 0
    assert res["total_latency_ms"] > 0


@pytest.mark.asyncio
async def test_streaming_barge_in_instantaneous_cancellation():
    """Verifies that token streaming aborts immediately when caller barges in."""
    c = UniversalLLMClient(simulated_ttft_ms=30.0, simulated_token_ms=50.0)
    cancel_event = asyncio.Event()

    tokens_received = []

    async def run_stream():
        async for token, ttft in c.stream_generate(
            messages=[{"role": "user", "content": "Tell me a long story about dialers."}],
            cancel_event=cancel_event,
            mock_response="Word1 Word2 Word3 Word4 Word5 Word6 Word7 Word8 Word9 Word10"
        ):
            tokens_received.append(token)
            if len(tokens_received) == 2:
                # Caller barges in!
                cancel_event.set()

    start_time = time.time()
    await run_stream()
    duration = time.time() - start_time

    # Must have aborted after 2 tokens, not emitting all 10
    assert len(tokens_received) <= 3
    assert duration < 0.5  # Cancelled immediately, didn't wait for all tokens


def test_interactive_turn_training_api():
    """Verifies POST /api/calls/{session_id}/train-turn saves directly into brain with approved status."""
    session_id = f"test-train-{int(time.time())}"
    payload = {
        "question_text": "Do you support VICIdial FastAGI carrier integration?",
        "approved_answer": "Yes, we integrate natively via SIP trunks and FastAGI with zero carrier latency.",
        "category": "technical",
        "sentiment": "neutral"
    }

    resp = client.post(f"/api/calls/{session_id}/train-turn", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "approved"
    assert data["question_id"] is not None

    # Verify that Brain immediately recognizes this approved answer
    brain = BrainManager()
    matched = brain.find_matching_approved_answer("Do you guys support VICIdial FastAGI?")
    assert matched is not None
    assert "FastAGI" in matched


def test_call_transcript_export_api():
    """Verifies GET /api/calls/{session_id}/export outputs formatted script or JSON."""
    session_id = f"test-export-{int(time.time())}"
    transcript = [
        {"speaker": "agent", "text": "Hi, this is Jordan calling from Shadow Voice — do you have a quick minute?", "timestamp": 0.0, "latency_ms": 12.0},
        {"speaker": "caller", "text": "Can you handle 10,000 calls a day?", "timestamp": 3.5},
        {"speaker": "agent", "text": "Yes, our telephony cluster scales to over 50,000 concurrent channels.", "timestamp": 5.0, "latency_ms": 110.0}
    ]

    # Insert test call log
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO call_logs (session_id, phone_number, duration_sec, disposition, transcript, created_at)
        VALUES (?, '+1 (555) 019-9999', 15.0, 'SALE', ?, CURRENT_TIMESTAMP)
    """, (session_id, json.dumps(transcript)))
    conn.commit()
    conn.close()

    # Test text export
    resp_txt = client.get(f"/api/calls/{session_id}/export?format=text")
    assert resp_txt.status_code == 200
    txt_data = resp_txt.json()
    assert txt_data["format"] == "text"
    assert "=== CALL TRANSCRIPT:" in txt_data["content"]
    assert "Jordan (Agent)" in txt_data["content"]
    assert "Customer:" in txt_data["content"]

    # Test JSON export
    resp_json = client.get(f"/api/calls/{session_id}/export?format=json")
    assert resp_json.status_code == 200
    j_data = resp_json.json()
    assert j_data["format"] == "json"
    assert len(j_data["transcript"]) == 3
    assert j_data["metadata"]["disposition"] == "SALE"


def test_autonomous_brain_evolution_engine_and_api():
    """Verifies that the autonomous evolution engine analyzes calls and evolves memory."""
    # Ensure there's at least one call log with an objection and a question
    session_id = f"test-evo-{int(time.time())}"
    transcript = [
        {"speaker": "agent", "text": "Hi, this is Jordan calling from Shadow Voice — do you have a quick minute?", "timestamp": 0.0},
        {"speaker": "caller", "text": "Is this service expensive compared to standard SIP carriers?", "timestamp": 3.0},
        {"speaker": "agent", "text": "Our usage-based rates start at just two cents per connected minute.", "timestamp": 5.2},
        {"speaker": "caller", "text": "We already have an in-house dialer, but send me an email.", "timestamp": 8.0}
    ]

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO call_logs (session_id, phone_number, duration_sec, disposition, transcript, created_at)
        VALUES (?, '+1 (555) 019-8888', 12.0, 'CALLBK', ?, CURRENT_TIMESTAMP)
    """, (session_id, json.dumps(transcript)))
    conn.commit()
    conn.close()

    # Trigger evolution pass via API
    resp = client.post("/api/brain/evolve", json={"limit_calls": 5, "auto_approve": True})
    assert resp.status_code == 200
    data = resp.json()

    assert data["calls_analyzed"] >= 1
    assert data["naturalness_score"] >= 80.0
    assert "insights_summary" in data

    # Verify evolution history endpoint
    resp_hist = client.get("/api/brain/evolution-history?limit=5")
    assert resp_hist.status_code == 200
    hist = resp_hist.json()
    assert len(hist) >= 1
    assert hist[0]["calls_analyzed"] >= 1


def test_llm_test_connection_endpoint():
    """Verifies POST /api/settings/test-llm tests provider connection and inference."""
    payload = {
        "provider": "ollama",
        "model": "llama3.2:latest",
        "test_prompt": "Are you ready?"
    }
    resp = client.post("/api/settings/test-llm", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "provider" in data
    assert "latency_ms" in data
    assert "connected" in data
