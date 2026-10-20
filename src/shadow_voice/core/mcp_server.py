"""
Shadow Voice MCP Server
=======================
Implements JSON-RPC 2.0 Model Context Protocol (MCP) server for:
- Antigravity
- Claude Desktop
- Cursor IDE
"""

from __future__ import annotations
import sys
import os
import json
import logging
from typing import Dict, Any, List, Optional

from shadow_voice.core.db import init_db
from shadow_voice.brain.brain import BrainManager
from shadow_voice.reach.reader import ReachReader
from shadow_voice.reach.analyzer import ReachAnalyzer
from shadow_voice.cti.vicidial import ViciDialAdapter
from shadow_voice.dialogue.fsm import SalesConversationFSM

logger = logging.getLogger("shadow_voice.mcp")


class ShadowVoiceMCPServer:
    """Stdio and HTTP MCP Server for Shadow Voice."""

    def __init__(self) -> None:
        init_db()
        self.brain = BrainManager()
        self.reader = ReachReader()
        self.analyzer = ReachAnalyzer(self.brain)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "update_instructions",
                "description": "Updates the voice agent's campaign instructions, persona, and opening greeting (enforcing Section 7.1 natural human dialogue with no AI disclosure).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_name": {"type": "string", "description": "Representative name (e.g. Jordan)"},
                        "company_name": {"type": "string", "description": "Company name (e.g. Shadow Voice)"},
                        "opening_greeting": {"type": "string", "description": "Natural opening line (e.g. 'Hi, this is Jordan calling from Shadow Voice — do you have a quick minute?')"},
                        "primary_instructions": {"type": "string", "description": "Directives on what to speak, qualify, and answer."},
                        "tone": {"type": "string", "description": "Tone of voice (e.g. Confident, concise)"}
                    },
                    "required": ["agent_name", "company_name", "opening_greeting", "primary_instructions"]
                }
            },
            {
                "name": "get_brain_knowledge",
                "description": "Queries the agent's Cognitive Brain memory, customer learned questions, and verified story bank receipts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Optional search keyword for receipts or questions"},
                        "status": {"type": "string", "description": "Filter for questions: 'pending_review', 'approved', or 'all'", "default": "all"}
                    }
                }
            },
            {
                "name": "review_customer_question",
                "description": "Approves and defines the authoritative answer for a customer question learned during live calls.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "integer", "description": "ID of learned customer question"},
                        "approved_answer": {"type": "string", "description": "Definitive answer the voice agent will speak when asked this question"}
                    },
                    "required": ["question_id", "approved_answer"]
                }
            },
            {
                "name": "scan_url_with_reach_eyes",
                "description": "Uses Agent Reach Eyes to inspect a company or competitor website, extracts value props and FAQs, and digests them into the Cognitive Brain.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target website URL (e.g. https://vicidial.org)"},
                        "auto_digest": {"type": "boolean", "description": "Whether to automatically commit insights into the brain", "default": True}
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "simulate_call_turn",
                "description": "Tests how the agent responds to a customer prompt based on current instructions and Cognitive Brain knowledge.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "customer_utterance": {"type": "string", "description": "What the customer says"}
                    },
                    "required": ["customer_utterance"]
                }
            }
        ]

    def execute_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Executes tool calls safely."""
        args = arguments or {}

        try:
            if name == "update_instructions":
                self.brain.save_instructions(
                    campaign_id="DEFAULT_SALES_V1",
                    agent_name=args["agent_name"],
                    company_name=args["company_name"],
                    opening_greeting=args["opening_greeting"],
                    primary_instructions=args["primary_instructions"],
                    tone=args.get("tone", "Confident, friendly, consultative")
                )
                return {"status": "success", "message": "Instructions updated successfully."}

            elif name == "get_brain_knowledge":
                query = args.get("query", "")
                status = args.get("status", "all")
                questions = self.brain.get_customer_questions(status=status, query=query, limit=10)
                stories = self.brain.get_story_bank(query=query, limit=5)
                return {
                    "customer_questions": questions,
                    "story_bank_receipts": stories
                }

            elif name == "review_customer_question":
                qid = args["question_id"]
                ans = args["approved_answer"]
                ok = self.brain.update_question_status(qid, status="approved", approved_answer=ans)
                return {"status": "success" if ok else "error", "message": "Question approved."}

            elif name == "scan_url_with_reach_eyes":
                url = args["url"]
                read_res = self.reader.read_url(url)
                if read_res.get("status") == "error":
                    return {"status": "error", "message": read_res.get("message")}

                analysis = self.analyzer.analyze_content(
                    title=read_res.get("title", ""),
                    content=read_res.get("content", ""),
                    url=read_res.get("url", url)
                )

                if args.get("auto_digest", True):
                    digest_res = self.analyzer.digest_into_brain(analysis)
                    return {"status": "success", "analysis": analysis, "digest": digest_res}
                return {"status": "success", "analysis": analysis}

            elif name == "simulate_call_turn":
                text = args["customer_utterance"]
                fsm = SalesConversationFSM(brain_manager=self.brain)
                res = fsm.process_turn(text)
                return {
                    "agent_reply": res.agent_text,
                    "next_stage": res.next_stage.value,
                    "action": res.action,
                    "disposition": res.disposition_code
                }

            return {"status": "error", "message": f"Unknown tool '{name}'"}
        except KeyError as e:
            return {"status": "error", "message": f"Missing required argument: {str(e)}"}
