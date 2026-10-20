"""
Groq High-Speed Telephony Provider
==================================
Sub-100ms TTFT streaming inference using Groq LPU engine.
Uses OpenAI-compatible SSE endpoints at https://api.groq.com/openai/v1.
Ideal for conversational voice agents where low latency is critical.
"""

from __future__ import annotations
import os
from typing import Optional, List
from .custom import CustomOpenAICompatibleProvider


class GroqProvider(CustomOpenAICompatibleProvider):
    """Groq Provider for ultra-low latency conversational voice generation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 20.0
    ) -> None:
        url = base_url or os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        key = api_key or os.getenv("GROQ_API_KEY", "")
        selected_model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        super().__init__(base_url=url, api_key=key, model=selected_model, timeout=timeout)

    @property
    def name(self) -> str:
        return "groq"

    def list_models(self) -> List[str]:
        models = super().list_models()
        defaults = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it"
        ]
        return list(dict.fromkeys(models + defaults))
