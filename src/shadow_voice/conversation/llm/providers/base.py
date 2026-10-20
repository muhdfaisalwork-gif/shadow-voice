"""
Base LLM Provider Interface
===========================
Defines the abstract interface for all LLM providers (Local Ollama, LM Studio,
Groq, OpenRouter, OpenAI, Gemini, Anthropic) supporting both full chat completions
and real-time token streaming with barge-in cancellation and TTFT instrumentation.
"""

from __future__ import annotations
import asyncio
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'ollama', 'custom', 'groq', 'openrouter', 'openai', etc.)."""
        pass

    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Executes synchronous/blocking chat completion.
        Returns dict with:
        {
            "content": str,
            "model_used": str,
            "provider": str,
            "ttft_ms": float,
            "total_latency_ms": float
        }
        """
        pass

    @abstractmethod
    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        cancel_event: asyncio.Event,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any
    ) -> AsyncGenerator[tuple[str, Optional[float]], None]:
        """
        Yields (token, ttft_ms_or_none).
        First yield contains ttft_ms.
        Checks cancel_event on every token to ensure instantaneous abort on barge-in.
        """
        pass

    @abstractmethod
    def list_models(self) -> List[str]:
        """Returns list of available models for this provider."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Checks if provider backend is reachable."""
        pass

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """Convenience method to generate text from a prompt."""
        messages: List[Dict[str, str]] = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": prompt or ""})

        res = self.chat_completion(messages, temperature=temperature)
        return res.get("content", "").strip()
