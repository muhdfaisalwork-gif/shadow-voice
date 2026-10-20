"""
System Settings API Router
==========================
Handles:
- LLM Provider & Model selection (Ollama, Groq, OpenRouter, OpenAI, Gemini)
- Speech engine selection (Deepgram Nova-3, Cartesia Sonic, Qwen3-TTS)
- Daily spend ceilings & Kill Switch trigger
"""

from __future__ import annotations
import logging
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

from shadow_voice.core.db import get_connection
from shadow_voice.core.kill_switch import KillSwitch, KillSwitchRole

logger = logging.getLogger("shadow_voice.api.settings")
router = APIRouter(prefix="/api/settings", tags=["System Settings"])

kill_switch = KillSwitch.get_instance()


class UpdateSettingsRequest(BaseModel):
    settings: Dict[str, Any]


class KillSwitchRequest(BaseModel):
    trigger: bool
    reason: str = "Manual toggle from dashboard"
    role: Optional[str] = "PM"  # PM, QA, SRE, SPEND_GUARD


class TestLLMRequest(BaseModel):
    provider: str = "ollama"
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    test_prompt: str = "Hello, what voice automation capabilities do you specialize in?"


@router.get("/")
def get_settings() -> Dict[str, Any]:
    """Retrieves all persisted system configuration settings."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    settings = {r["key"]: r["value"] for r in cursor.fetchall()}
    conn.close()

    from shadow_voice.conversation.llm import UniversalLLMClient
    client = UniversalLLMClient()
    ollama_prov = client.get_provider("ollama")
    ollama_live = ollama_prov.is_connected()
    ollama_models = ollama_prov.list_models() if ollama_live else ["llama3.2:latest", "deepseek-r1:latest", "qwen2.5:latest"]

    ks = KillSwitch.get_instance()

    return {
        "settings": settings,
        "kill_switch_active": ks.is_triggered,
        "ollama_connected": ollama_live,
        "available_models": {
            "ollama": ollama_models,
            "custom": ["local-model", "llama-3-8b", "mistral-7b"],
            "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
            "openrouter": ["google/gemma-4-31b-it:free", "meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen-2.5-72b-instruct:free", "deepseek/deepseek-chat"],
            "openai": ["gpt-4o", "gpt-4o-mini"],
            "gemini": ["gemini-2.0-flash", "gemini-1.5-pro"],
            "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
        },
        "available_stt": ["deepgram_nova3", "flux_streaming", "mock"],
        "available_tts": ["cartesia_sonic", "qwen3_tts", "elevenlabs", "mock"]
    }


@router.post("/")
def update_settings(req: UpdateSettingsRequest) -> Dict[str, Any]:
    """Updates global settings."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for k, v in (req.settings or {}).items():
            if v is None:
                continue
            val_str = str(v)
            if val_str in ("••••••••", "********"):
                continue
            cursor.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """, (str(k), val_str))
        conn.commit()
    finally:
        conn.close()
    return {"success": True, "message": "Settings updated successfully."}


@router.post("/kill-switch")
def toggle_kill_switch(req: KillSwitchRequest) -> Dict[str, Any]:
    """Toggles the emergency system-wide kill switch."""
    role_map = {
        "PM": KillSwitchRole.PM,
        "QA": KillSwitchRole.QA,
        "SRE": KillSwitchRole.SRE,
        "SPEND_GUARD": KillSwitchRole.SPEND_GUARD
    }
    assigned_role = role_map.get((req.role or "").strip().upper(), KillSwitchRole.PM)
    ks = KillSwitch.get_instance()

    if req.trigger:
        ks.trigger_kill_switch(role=assigned_role, reason=req.reason)
    else:
        ks.reset_kill_switch(role=assigned_role)

    return {
        "kill_switch_active": ks.is_triggered,
        "message": f"Kill switch is now {'ACTIVATED' if ks.is_triggered else 'DEACTIVATED'}."
    }


@router.post("/test-llm")
def test_llm_connection(req: TestLLMRequest) -> Dict[str, Any]:
    """Tests connectivity and prompt generation with specified LLM provider."""
    from shadow_voice.conversation.llm import UniversalLLMClient
    client = UniversalLLMClient(
        provider=req.provider,
        api_key=req.api_key,
        model=req.model,
        base_url=req.base_url
    )
    provider = client.get_provider(req.provider)
    is_live = provider.is_connected()

    start = time.time()
    try:
        res = client.chat_completion(
            messages=[{"role": "user", "content": req.test_prompt}],
            provider_name=req.provider,
            max_tokens=80
        )
        latency = round((time.time() - start) * 1000.0, 1)
        return {
            "success": True,
            "connected": is_live,
            "provider": req.provider,
            "model_used": res.get("model_used", req.model or "default"),
            "latency_ms": latency,
            "response": res.get("content", "").strip()
        }
    except Exception as e:
        latency = round((time.time() - start) * 1000.0, 1)
        return {
            "success": False,
            "connected": is_live,
            "provider": req.provider,
            "model_used": req.model or "unknown",
            "latency_ms": latency,
            "error": str(e)
        }
