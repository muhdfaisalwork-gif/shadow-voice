"""
Voice Cloning & Reference Audio API Router
==========================================
Handles:
- Uploading reference audio samples (WAV / MP3) of human reps
- Voice acoustic analysis and timbre profile extraction
- Voice profile switching (Cartesia, ElevenLabs, Qwen3-TTS)
- Voice synthesis preview and playback
"""

from __future__ import annotations
import os
import shutil
import uuid
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from shadow_voice.conversation.cloning import VoiceCloningEngine, VOICES_DIR

import base64

logger = logging.getLogger("shadow_voice.api.voices")
router = APIRouter(prefix="/api/voices", tags=["Voice Cloning & Reference Audio"])

cloning_engine = VoiceCloningEngine()


class PreviewVoiceRequest(BaseModel):
    text: str = "Hi, this is Jordan calling from Shadow Voice — do you have a quick minute?"


class Base64VoiceUploadRequest(BaseModel):
    name: str
    audio_base64: str
    filename: Optional[str] = "custom_voice.wav"
    description: Optional[str] = ""
    engine: Optional[str] = "cartesia_sonic"
    set_active: Optional[bool] = True


@router.get("/")
def get_voice_profiles() -> Dict[str, Any]:
    """Retrieves all registered cloned voices and current active voice."""
    profiles = cloning_engine.list_voice_profiles()
    active = cloning_engine.get_active_profile()
    return {
        "voices": profiles,
        "active_voice": active,
        "supported_engines": ["cartesia_sonic", "elevenlabs", "qwen3_tts", "custom_clone"]
    }


@router.post("/upload")
async def upload_reference_audio(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    engine: str = Form("cartesia_sonic"),
    set_active: bool = Form(True)
) -> Dict[str, Any]:
    """
    Uploads a human reference audio sample (.wav / .mp3) to clone their voice.
    Extracts acoustic pitch and timbre metrics.
    """
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Voice name cannot be empty.")

    ext = os.path.splitext(file.filename)[1].lower() or ".wav"
    if ext not in [".wav", ".mp3", ".ogg", ".m4a"]:
        raise HTTPException(status_code=400, detail="Only audio files (.wav, .mp3, .ogg, .m4a) are supported.")

    file_id = f"ref_{uuid.uuid4().hex[:8]}"
    saved_filename = f"{file_id}{ext}"
    saved_path = os.path.join(VOICES_DIR, saved_filename)

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    if not os.path.exists(saved_path) or os.path.getsize(saved_path) == 0:
        if os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    # Analyze audio acoustics
    analysis = cloning_engine.analyze_audio_file(saved_path)
    pitch_hz = float(analysis.get("estimated_pitch_hz") or 195.0)
    audio_url = f"/voices/{saved_filename}"

    # Register voice profile
    profile = cloning_engine.create_voice_profile(
        name=clean_name,
        description=description.strip() or f"Cloned voice from {file.filename} (Pitch: {pitch_hz}Hz)",
        engine=engine,
        reference_audio_path=saved_path,
        reference_audio_url=audio_url,
        voice_id=file_id,
        estimated_pitch_hz=pitch_hz,
        set_active=set_active
    )

    return {
        "success": True,
        "message": f"Successfully uploaded and cloned '{clean_name}'!",
        "profile": profile,
        "acoustics": analysis
    }


@router.post("/upload-base64")
def upload_reference_audio_base64(req: Base64VoiceUploadRequest) -> Dict[str, Any]:
    """Uploads base64-encoded reference audio (.wav / .mp3) to clone a voice."""
    clean_name = (req.name or "").strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Voice name cannot be empty.")

    file_id = f"ref_{uuid.uuid4().hex[:8]}"
    ext = os.path.splitext(req.filename or "")[1].lower() or ".wav"
    saved_filename = f"{file_id}{ext}"
    saved_path = os.path.join(VOICES_DIR, saved_filename)

    if not req.audio_base64 or not str(req.audio_base64).strip():
        raise HTTPException(status_code=400, detail="audio_base64 cannot be empty.")

    b64_str = req.audio_base64.strip()
    if "," in b64_str:
        b64_str = b64_str.split(",", 1)[1].strip()

    try:
        raw_bytes = base64.b64decode(b64_str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")

    if not raw_bytes or len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Audio data cannot be empty.")

    with open(saved_path, "wb") as f:
        f.write(raw_bytes)

    analysis = cloning_engine.analyze_audio_file(saved_path)
    pitch_hz = float(analysis.get("estimated_pitch_hz") or 195.0)
    audio_url = f"/voices/{saved_filename}"

    profile = cloning_engine.create_voice_profile(
        name=clean_name,
        description=req.description.strip() or f"Cloned voice from {req.filename} (Pitch: {pitch_hz}Hz)",
        engine=req.engine or "cartesia_sonic",
        reference_audio_path=saved_path,
        reference_audio_url=audio_url,
        voice_id=file_id,
        estimated_pitch_hz=pitch_hz,
        set_active=req.set_active if req.set_active is not None else True
    )

    return {
        "success": True,
        "message": f"Successfully uploaded and cloned '{clean_name}'!",
        "profile": profile,
        "acoustics": analysis
    }


@router.post("/{voice_id}/activate")
def activate_voice(voice_id: str) -> Dict[str, Any]:
    """Sets the chosen voice profile as the active voice for phone calls."""
    success = cloning_engine.activate_voice_profile(voice_id)
    if not success:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    return {"success": True, "message": f"Voice profile '{voice_id}' is now active."}


@router.post("/{voice_id}/preview")
def preview_voice(voice_id: str, req: PreviewVoiceRequest) -> Dict[str, Any]:
    """Synthesizes text in the chosen voice and returns a playable audio URL."""
    profiles = cloning_engine.list_voice_profiles()
    target = next((p for p in profiles if p["id"] == voice_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Voice profile not found")

    result = cloning_engine.synthesize_cloned_speech(
        text=req.text,
        voice_profile=target
    )
    return result


@router.delete("/{voice_id}")
def delete_voice(voice_id: str) -> Dict[str, Any]:
    """Deletes a custom cloned voice profile."""
    clean_id = (voice_id or "").strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="Voice ID cannot be empty.")
    if clean_id in ("jordan_sales", "alex_closer", "taylor_support"):
        raise HTTPException(status_code=400, detail="Cannot delete default built-in voice profile.")

    success = cloning_engine.delete_voice_profile(clean_id)
    if not success:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    return {"success": True, "message": "Voice profile deleted."}
