"""
Structured Logging & Session Tracing
====================================
Provides contextual JSON / structured logging across all components:
session_id, lead_id, campaign_id, prompt_version, latency markers.
"""

from __future__ import annotations
import json
import logging
import sys
import time
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Context variables for per-async-task session tracing
current_session_id: ContextVar[Optional[str]] = ContextVar("current_session_id", default=None)
current_lead_id: ContextVar[Optional[str]] = ContextVar("current_lead_id", default=None)
current_campaign_id: ContextVar[Optional[str]] = ContextVar("current_campaign_id", default=None)
current_trace_id: ContextVar[Optional[str]] = ContextVar("current_trace_id", default=None)


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured JSON lines for production log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "session_id": current_session_id.get(),
            "lead_id": current_lead_id.get(),
            "campaign_id": current_campaign_id.get(),
            "trace_id": current_trace_id.get(),
        }

        # Include custom extra attributes if passed
        for key in ("component", "latency_ms", "stt_latency_ms", "ttft_ms", "tts_latency_ms", "fsm_state", "guardrail_flag"):
            if hasattr(record, key):
                log_obj[key] = getattr(record, key)

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def configure_logging(level: int = logging.INFO, json_format: bool = False) -> None:
    """Configures root logger with clean terminal or structured JSON output."""
    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        fmt = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers to avoid duplicates
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)
