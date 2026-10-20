"""
Shadow Voice Studio Server
==========================
FastAPI Web Studio server for Shadow Voice:
- Live Voice Console & Softphone WebSocket
- Instruction Studio with Section 7.1 Natural Quality enforcement
- Evolving Cognitive Brain with Customer Question Learning
- Pluggable CTI Hub (VICIdial, Asterisk, CPaaS, WebPhone)
- Agent Reach Eyes (URL Scanner & Digest)
- Analytics & Compliance Monitors
"""

from __future__ import annotations
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from shadow_voice.core.db import init_db
from shadow_voice.api.routes import (
    calls,
    instructions,
    brain,
    dialers,
    reach,
    analytics,
    settings,
    voices,
    softphones
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure SQLite database and default seeds are ready
    init_db()
    yield
    # Shutdown cleanups if any


app = FastAPI(
    title="Shadow Voice — Autonomous Studio & Cognitive Brain",
    description="Dialer-Agnostic Low-Latency AI Voice Agent Platform with Evolving Knowledge & Agent Reach Eyes",
    version="2.0.0",
    lifespan=lifespan
)

# Enable CORS for local testing & dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(calls.router)
app.include_router(instructions.router)
app.include_router(brain.router)
app.include_router(dialers.router)
app.include_router(reach.router)
app.include_router(analytics.router)
app.include_router(settings.router)
app.include_router(voices.router)
app.include_router(softphones.router)

@app.get("/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "Shadow Voice Studio", "version": "2.0.0"}

from fastapi.responses import Response

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)

# Prometheus Metrics Endpoint
from fastapi.responses import PlainTextResponse
from shadow_voice.monitoring.metrics import ShadowVoiceMetrics
metrics_collector = ShadowVoiceMetrics()

@app.get("/metrics", response_class=PlainTextResponse, tags=["Monitoring"])
def get_prometheus_metrics():
    """Prometheus metrics exporter endpoint."""
    return metrics_collector.export_prometheus_text()

# Mount recordings & voices storage
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))
RECORDINGS_DIR = os.path.join(ROOT_DIR, "storage", "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)
app.mount("/recordings", StaticFiles(directory=RECORDINGS_DIR), name="recordings")

VOICES_DIR = os.path.join(ROOT_DIR, "storage", "voices")
os.makedirs(VOICES_DIR, exist_ok=True)
app.mount("/voices", StaticFiles(directory=VOICES_DIR), name="voices")

# Mount static frontend (dual mount: /static and root /)
STATIC_DIR = os.path.join(BASE_DIR, "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_assets")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static_root")

