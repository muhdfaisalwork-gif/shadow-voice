"""
Agent Reach Eyes — URL Reader
==============================
High-speed web content reader:
- Backend 1: Jina Reader (https://r.jina.ai/{url}) for clean LLM-optimized Markdown.
- Backend 2: Standard Python urllib/aiohttp fallback for direct HTML extraction.
"""

from __future__ import annotations
import logging
import urllib.request
import urllib.parse
import re
from typing import Dict, Any, Optional

logger = logging.getLogger("shadow_voice.reach.reader")


class ReachReader:
    """Reads and extracts clean textual markdown from any public website URL."""

    def __init__(self, timeout_sec: int = 10) -> None:
        self.timeout = timeout_sec
        self.jina_prefix = "https://r.jina.ai/"

    def read_url(self, url: str) -> Dict[str, Any]:
        """Reads target webpage, trying Jina Reader first, falling back to direct HTTP."""
        raw_url = (url or "").strip()
        if not raw_url:
            return {
                "status": "error",
                "message": "A valid target URL is required.",
                "url": url
            }

        parsed_init = urllib.parse.urlparse(raw_url)
        if parsed_init.scheme and parsed_init.scheme not in ("http", "https"):
            return {
                "status": "error",
                "message": "Only HTTP and HTTPS web URLs are supported.",
                "url": url
            }

        if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            raw_url = f"https://{raw_url}"

        parsed = urllib.parse.urlparse(raw_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {
                "status": "error",
                "message": "Only HTTP and HTTPS web URLs are supported.",
                "url": url
            }

        # 1. High-speed Jina Reader Markdown
        try:
            jina_target = f"{self.jina_prefix}{raw_url}"
            req = urllib.request.Request(
                jina_target,
                headers={
                    "User-Agent": "ShadowVoiceReachEyes/1.0",
                    "Accept": "text/markdown, text/plain"
                }
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                if content and len(content.strip()) > 80:
                    lines = [line.strip() for line in content.split("\n") if line.strip()]
                    title = lines[0].replace("#", "").strip() if lines else "Extracted Page"
                    return {
                        "status": "success",
                        "backend": "jina_reader",
                        "url": raw_url,
                        "title": title[:140],
                        "content": content[:8000],
                        "summary": content[:400] + "..." if len(content) > 400 else content
                    }
        except Exception as e:
            logger.debug(f"Jina reader fallback triggered: {e}")

        # 2. Direct HTTP Fetch Fallback
        try:
            req = urllib.request.Request(
                raw_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShadowVoice/1.0"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                # Strip scripts and styles
                clean = re.sub(r"<(script|style).*?>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
                # Strip HTML tags
                text = re.sub(r"<[^>]+>", " ", clean)
                # Collapse whitespace
                text = re.sub(r"\s+", " ", text).strip()
                title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                title = " ".join(title_match.group(1).split()).strip() if title_match else "Website Content"

                return {
                    "status": "success",
                    "backend": "direct_http",
                    "url": raw_url,
                    "title": title[:140],
                    "content": text[:8000],
                    "summary": text[:400] + "..." if len(text) > 400 else text
                }
        except Exception as err:
            logger.error(f"Failed to fetch {raw_url}: {err}")
            return {
                "status": "error",
                "message": f"Unable to reach {raw_url}: {str(err)}",
                "url": raw_url
            }
