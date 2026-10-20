"""
Mock Telephony & AudioSocket Test Harness
==========================================
Simulates an Asterisk AudioSocket client connecting to Shadow Voice Gateway:
- Transmits initial 16-byte UUID
- Streams 8 kHz 20ms PCM audio frames (320 bytes)
- Receives egress audio and validates timing and byte integrity
- Simulates caller speech, pauses, and hangup
"""

from __future__ import annotations
import asyncio
import logging
import struct
import uuid
from typing import List, Optional
import numpy as np

logger = logging.getLogger("shadow_voice.mock_telephony")


class MockAudioSocketClient:
    """Simulates an Asterisk channel dialing in over AudioSocket TCP."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9092) -> None:
        self.host = host
        self.port = port
        self.session_uuid = str(uuid.uuid4())
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.received_audio_frames: List[bytes] = []
        self.is_connected = False

    async def connect(self) -> None:
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        # Send 16-byte UUID handshake
        uuid_bytes = uuid.UUID(self.session_uuid).bytes
        self.writer.write(uuid_bytes)
        await self.writer.drain()
        self.is_connected = True
        logger.info(f"[MOCK CLIENT] Connected to AudioSocket server with UUID {self.session_uuid}")

    async def send_8k_frame(self, pcm_320_bytes: bytes) -> None:
        """Sends an 8kHz 20ms audio frame (0x10) to the gateway."""
        if not self.writer or self.writer.is_closing():
            return
        header = struct.pack(">BH", 0x10, len(pcm_320_bytes))
        self.writer.write(header + pcm_320_bytes)
        await self.writer.drain()

    async def send_hangup(self) -> None:
        """Sends clean hangup (0x01) to the gateway."""
        if not self.writer or self.writer.is_closing():
            return
        self.writer.write(struct.pack(">BH", 0x01, 0))
        await self.writer.drain()
        self.writer.close()
        await self.writer.wait_closed()
        self.is_connected = False

    async def receive_frames_loop(self, max_frames: int = 50) -> None:
        """Listens for returned egress audio frames from the gateway."""
        count = 0
        while self.is_connected and count < max_frames and self.reader:
            try:
                header = await self.reader.readexactly(3)
                msg_type, length = header[0], struct.unpack(">H", header[1:3])[0]
                payload = b""
                if length > 0:
                    payload = await self.reader.readexactly(length)
                if msg_type == 0x10:
                    self.received_audio_frames.append(payload)
                    count += 1
                elif msg_type == 0x01:
                    logger.info("[MOCK CLIENT] Received hangup from gateway.")
                    break
            except Exception:
                break
