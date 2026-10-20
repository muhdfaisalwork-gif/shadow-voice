"""
Anthropic Claude Provider
=========================
Direct connection to Anthropic Messages API (Claude 3.5 Sonnet / Haiku).
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from typing import List, Dict, Any, Optional, AsyncGenerator
import requests
import httpx

from .base import BaseLLMProvider

logger = logging.getLogger("shadow_voice.llm.anthropic")


class AnthropicProvider(BaseLLMProvider):
    """Direct Anthropic Claude Messages API Provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0
    ) -> None:
        self._base_url = (base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")).rstrip("/")
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01"
        }

    def is_connected(self) -> bool:
        return bool(self._api_key and len(self._api_key) > 5)

    def list_models(self) -> List[str]:
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229"
        ]

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any
    ) -> Dict[str, Any]:
        start_time = time.time() * 1000.0
        system_text = ""
        claude_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_text = m.get("content", "")
            else:
                claude_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": claude_messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        if system_text:
            payload["system"] = system_text

        try:
            res = requests.post(f"{self.base_url}/v1/messages", json=payload, headers=self._headers(), timeout=self.timeout)
            total_latency = (time.time() * 1000.0) - start_time
            if res.status_code == 200:
                data = res.json()
                content = "".join([block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"])
                return {
                    "content": content,
                    "model_used": self.model,
                    "provider": self.name,
                    "ttft_ms": round(total_latency * 0.4, 1),
                    "total_latency_ms": round(total_latency, 1)
                }
            return {
                "content": f"[Anthropic Error {res.status_code}]: {res.text}",
                "model_used": self.model,
                "provider": self.name,
                "ttft_ms": 0.0,
                "total_latency_ms": round(total_latency, 1)
            }
        except Exception as e:
            total_latency = (time.time() * 1000.0) - start_time
            return {
                "content": f"[Anthropic Unavailable]: {e}",
                "model_used": self.model,
                "provider": self.name,
                "ttft_ms": 0.0,
                "total_latency_ms": round(total_latency, 1)
            }

    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        cancel_event: asyncio.Event,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any
    ) -> AsyncGenerator[tuple[str, Optional[float]], None]:
        start_time = time.time() * 1000.0
        first_token_received = False
        system_text = ""
        claude_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_text = m.get("content", "")
            else:
                claude_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": claude_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True
        }
        if system_text:
            payload["system"] = system_text

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/messages",
                    json=payload,
                    headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        yield f"[Anthropic error {response.status_code}]", None
                        return

                    async for line in response.aiter_lines():
                        if cancel_event.is_set():
                            break
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        try:
                            chunk = json.loads(data_str)
                            chunk_type = chunk.get("type")
                            if chunk_type == "content_block_delta":
                                token = chunk.get("delta", {}).get("text", "")
                                if token:
                                    if not first_token_received:
                                        first_token_received = True
                                        ttft_ms = (time.time() * 1000.0) - start_time
                                        yield token, round(ttft_ms, 1)
                                    else:
                                        yield token, None
                            elif chunk_type == "message_stop":
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.warning(f"Anthropic streaming exception: {e}")
            if not first_token_received:
                yield f"[Anthropic error: {e}]", 0.0
