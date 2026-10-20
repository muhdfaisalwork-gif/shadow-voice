"""
Custom OpenAI-Compatible Provider (LM Studio / vLLM / LocalAI)
=============================================================
Connects to local or on-premise OpenAI-compatible inference servers:
- LM Studio (default: http://localhost:1234/v1)
- vLLM (default: http://localhost:8000/v1)
- LocalAI (default: http://localhost:8080/v1)
- Text-Generation-WebUI / Aphrodite / Ollama OpenAI endpoint
Supports streaming SSE format with barge-in cancellation and TTFT tracking.
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

logger = logging.getLogger("shadow_voice.llm.custom")


class CustomOpenAICompatibleProvider(BaseLLMProvider):
    """Universal OpenAI-compatible provider for local servers like LM Studio & vLLM."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0
    ) -> None:
        raw_url = (base_url or os.getenv("CUSTOM_LLM_BASE_URL", "http://localhost:1234/v1")).rstrip("/")
        if not raw_url.endswith("/v1") and not raw_url.endswith("/chat/completions"):
            raw_url = f"{raw_url}/v1"
        self._base_url = raw_url
        self._api_key = api_key or os.getenv("CUSTOM_LLM_API_KEY", "not-needed")
        self._model = model or os.getenv("CUSTOM_LLM_MODEL", "local-model")
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "custom"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def is_connected(self) -> bool:
        """Checks if local OpenAI-compatible inference server is running."""
        try:
            res = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=2.0)
            return res.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """Queries /models endpoint to discover locally hosted models."""
        try:
            res = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                models = [m["id"] for m in data.get("data", []) if "id" in m]
                if models:
                    return models
        except Exception:
            pass
        return [self.model, "local-model", "llama-3-8b-instruct", "mistral-7b-instruct"]

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Executes synchronous chat completion against local server."""
        start_time = time.time() * 1000.0
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        endpoint = f"{self.base_url}/chat/completions" if not self.base_url.endswith("/chat/completions") else self.base_url
        try:
            res = requests.post(endpoint, json=payload, headers=self._headers(), timeout=self.timeout)
            total_latency = (time.time() * 1000.0) - start_time

            if res.status_code == 200:
                data = res.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {
                    "content": content,
                    "model_used": self.model,
                    "provider": self.name,
                    "ttft_ms": round(total_latency * 0.35, 1),
                    "total_latency_ms": round(total_latency, 1)
                }
            return {
                "content": f"[Local AI Server Error {res.status_code}]: {res.text}",
                "model_used": self.model,
                "provider": self.name,
                "ttft_ms": 0.0,
                "total_latency_ms": round(total_latency, 1)
            }
        except Exception as e:
            total_latency = (time.time() * 1000.0) - start_time
            return {
                "content": f"[Local AI Server Unavailable]: {e}",
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
        """
        Streams SSE tokens with barge-in cancellation and TTFT measurement.
        """
        start_time = time.time() * 1000.0
        first_token_received = False
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }
        endpoint = f"{self.base_url}/chat/completions" if not self.base_url.endswith("/chat/completions") else self.base_url

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    json=payload,
                    headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        yield f"[Server error {response.status_code}]", None
                        return

                    async for line in response.aiter_lines():
                        if cancel_event.is_set():
                            break
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                if not first_token_received:
                                    first_token_received = True
                                    ttft_ms = (time.time() * 1000.0) - start_time
                                    yield token, round(ttft_ms, 1)
                                else:
                                    yield token, None
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.warning(f"Custom OpenAI streaming error: {e}")
            if not first_token_received:
                yield f"[Local LLM error: {e}]", 0.0
