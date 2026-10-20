"""
Universal LLM Client & Streaming Engine
=======================================
Multi-model router and streaming client for conversational telephony agents:
- Supports 100% Local Models: Ollama (localhost:11434), LM Studio (localhost:1234/v1), vLLM
- Supports Cloud Models: Groq (sub-100ms), OpenRouter, OpenAI, Anthropic, Gemini
- Instant token-level abort on barge-in
- Time-to-first-token (TTFT) instrumentation
- Database-driven configuration with environment fallback
"""

from __future__ import annotations
import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, AsyncGenerator

from shadow_voice.core.db import get_connection
from .providers import (
    BaseLLMProvider,
    OllamaProvider,
    CustomOpenAICompatibleProvider,
    GroqProvider,
    OpenRouterProvider,
    OpenAIProvider,
    GeminiProvider,
    AnthropicProvider
)

logger = logging.getLogger("shadow_voice.llm.client")


def _get_db_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Helper to fetch setting directly from database if available."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ? LIMIT 1", (key,))
        row = c.fetchone()
        conn.close()
        if row and row["value"]:
            return row["value"]
    except Exception:
        pass
    return default


@dataclass
class LLMGenerationResult:
    text: str
    ttft_ms: float
    total_latency_ms: float
    model_version: str
    tokens_count: int
    was_cancelled: bool = False


class UniversalLLMClient:
    """
    Universal Multi-Model Engine:
    Seamlessly routes speech and brain requests to Local Ollama, LM Studio/vLLM,
    Groq, OpenRouter, OpenAI, Gemini, or Claude.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        simulated_ttft_ms: float = 120.0,
        simulated_token_ms: float = 10.0
    ) -> None:
        self._explicit_provider = provider
        self._explicit_api_key = api_key
        self._explicit_model = model
        self._explicit_base_url = base_url
        self.simulated_ttft_ms = simulated_ttft_ms
        self.simulated_token_ms = simulated_token_ms
        self._providers_cache: Dict[str, BaseLLMProvider] = {}

    @property
    def active_provider_name(self) -> str:
        if self._explicit_provider:
            return self._explicit_provider.lower()
        db_val = _get_db_setting("LLM_PROVIDER")
        env_val = os.getenv("LLM_PROVIDER")
        return (db_val or env_val or "ollama").lower()

    def get_base_url(self, provider_name: Optional[str] = None) -> Optional[str]:
        if self._explicit_base_url:
            return self._explicit_base_url
        prov = (provider_name or self.active_provider_name).lower()
        if prov == "ollama":
            return _get_db_setting("OLLAMA_BASE_URL") or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        elif prov in ("custom", "lmstudio", "vllm"):
            return _get_db_setting("CUSTOM_LLM_BASE_URL") or os.getenv("CUSTOM_LLM_BASE_URL", "http://localhost:1234/v1")
        elif prov == "groq":
            return _get_db_setting("GROQ_BASE_URL") or os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        elif prov == "openrouter":
            return _get_db_setting("OPENROUTER_BASE_URL") or os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        elif prov == "openai":
            return _get_db_setting("OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        return None

    @property
    def active_base_url(self) -> Optional[str]:
        return self.get_base_url()

    def get_model(self, provider_name: Optional[str] = None) -> str:
        if self._explicit_model:
            return self._explicit_model
        prov = (provider_name or self.active_provider_name).lower()
        ui_selected_model = _get_db_setting("SELECTED_MODEL")
        if prov == "ollama":
            return _get_db_setting("OLLAMA_MODEL") or ui_selected_model or os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        elif prov in ("custom", "lmstudio", "vllm"):
            return _get_db_setting("CUSTOM_LLM_MODEL") or ui_selected_model or os.getenv("CUSTOM_LLM_MODEL", "local-model")
        elif prov == "groq":
            return _get_db_setting("GROQ_MODEL") or ui_selected_model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        elif prov == "openai":
            return _get_db_setting("OPENAI_MODEL") or ui_selected_model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif prov == "gemini":
            return _get_db_setting("GEMINI_MODEL") or ui_selected_model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        elif prov == "anthropic":
            return _get_db_setting("ANTHROPIC_MODEL") or ui_selected_model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        else:
            return _get_db_setting("OPENROUTER_MODEL") or ui_selected_model or os.getenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")

    @property
    def current_model(self) -> str:
        return self.get_model()

    def get_api_key(self, provider_name: Optional[str] = None) -> Optional[str]:
        if self._explicit_api_key:
            return self._explicit_api_key
        prov = (provider_name or self.active_provider_name).lower()
        ui_api_key = _get_db_setting("API_KEY")
        if prov == "ollama":
            return None
        elif prov in ("custom", "lmstudio", "vllm"):
            return _get_db_setting("CUSTOM_LLM_API_KEY") or ui_api_key or os.getenv("CUSTOM_LLM_API_KEY")
        elif prov == "groq":
            return _get_db_setting("GROQ_API_KEY") or ui_api_key or os.getenv("GROQ_API_KEY")
        elif prov == "openai":
            return _get_db_setting("OPENAI_API_KEY") or ui_api_key or os.getenv("OPENAI_API_KEY")
        elif prov == "gemini":
            return _get_db_setting("GEMINI_API_KEY") or ui_api_key or os.getenv("GEMINI_API_KEY")
        elif prov == "anthropic":
            return _get_db_setting("ANTHROPIC_API_KEY") or ui_api_key or os.getenv("ANTHROPIC_API_KEY")
        else:
            return _get_db_setting("OPENROUTER_API_KEY") or ui_api_key or os.getenv("OPENROUTER_API_KEY")

    def get_provider(self, provider_name: Optional[str] = None) -> BaseLLMProvider:
        """Retrieves or instantiates the requested provider."""
        prov = (provider_name or self.active_provider_name).lower()
        if prov in self._providers_cache:
            return self._providers_cache[prov]

        key = self.get_api_key(prov)
        url = self.get_base_url(prov)
        model = self.get_model(prov)

        provider_obj: BaseLLMProvider
        if prov == "ollama":
            provider_obj = OllamaProvider(base_url=url, model=model)
        elif prov in ("custom", "lmstudio", "vllm"):
            provider_obj = CustomOpenAICompatibleProvider(base_url=url, api_key=key, model=model)
        elif prov == "groq":
            provider_obj = GroqProvider(base_url=url, api_key=key, model=model)
        elif prov == "openai":
            provider_obj = OpenAIProvider(base_url=url, api_key=key, model=model)
        elif prov == "gemini":
            provider_obj = GeminiProvider(base_url=url, api_key=key, model=model)
        elif prov == "anthropic":
            provider_obj = AnthropicProvider(base_url=url, api_key=key, model=model)
        else:
            provider_obj = OpenRouterProvider(base_url=url, api_key=key, model=model)

        self._providers_cache[prov] = provider_obj
        return provider_obj

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        provider_name: Optional[str] = None,
        mock_response: Optional[str] = None
    ) -> Dict[str, Any]:
        """Executes full chat completion."""
        if mock_response is not None:
            return {
                "content": mock_response,
                "model_used": "mock-simulator",
                "provider": "mock",
                "ttft_ms": 25.0,
                "total_latency_ms": 80.0
            }

        provider = self.get_provider(provider_name)
        try:
            return provider.chat_completion(
                messages=messages or [],
                temperature=temperature,
                max_tokens=max_tokens
            )
        except Exception as e:
            logger.warning(f"Provider {provider.name} failed: {e}. Falling back to default.")
            return {
                "content": "Thank you for sharing that. We provide customized telephony automation tailored to your dialer infrastructure.",
                "model_used": "fallback-safe",
                "provider": "fallback",
                "ttft_ms": 10.0,
                "total_latency_ms": 25.0
            }

    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        cancel_event: asyncio.Event,
        mock_response: Optional[str] = None,
        provider_name: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512
    ) -> AsyncGenerator[tuple[str, Optional[float]], None]:
        """
        Yields (token, ttft_ms_or_none).
        First yield contains ttft_ms.
        Checks cancel_event on every token to ensure instantaneous abort on barge-in.
        Supports fast mock simulation or live provider streaming.
        """
        # If mock_response is explicitly provided or provider is mock:
        if mock_response is not None:
            start_time = time.time() * 1000.0
            first_delay = self.simulated_ttft_ms / 1000.0
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=first_delay)
                return
            except asyncio.TimeoutError:
                pass

            ttft_ms = (time.time() * 1000.0) - start_time
            words = mock_response.split(" ")
            for i, word in enumerate(words):
                if cancel_event.is_set():
                    break
                token = word + (" " if i < len(words) - 1 else "")
                first_ttft = ttft_ms if i == 0 else None
                yield token, first_ttft
                await asyncio.sleep(self.simulated_token_ms / 1000.0)
            return

        provider = self.get_provider(provider_name)
        # Check connection before streaming live; if not connected, fall back to simulated response
        if not provider.is_connected() and provider.name not in ("openrouter", "openai", "groq"):
            # Provide natural default response so calls never stall
            fallback_text = "We specialize in conversational telephony automation for high-volume outbound dialers."
            start_time = time.time() * 1000.0
            first_delay = 0.05
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=first_delay)
                return
            except asyncio.TimeoutError:
                pass
            ttft_ms = (time.time() * 1000.0) - start_time
            words = fallback_text.split(" ")
            for i, word in enumerate(words):
                if cancel_event.is_set():
                    break
                token = word + (" " if i < len(words) - 1 else "")
                yield token, (ttft_ms if i == 0 else None)
                await asyncio.sleep(0.01)
            return

        # Stream directly from active provider with resilient error handling
        yielded_count = 0
        try:
            stream = provider.stream_generate(
                messages=messages or [],
                cancel_event=cancel_event,
                temperature=temperature,
                max_tokens=max_tokens
            )
            async for token, ttft in stream:
                if cancel_event.is_set():
                    break
                yield token, ttft
                yielded_count += 1
        except Exception as exc:
            logger.warning(
                f"[UniversalLLMClient] Upstream provider {provider.name} stream error: {exc}. "
                f"Tokens emitted prior to error: {yielded_count}"
            )
            # If nothing was emitted before the stream failed, yield conversational fallback so call never dies
            if yielded_count == 0 and not cancel_event.is_set():
                fallback_phrase = "I understand. Let me make sure I have all the right details for you."
                words = fallback_phrase.split(" ")
                for i, word in enumerate(words):
                    if cancel_event.is_set():
                        break
                    yield word + (" " if i < len(words) - 1 else ""), (50.0 if i == 0 else None)
                    await asyncio.sleep(0.01)


# Backward compatibility alias
class StreamingLLMClient(UniversalLLMClient):
    """Alias to UniversalLLMClient for backward compatibility."""
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        simulated_ttft_ms: float = 140.0,
        simulated_token_ms: float = 12.0
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            simulated_ttft_ms=simulated_ttft_ms,
            simulated_token_ms=simulated_token_ms
        )
