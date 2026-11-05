"""
VoiceStudio Local Bridge & Voice Design Client
==============================================
Client adapter connecting Shadow Voice to local VoiceStudio instances (http://localhost:3900).

Enables:
1. High-fidelity local speech synthesis via OmniVoice / CosyVoice / PocketTTS engines.
2. Prompt-based Voice Design (text prompt -> synthetic voice persona without reference audio).
3. Local voice profile discovery and zero-shot voice cloning.
4. Seamless fallback to built-in Shadow Voice synthesis if VoiceStudio is not running.
"""

from __future__ import annotations

import os
import json
import logging
import base64
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

logger = logging.getLogger("shadow_voice.voicestudio_client")

DEFAULT_VOICESTUDIO_URL = "http://localhost:3900"


class VoiceStudioClient:
    """REST client connecting Shadow Voice to local VoiceStudio instances."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or os.getenv("VOICESTUDIO_URL", DEFAULT_VOICESTUDIO_URL)).rstrip("/")
        self.timeout = timeout

    def _request(self, endpoint: str, data: Optional[Dict[str, Any]] = None, method: str = "GET") -> Any:
        url = f"{self.base_url}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
        headers = {"Content-Type": "application/json"}
        req_data = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    return json.loads(resp.read().decode("utf-8"))
                return resp.read()
        except urllib.error.URLError as e:
            logger.debug(f"VoiceStudio connection failed ({url}): {e}")
            raise ConnectionError(f"VoiceStudio not reachable at {self.base_url}: {e}")

    def is_available(self) -> bool:
        """Checks if local VoiceStudio backend is online."""
        try:
            res = self._request("/health")
            return bool(isinstance(res, dict) and (res.get("status") == "ok" or "status" in res))
        except Exception:
            return False

    def list_voices(self) -> List[Dict[str, Any]]:
        """Queries saved voice profiles from VoiceStudio."""
        try:
            res = self._request("/v1/audio/voices")
            if isinstance(res, dict) and "voices" in res:
                return res["voices"]
            if isinstance(res, list):
                return res
            return []
        except Exception as e:
            logger.debug(f"Could not retrieve VoiceStudio voices: {e}")
            return []

    def generate_speech(
        self,
        text: str,
        voice_id: str = "alloy",
        model: str = "tts-1",
        response_format: str = "wav"
    ) -> Optional[bytes]:
        """Generates speech via VoiceStudio OpenAI-compatible endpoint."""
        payload = {
            "model": model,
            "voice": voice_id,
            "input": text,
            "response_format": response_format
        }
        try:
            raw_audio = self._request("/v1/audio/speech", data=payload, method="POST")
            return raw_audio if isinstance(raw_audio, bytes) else None
        except Exception as e:
            logger.warning(f"VoiceStudio speech generation failed: {e}")
            return None

    def design_voice(self, description: str, name: str) -> Dict[str, Any]:
        """
        Voice Design: prompts VoiceStudio to synthesize a new voice profile
        matching a natural language persona description (e.g. '35-year-old female, warm, consultative midwest').
        """
        payload = {
            "name": name,
            "description": description,
            "gender": "neutral",
            "accent": "american",
            "personality": "professional"
        }
        try:
            res = self._request("/api/design", data=payload, method="POST")
            return res if isinstance(res, dict) else {"success": True, "name": name, "voice_id": f"design_{name.lower().replace(' ', '_')}"}
        except Exception as e:
            logger.warning(f"VoiceStudio Voice Design failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "voice_id": f"fallback_{name.lower().replace(' ', '_')}"
            }
