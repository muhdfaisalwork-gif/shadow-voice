"""
OpenRouter Multi-Model Cloud Provider
=====================================
Unified cloud routing to 200+ models (Claude, Llama 3, DeepSeek, Mistral, Qwen).
Uses standard OpenAI-compatible API at https://openrouter.ai/api/v1.
"""

from __future__ import annotations
import os
from typing import Optional, List, Dict
from .custom import CustomOpenAICompatibleProvider


class OpenRouterProvider(CustomOpenAICompatibleProvider):
    """OpenRouter Provider for multi-model access."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0
    ) -> None:
        url = base_url or os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        selected_model = model or os.getenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
        super().__init__(base_url=url, api_key=key, model=selected_model, timeout=timeout)

    @property
    def name(self) -> str:
        return "openrouter"

    def _headers(self) -> Dict[str, str]:
        headers = super()._headers()
        headers["HTTP-Referer"] = "https://shadowvoice.ai"
        headers["X-Title"] = "Shadow Voice Telephony Agent"
        return headers

    def list_models(self) -> List[str]:
        models = super().list_models()
        defaults = [
            "google/gemma-4-31b-it:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "deepseek/deepseek-chat",
            "anthropic/claude-3.5-sonnet"
        ]
        return list(dict.fromkeys(models + defaults))
