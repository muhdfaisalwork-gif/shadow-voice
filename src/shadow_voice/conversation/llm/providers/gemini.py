"""
Google Gemini Provider
======================
High-speed Gemini 2.0 Flash / Pro inference via Google Generative AI API.
"""

from __future__ import annotations
import os
from typing import Optional, List
from .custom import CustomOpenAICompatibleProvider


class GeminiProvider(CustomOpenAICompatibleProvider):
    """Google Gemini Provider using standard v1beta endpoint."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0
    ) -> None:
        url = base_url or os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
        key = api_key or os.getenv("GEMINI_API_KEY", "")
        selected_model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        super().__init__(base_url=url, api_key=key, model=selected_model, timeout=timeout)

    @property
    def name(self) -> str:
        return "gemini"

    def list_models(self) -> List[str]:
        return ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
