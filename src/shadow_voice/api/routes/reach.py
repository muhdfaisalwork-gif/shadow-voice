"""
Agent Reach Eyes API Router
============================
Handles:
- Scanning web URLs (competitors, prospects, landing pages)
- Extracting business intelligence & candidate Q&As
- One-click ingestion into Cognitive Brain memory
"""

from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shadow_voice.reach.reader import ReachReader
from shadow_voice.reach.analyzer import ReachAnalyzer

logger = logging.getLogger("shadow_voice.api.reach")
router = APIRouter(prefix="/api/reach", tags=["Agent Reach Eyes"])

reader = ReachReader()
analyzer = ReachAnalyzer()


class ScanUrlRequest(BaseModel):
    url: str


class DigestRequest(BaseModel):
    analysis: Dict[str, Any]


@router.post("/scan")
def scan_url(req: ScanUrlRequest) -> Dict[str, Any]:
    """Scans target webpage using ReachReader and extracts domain intelligence."""
    read_res = reader.read_url(req.url)
    if read_res.get("status") == "error":
        raise HTTPException(status_code=400, detail=read_res.get("message", "Failed to scan URL"))

    analysis = analyzer.analyze_content(
        title=read_res.get("title", ""),
        content=read_res.get("content", ""),
        url=read_res.get("url", req.url)
    )

    return {
        "status": "success",
        "backend": read_res.get("backend"),
        "analysis": analysis
    }


@router.post("/digest")
def digest_into_brain(req: DigestRequest) -> Dict[str, Any]:
    """Commits extracted website intelligence directly into Cognitive Brain memory."""
    res = analyzer.digest_into_brain(req.analysis)
    return res
