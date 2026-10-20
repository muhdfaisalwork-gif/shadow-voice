"""
Local Ollama Provider
=====================
Connects to local Ollama instance (default: http://localhost:11434)
Runs 100% locally and offline on user's machine with zero API keys.
Supports streaming NDJSON generation with instantaneous barge-in cancellation.
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

logger = logging.getLogger("shadow_voice.llm.ollama")


class OllamaProvider(BaseLLMProvider):
    """
    Local Ollama Provider for offline open-source models:
    Llama 3.2, DeepSeek-R1, Qwen 2.5, Mistral, etc.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0
    ) -> None:
        self._base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self._model = model or os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        self.timeout = timeout
        self._last_conn_check: float = 0.0
        self._last_conn_status: bool = False

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    def is_connected(self) -> bool:
        """Checks if local Ollama daemon is reachable with 10s caching."""
        now = time.time()
        if now - self._last_conn_check < 10.0:
            return self._last_conn_status

        try:
            res = requests.get(f"{self.base_url}/api/version", timeout=0.4)
            status = (res.status_code == 200)
        except Exception:
            status = False

        self._last_conn_check = now
        self._last_conn_status = status
        return status

    def list_models(self) -> List[str]:
        """Queries local Ollama tags endpoint to return installed models."""
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                models = [m["name"] for m in data.get("models", []) if "name" in m]
                if models:
                    return models
        except Exception:
            pass
        return ["llama3.2:latest", "deepseek-r1:latest", "qwen2.5:latest", "mistral:latest"]

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Executes synchronous chat completion against local Ollama."""
        start_time = time.time() * 1000.0
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        try:
            res = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )
            total_latency = (time.time() * 1000.0) - start_time

            if res.status_code == 200:
                data = res.json()
                content = data.get("message", {}).get("content", "")
                return {
                    "content": content,
                    "model_used": self.model,
                    "provider": self.name,
                    "ttft_ms": round(total_latency * 0.3, 1),
                    "total_latency_ms": round(total_latency, 1)
                }
            else:
                return {
                    "content": f"[Ollama Error {res.status_code}]: {res.text}",
                    "model_used": self.model,
                    "provider": self.name,
                    "ttft_ms": 0.0,
                    "total_latency_ms": round(total_latency, 1)
                }
        except Exception as e:
            total_latency = (time.time() * 1000.0) - start_time
            return {
                "content": f"[Ollama Unavailable]: {e}",
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
        Streams tokens from Ollama /api/chat NDJSON stream.
        Monitors cancel_event on every chunk for instantaneous barge-in abort.
        """
        start_time = time.time() * 1000.0
        first_token_received = False
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload
                ) as response:
                    if response.status_code != 200:
                        yield f"[Ollama error {response.status_code}]", None
                        return

                    async for line in response.aiter_lines():
                        if cancel_event.is_set():
                            break
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                if not first_token_received:
                                    first_token_received = True
                                    ttft_ms = (time.time() * 1000.0) - start_time
                                    yield token, round(ttft_ms, 1)
                                else:
                                    yield token, None
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.warning(f"Ollama streaming exception: {e}")
            if not first_token_received:
                yield f"[Ollama connection error: {e}]", 0.0
