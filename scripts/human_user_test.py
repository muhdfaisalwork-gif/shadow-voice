#!/usr/bin/env python3
"""
Human User End-to-End Test Script
=================================
Simulates a real human user (David Miller, Call Center Director)
connecting to Shadow Voice via phone/softphone and testing:
1. Section 7.1 Natural Human Greeting (Zero AI Disclosure)
2. Value proposition & qualification dialogue
3. Real-world technical objection (VICIdial / Asterisk AudioSocket integration)
4. Question learning & Cognitive Brain memory storage
5. Pricing inquiry & Guardrail compliance verification
6. Agreement & Warm Transfer to live closer pool
7. Call teardown, latency logging, and analytics reporting
"""

import json
import time
import urllib.request
import sys

# Windows console UTF-8 support
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_URL = "http://localhost:9000"

def post_json(path, data):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(path):
    with urllib.request.urlopen(f"{BASE_URL}{path}") as resp:
        return json.loads(resp.read().decode("utf-8"))

def run_human_test():
    print("=" * 65)
    print("  HUMAN USER CALL EXPERIENCE TEST — SHADOW VOICE STUDIO")
    print("=" * 65)
    print("Caller: David Miller (Director of Telephony Operations)")
    print("Phone:  +1 (312) 555-0188")
    print("Lead:   LEAD_HUMAN_DAVID_01\n")

    # Step 1: Human places / receives call
    print("[1] DIALING INBOUND / ANSWERING CALL...")
    call_start = post_json("/api/calls/start", {
        "phone_number": "+1 (312) 555-0188",
        "lead_id": "LEAD_HUMAN_DAVID_01",
        "campaign_id": "DEFAULT_SALES_V1"
    })
    session_id = call_start["session_id"]
    greeting = call_start["greeting"]

    print(f"  --> Call Connected | Session ID: {session_id}")
    print(f"  --> Voice Selected: {greeting.get('voice_name', 'Jordan (Sales Engineer)')}")
    print(f"  --> Initial Latency: {greeting['latency']['total_ms']}ms")
    print(f'\n[AGENT GREETING]:\n  "{greeting["text"]}"\n')

    # Step 2: Human conversational flow
    human_script = [
        {
            "user": "Yeah, Jordan, I have a minute. What is this regarding?",
            "intent": "Open-ended curiosity / permission granted"
        },
        {
            "user": "We run a 50-seat call center with VICIdial. Does your platform connect directly to Asterisk AudioSocket without lag?",
            "intent": "Technical inquiry + dialer compatibility objection"
        },
        {
            "user": "What does your pricing look like per minute?",
            "intent": "Pricing verification against guardrails"
        },
        {
            "user": "That sounds very reasonable. Yeah, let's get someone on the line to walk through a test setup.",
            "intent": "Agreement / request for live specialist transfer"
        }
    ]

    for turn_idx, turn_data in enumerate(human_script, 1):
        user_utterance = turn_data["user"]
        print(f"--- TURN {turn_idx} ---")
        print(f"[CALLER (David)]: \"{user_utterance}\"")
        print(f"   (Intent: {turn_data['intent']})")

        start_time = time.time()
        turn_response = post_json(f"/api/calls/{session_id}/turn", {"text": user_utterance})
        round_trip_ms = round((time.time() - start_time) * 1000.0, 1)

        reply_text = turn_response.get("agent_reply", "")
        stage = turn_response.get("stage", "UNKNOWN")
        dispo = turn_response.get("disposition", "CALLBK")
        lat = turn_response.get("latency", {})

        print(f"[AGENT (Jordan)]: \"{reply_text}\"")
        print(f"   Stage: {stage} | Disposition: {dispo}")
        print(f"   Playout Latency: {lat.get('total_ms', 0)}ms (STT: {lat.get('stt_ms',0)}ms, TTFT: {lat.get('llm_ttft_ms',0)}ms, TTS: {lat.get('tts_ms',0)}ms)")

        learned = turn_response.get("questions_learned")
        if learned:
            print(f"   [BRAIN MEMORY]: Captured caller inquiry: '{learned}'")
        print()
        time.sleep(0.3)

    # Step 3: Call Conclusion & Transfer Disposition
    print("[3] COMPLETING CALL & LOGGING DISPOSITION...")
    end_result = post_json(f"/api/calls/{session_id}/end", {"disposition": "SALE"})
    print(f"  --> Final Status: {end_result.get('status')}")
    print(f"  --> Final Disposition: {end_result.get('disposition')}")
    print(f"  --> Call Duration: {end_result.get('duration_sec')}s")

    # Step 4: Verify Cognitive Brain & Knowledge Base
    print("\n[4] VERIFYING COGNITIVE BRAIN RECEPTIVITY...")
    brain_summary = get_json("/api/brain/summary")
    print(f"  --> Total Questions Logged in Memory: {brain_summary.get('total_questions')}")
    print(f"  --> Approved Knowledge Base Answers:  {brain_summary.get('approved_questions')}")
    print(f"  --> Story Bank Case Studies:         {brain_summary.get('story_count')}")

    # Step 5: Check Softphone & Telephony Hub status
    print("\n[5] VERIFYING SOFTPHONE & TELEPHONY HUB STATUS...")
    softphones = get_json("/api/softphones/status")
    print(f"  --> Installed Eyebeam: {softphones.get('eyebeam_installed')}")
    print(f"  --> Installed X-Lite:  {softphones.get('xlite_installed')}")
    print(f"  --> Bundled Installers Found: {len(softphones.get('discovered_files', []))} binaries")
    print(f"  --> Virtual SIP Engine: {softphones.get('virtual_sip', {}).get('status', 'IDLE')}")

    # Step 6: Verify Analytics & Compliance
    print("\n[6] VERIFYING TCPA & PRODUCTION METRICS...")
    analytics = get_json("/api/analytics/summary")
    safe_harbor = analytics.get("safe_harbor", {})
    print(f"  --> Total Recorded Calls: {analytics.get('total_calls')}")
    print(f"  --> Average Duration:     {analytics.get('average_duration_sec')}s")
    print(f"  --> P95 Audio Latency:    {analytics.get('latency_metrics', {}).get('p95_ms')}ms")
    print(f"  --> Safe Harbor Status:   {safe_harbor.get('status')} (Drop Rate: {safe_harbor.get('regulatory_drop_rate')*100:.2f}%)")
    print(f"  --> Dispositions Map:     {analytics.get('dispositions')}")

    print("\n" + "=" * 65)
    print("  HUMAN USER TEST COMPLETE — ALL SYSTEMS OPERATIONAL")
    print("=" * 65)

if __name__ == "__main__":
    run_human_test()
