"""
OpenAI Provider
===============
Direct connection to OpenAI API (GPT-4o, GPT-4o-mini).
"""

from __future__ import annotations
import os
from typing import Optional, List
from .custom import CustomOpenAICompatibleProvider


class OpenAIProvider(CustomOpenAICompatibleProvider):
    """Direct OpenAI API Provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0
    ) -> None:
        url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        key = api_key or os.getenv("OPENAI_API_KEY", "")
        selected_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        super().__init__(base_url=url, api_key=key, model=selected_model, timeout=timeout)

    @property
    def name(self) -> str:
        return "openai"

    def list_models(self) -> List[str]:
        return ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "o1-mini"]
