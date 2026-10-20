"""
Unit and Integration Tests for Voice Cloning & Reference Audio Engine
===================================================================
Tests:
- Reference audio acoustic feature extraction (F0 pitch, RMS energy, duration)
- Voice profile database CRUD & active voice toggle
- Cloned speech synthesis (16kHz WAV format with formant resonance)
- FastAPI Voice endpoints (/api/voices/, /upload, /upload-base64, /preview, /activate)
- WebPhone session active voice speech synthesis integration
"""

import os
import wave
import uuid
import base64
import pytest
import numpy as np
from fastapi.testclient import TestClient

from shadow_voice.api.app import app
from shadow_voice.conversation.cloning import VoiceCloningEngine, VOICES_DIR
from shadow_voice.core.audio import save_pcm_to_wav, SAMPLE_RATE_16K
from shadow_voice.telephony.webphone import WebPhoneSession


@pytest.fixture
def sample_wav_file(tmp_path):
    """Generates a synthetic 220Hz test WAV file representing a human voice sample."""
    wav_path = str(tmp_path / "test_human_voice.wav")
    duration_sec = 2.5
    sample_rate = 16000
    t = np.linspace(0, duration_sec, int(duration_sec * sample_rate), endpoint=False)
    # Fundamental pitch 210Hz with 2nd harmonic
    signal = 0.4 * np.sin(2 * np.pi * 210 * t) + 0.2 * np.sin(2 * np.pi * 420 * t)
    pcm_bytes = (signal * 20000).astype(np.int16).tobytes()
    save_pcm_to_wav(pcm_bytes, wav_path, sample_rate=sample_rate)
    return wav_path


@pytest.fixture
def client():
    return TestClient(app)


class TestVoiceCloningEngine:
    """Tests the core VoiceCloningEngine logic."""

    def test_analyze_audio_file(self, sample_wav_file):
        engine = VoiceCloningEngine()
        metrics = engine.analyze_audio_file(sample_wav_file)

        assert "duration_sec" in metrics
        assert metrics["duration_sec"] >= 2.0
        assert metrics["sample_rate"] == 16000
        assert metrics["channels"] == 1
        assert "rms_energy" in metrics
        assert metrics["rms_energy"] > 0
        assert "estimated_pitch_hz" in metrics
        assert 80.0 <= metrics["estimated_pitch_hz"] <= 350.0

    def test_profile_crud_and_activation(self, sample_wav_file):
        engine = VoiceCloningEngine()
        voice_name = f"Test Rep {uuid.uuid4().hex[:6]}"

        profile = engine.create_voice_profile(
            name=voice_name,
            description="Consultative closer with crisp cadence",
            engine="custom_clone",
            reference_audio_path=sample_wav_file,
            reference_audio_url="/voices/test.wav",
            set_active=True
        )

        assert profile["name"] == voice_name
        assert profile["is_active"] is True

        # Verify active profile is this newly created one
        active = engine.get_active_profile()
        assert active is not None
        assert active["id"] == profile["id"]
        assert active["name"] == voice_name

        # Switch back to jordan_sales
        switched = engine.activate_voice_profile("jordan_sales")
        assert switched is True

        active_again = engine.get_active_profile()
        assert active_again["id"] == "jordan_sales"

        # Delete test profile
        deleted = engine.delete_voice_profile(profile["id"])
        assert deleted is True

    def test_synthesize_cloned_speech(self):
        engine = VoiceCloningEngine()
        profile = {
            "id": "jordan_sales",
            "name": "Jordan (Sales Closer)",
            "estimated_pitch_hz": 200.0
        }
        text = "Hi, this is Jordan calling from Shadow Voice — do you have a quick minute?"
        result = engine.synthesize_cloned_speech(text, profile)

        assert result["success"] is True
        assert result["audio_url"].startswith("/voices/")
        assert os.path.exists(result["filepath"])

        # Validate that the generated file is a readable 16kHz WAV
        with wave.open(result["filepath"], "rb") as wf:
            assert wf.getframerate() == SAMPLE_RATE_16K
            assert wf.getnchannels() == 1
            assert wf.getnframes() > 0


class TestVoiceApiEndpoints:
    """Tests the HTTP API endpoints for voice cloning and synthesis."""

    def test_get_voice_profiles(self, client):
        resp = client.get("/api/voices/")
        assert resp.status_code == 200
        data = resp.json()
        assert "voices" in data
        assert len(data["voices"]) >= 1
        assert "active_voice" in data
        assert "supported_engines" in data

    def test_upload_reference_audio_multipart(self, client, sample_wav_file):
        with open(sample_wav_file, "rb") as f:
            resp = client.post(
                "/api/voices/upload",
                data={
                    "name": "Sarah Enterprise Closer",
                    "description": "Crisp enterprise consultative tone",
                    "engine": "cartesia_sonic",
                    "set_active": "false"
                },
                files={"file": ("sarah_sample.wav", f, "audio/wav")}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["profile"]["name"] == "Sarah Enterprise Closer"
        assert "acoustics" in data
        assert data["acoustics"]["sample_rate"] == 16000

        # Clean up created profile
        voice_id = data["profile"]["id"]
        del_resp = client.delete(f"/api/voices/{voice_id}")
        assert del_resp.status_code == 200

    def test_upload_reference_audio_base64(self, client, sample_wav_file):
        with open(sample_wav_file, "rb") as f:
            b64_audio = base64.b64encode(f.read()).decode("utf-8")

        resp = client.post(
            "/api/voices/upload-base64",
            json={
                "name": "Alex Tech Specialist",
                "audio_base64": b64_audio,
                "filename": "alex.wav",
                "description": "Technical tone",
                "engine": "qwen3_tts",
                "set_active": False
            }
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["profile"]["name"] == "Alex Tech Specialist"

        # Preview speech with this voice
        voice_id = data["profile"]["id"]
        prev_resp = client.post(
            f"/api/voices/{voice_id}/preview",
            json={"text": "Shadow Voice integrates directly with your existing dialers."}
        )
        assert prev_resp.status_code == 200
        prev_data = prev_resp.json()
        assert prev_data["success"] is True
        assert prev_data["audio_url"].startswith("/voices/")

        # Clean up
        client.delete(f"/api/voices/{voice_id}")

    def test_activate_voice(self, client):
        resp = client.post("/api/voices/alex_closer/activate")
        assert resp.status_code == 200

        get_resp = client.get("/api/voices/")
        active = get_resp.json()["active_voice"]
        assert active["id"] == "alex_closer"

        # Restore default active voice
        client.post("/api/voices/jordan_sales/activate")

    def test_webphone_session_generates_cloned_voice_speech(self, client):
        """Verifies WebPhoneSession delivers audio_url matching active voice on call turns."""
        session = WebPhoneSession()
        greeting = session.get_initial_greeting()

        assert "audio_url" in greeting
        assert greeting["audio_url"].startswith("/voices/")
        assert "voice_name" in greeting

        # Step a turn
        turn_res = pytest.run_async = None
        import asyncio
        turn_res = asyncio.run(session.process_user_turn("What dialers do you work with?"))

        assert "audio_url" in turn_res
        assert turn_res["audio_url"].startswith("/voices/")
        assert "voice_name" in turn_res
