"""
Shadow Voice MCP Stdio Runner
=============================
Starts the MCP Server on standard input/output for Claude Desktop, Cursor, and Antigravity.
"""

import sys
import os
import json

# Ensure src is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from shadow_voice.core.mcp_server import ShadowVoiceMCPServer

def main():
    server = ShadowVoiceMCPServer()

    while True:
        msg_id = None
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line_str = line.strip()
            if not line_str:
                continue

            req = json.loads(line_str)
            method = req.get("method")
            msg_id = req.get("id")

            # Ignore notifications (no id)
            if msg_id is None and not method == "initialize":
                continue

            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "shadow-voice-mcp",
                            "version": "2.0.0"
                        }
                    }
                }
            elif method == "tools/list":
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": server.get_tool_definitions()}
                }
            elif method == "tools/call":
                params = req.get("params", {})
                name = params.get("name")
                args = params.get("arguments", {})
                out = server.execute_tool(name, args)
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]}
                }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {}
                }

            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
        except Exception as e:
            err = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": str(e)}
            }
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
