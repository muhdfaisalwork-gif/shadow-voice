"""
Asterisk AudioSocket Transport Adapter
======================================
Implements native Asterisk AudioSocket TCP protocol:
- Initial 16-byte UUID connection handshake
- Type 0x10: Audio payload (16-bit linear PCM mono)
- Type 0x01: Hangup / Close
- Type 0x00: Keep-Alive
- Type 0x02: Error
- Explicit 8kHz / 16kHz boundary handling
- Clean session lifecycle, socket timeouts, graceful hangup
"""

from __future__ import annotations
import asyncio
import logging
import struct
import uuid
from typing import Dict, Optional, Callable, Awaitable
from shadow_voice.core.audio import (
    AudioFrame,
    SAMPLE_RATE_8K,
    SAMPLE_RATE_16K,
    FRAME_BYTES_8K,
    FRAME_BYTES_16K,
)
from shadow_voice.telephony.metadata import CallMetadata
from shadow_voice.telephony.sip_rtp import BaseTransportAdapter
from shadow_voice.telephony.resampler import GatewayResampler

logger = logging.getLogger("shadow_voice.audiosocket")

# AudioSocket Message Types
TYPE_KEEP_ALIVE = 0x00
TYPE_HANGUP = 0x01
TYPE_ERROR = 0x02
TYPE_AUDIO = 0x10


class AudioSocketConnection:
    """Manages an active Asterisk AudioSocket TCP connection."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        session_id: str,
        pstn_sample_rate: int = SAMPLE_RATE_8K
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.session_id = session_id
        self.pstn_sample_rate = pstn_sample_rate
        self.is_closed = False
        self._seq = 0
        self.audio_buffer = bytearray()

    async def read_message(self) -> Optional[tuple[int, bytes]]:
        """Reads a framed AudioSocket message: (msg_type, payload)."""
        try:
            # Read 3-byte header: 1 byte type, 2 bytes big-endian length
            header = await self.reader.readexactly(3)
            msg_type = header[0]
            payload_len = struct.unpack(">H", header[1:3])[0]

            payload = b""
            if payload_len > 0:
                payload = await self.reader.readexactly(payload_len)

            return msg_type, payload
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            self.is_closed = True
            return None
        except Exception as e:
            logger.error(f"[AudioSocket] Session {self.session_id} read error: {e}")
            self.is_closed = True
            return None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Sends audio payload (0x10) to Asterisk."""
        if self.is_closed or self.writer.is_closing():
            return
        header = struct.pack(">BH", TYPE_AUDIO, len(pcm_bytes))
        try:
            self.writer.write(header + pcm_bytes)
            await self.writer.drain()
        except Exception as e:
            logger.warning(f"[AudioSocket] Session {self.session_id} send audio failed: {e}")
            self.is_closed = True

    async def send_hangup(self) -> None:
        """Sends clean hangup (0x01) to Asterisk and closes stream."""
        if self.is_closed:
            return
        try:
            self.writer.write(struct.pack(">BH", TYPE_HANGUP, 0))
            await self.writer.drain()
        except Exception:
            pass
        finally:
            self.is_closed = True
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


class AudioSocketAdapter(BaseTransportAdapter):
    """
    Asterisk AudioSocket TCP server listening for incoming calls from Asterisk AudioSocket dialplan.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9092,
        pstn_sample_rate: int = SAMPLE_RATE_8K
    ) -> None:
        self.host = host
        self.port = port
        self.pstn_sample_rate = pstn_sample_rate
        self.server: Optional[asyncio.Server] = None
        self.connections: Dict[str, AudioSocketConnection] = {}
        self.metadata_store: Dict[str, CallMetadata] = {}

        self._ingress_handler: Optional[Callable[[str, AudioFrame, CallMetadata], Awaitable[None]]] = None
        self._session_end_handler: Optional[Callable[[str, str], Awaitable[None]]] = None

    def set_ingress_handler(
        self,
        handler: Callable[[str, AudioFrame, CallMetadata], Awaitable[None]]
    ) -> None:
        self._ingress_handler = handler

    def set_session_end_handler(
        self,
        handler: Callable[[str, str], Awaitable[None]]
    ) -> None:
        self._session_end_handler = handler

    async def start(self) -> None:
        """Binds and starts the TCP AudioSocket server."""
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        logger.info(f"[AudioSocket] Server listening on {self.host}:{self.port}")

    async def stop(self) -> None:
        """Shuts down server and closes active connections cleanly."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        for session_id, conn in list(self.connections.items()):
            await conn.send_hangup()
        self.connections.clear()
        logger.info("[AudioSocket] Server stopped.")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handles a new inbound TCP connection from Asterisk."""
        session_uuid: Optional[str] = None
        try:
            # Handshake: First 16 bytes is UUID in binary or ASCII format
            uuid_bytes = await reader.readexactly(16)
            try:
                # Standard Asterisk AudioSocket provides 16-byte raw UUID
                session_uuid = str(uuid.UUID(bytes=uuid_bytes))
            except Exception:
                session_uuid = uuid_bytes.decode("utf-8", errors="ignore").strip("\x00")
                if not session_uuid:
                    session_uuid = str(uuid.uuid4())

            logger.info(f"[AudioSocket] Accepted connection for session UUID: {session_uuid}")
            conn = AudioSocketConnection(reader, writer, session_uuid, self.pstn_sample_rate)
            self.connections[session_uuid] = conn

            metadata = self.metadata_store.get(
                session_uuid,
                CallMetadata(session_id=session_uuid, dialer_type="asterisk_audiosocket")
            )

            # Process inbound messages loop
            while not conn.is_closed:
                msg = await conn.read_message()
                if msg is None:
                    break
                msg_type, payload = msg

                if msg_type == TYPE_AUDIO:
                    # Inbound audio frame from caller - buffer and chunk to exact 20ms frames
                    conn.audio_buffer.extend(payload)
                    expected_bytes = FRAME_BYTES_8K if self.pstn_sample_rate == SAMPLE_RATE_8K else FRAME_BYTES_16K
                    while len(conn.audio_buffer) >= expected_bytes:
                        chunk = bytes(conn.audio_buffer[:expected_bytes])
                        del conn.audio_buffer[:expected_bytes]
                        raw_frame = AudioFrame(
                            data=chunk,
                            sample_rate=self.pstn_sample_rate,
                            sequence_num=conn._seq,
                            timestamp_ms=conn._seq * 20.0
                        )
                        conn._seq += 1

                        # Boundary conversion to 16kHz canonical internal rate
                        frame_16k = GatewayResampler.ingress_pstn_to_internal(raw_frame)

                        if self._ingress_handler:
                            await self._ingress_handler(session_uuid, frame_16k, metadata)

                elif msg_type == TYPE_HANGUP:
                    logger.info(f"[AudioSocket] Asterisk sent hangup for session: {session_uuid}")
                    break
                elif msg_type == TYPE_KEEP_ALIVE:
                    # Keepalive ping - acknowledge if needed
                    pass
                elif msg_type == TYPE_ERROR:
                    logger.warning(f"[AudioSocket] Received error frame from Asterisk on session: {session_uuid}")

        except Exception as e:
            logger.error(f"[AudioSocket] Client handler error: {e}")
        finally:
            if session_uuid and session_uuid in self.connections:
                conn = self.connections.pop(session_uuid)
                await conn.send_hangup()

            if session_uuid and self._session_end_handler:
                try:
                    await self._session_end_handler(session_uuid, "HANGUP_OR_DISCONNECT")
                except Exception as err:
                    logger.error(f"[AudioSocket] Session end handler error: {err}")

    async def send_audio_frame(self, session_id: str, frame: AudioFrame) -> None:
        """
        Sends 16kHz internal frame to Asterisk, automatically resampling to
        PSTN sample rate (8kHz) at the gateway boundary.
        """
        conn = self.connections.get(session_id)
        if not conn or conn.is_closed:
            return

        pstn_frame = GatewayResampler.egress_internal_to_pstn(frame)
        await conn.send_audio(pstn_frame.data)

    async def hangup_call(self, session_id: str, reason: str = "NORMAL_CLEARING") -> None:
        """Hangs up the call cleanly via AudioSocket hangup frame."""
        conn = self.connections.pop(session_id, None)
        if conn:
            logger.info(f"[AudioSocket] Hanging up session {session_id} ({reason})")
            await conn.send_hangup()
