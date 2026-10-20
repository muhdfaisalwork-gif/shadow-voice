"""
Shadow Voice Studio Server Launcher
===================================
Launches the Shadow Voice Web Studio and API Server on port 9000.
"""

import sys
import os
import argparse
import uvicorn
from dotenv import load_dotenv

load_dotenv()

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from shadow_voice.core.db import init_db

if __name__ == "__main__":
    # Ensure UTF-8 output on Windows terminal
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Shadow Voice Autonomous Studio & Telephony Gateway")
    parser.add_argument("-p", "--port", type=int, default=int(os.getenv("PORT", "9000")), help="HTTP/Web Studio port (default: 9000)")
    parser.add_argument("-H", "--host", type=str, default=os.getenv("HOST", "0.0.0.0"), help="Host address to bind (default: 0.0.0.0)")
    args = parser.parse_args()

    init_db()
    port = args.port
    host = args.host

    print("\n" + "=" * 65)
    print("  [*] SHADOW VOICE - AUTONOMOUS STUDIO & COGNITIVE BRAIN")
    print("=" * 65)
    print(f"  * Gateway & Studio URL:   http://localhost:{port}")
    print(f"  * Dialer CTI Hub:         VICIdial, Asterisk AudioSocket, WebPhone")
    print(f"  * Cognitive Brain:        Active & Evolving (SQLite WAL)")
    print(f"  * Natural Opening:        Section 7.1 Enforced (0 AI disclosures)")
    print("=" * 65 + "\n")

    uvicorn.run(
        "shadow_voice.api.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
