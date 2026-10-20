# Shadow Voice — AI Voice Agent Platform (Production v2)

[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-blue.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-brightgreen.svg)](pyproject.toml)
[![Architecture: Dialer--Agnostic](https://img.shields.io/badge/Architecture-Dialer--Agnostic-orange.svg)](#core-architecture-principles)
[![Target Latency: <650ms P95](https://img.shields.io/badge/Target%20Latency-%3C650ms%20P95-success.svg)](#latency-targets)
[![CTI Target: VICIdial](https://img.shields.io/badge/CTI-VICIdial-purple.svg)](#cti-integration)

Shadow Voice is a dialer-agnostic, low-latency AI Voice Agent platform designed for high-volume outbound CSR and sales environments. Built on a modular telephony gateway boundary and streaming AI pipeline (Deepgram Nova-3 / Flux STT, streaming LLM, and Qwen3-TTS), it achieves **sub-650ms speech-end-to-first-audio playout latency** while maintaining strict TCPA/TSR regulatory compliance.

---

## 0. Core Architecture Principles

1. **Telephony Transport Decoupled from Conversational Logic**: SIP/RTP and Asterisk AudioSocket feed a unified internal session core.
2. **Dialer-Agnostic CTI**: VICIdial is the primary concrete CTI implementation behind the `BaseDialerAdapter` interface, never hard-coded.
3. **Canonical Audio Contract**:
   - PCM signed linear, 16-bit (little-endian int16), mono (1 channel)
   - Canonical internal sample rate: **16 kHz**
   - Processing / egress cadence: **20 ms** (640 bytes per frame internal; 320 bytes @ 8 kHz PSTN boundary)
4. **Resampling at Gateway Boundary**: 8 kHz PSTN audio is converted to 16 kHz upon ingress and decimated back to 8 kHz on egress.
5. **Dual Buffering Layers**: Separate bounded ingress jitter buffer and monotonic paced egress playout buffer.
6. **Sub-Millisecond Barge-In**: Instantaneous playout buffer flush (<5ms) and concurrent cancellation of active LLM and TTS generation tasks.
7. **Runtime Output Guardrail**: Classification filter between LLM output and TTS input; flags unapproved pricing, guarantees, or legal claims, substitutes a safe fallback line, and routes to live human transfer.
8. **System-Wide Kill Switch**: Reachable by PM, QA/Compliance Engineer, or automated spend/regulatory monitors to immediately halt new outbound dials while gracefully winding down active calls.
9. **Natural Language Standard (Section 7.1)**: Calls begin naturally as human person-to-person business conversations (`"Hi, this is [Name] calling from [Company] — do you have a quick minute?"`) without robotic AI disclosures in the introduction.
10. **Phase 4.5 Canary Rollout**: Staged production deployment (1 Line -> 3 Lines -> 5 Lines full scale) before live volume cutover.
11. **Phase 5 Continuous Monitoring**: Real-time Prometheus metrics and rich console dashboard for drop rates, P50/P95/P99 latency, DNC freshness, and spend tracking.

---

## Architecture Diagram

```
                             Asterisk / VICIdial
                             (AudioSocket / SIP)
                                      │
                                      ▼
                        ┌──────────────────────────┐
                        │    Telephony Gateway     │
                        │   (8kHz <-> 16kHz PCM)   │
                        └─────────────┬────────────┘
                                      │ 640B / 20ms frames
                                      ▼
     ┌─────────────────────────────────────────────────────────────────┐
     │                      Session Audio Pipeline                     │
     │   ┌───────────────────────────┐   ┌──────────────────────────┐  │
     │   │   Ingress Jitter Buffer   │   │   Egress Playout Buffer  │  │
     │   │ (40-60ms depth, PLC/drops)│   │ (Paced 20ms, <5ms flush) │  │
     │   └─────────────┬─────────────┘   └─────────────▲────────────┘  │
     └─────────────────┼───────────────────────────────┼───────────────┘
                       │ Ingress PCM                   │ 16kHz Audio
                       ▼                               │
         ┌───────────────────────────┐   ┌─────────────┴────────────┐
         │    Streaming STT + VAD    │   │    Qwen3-TTS Streaming   │
         │  (Nova-3, 280-320ms VAD)  │   │  (Conversational style)  │
         └─────────────┬─────────────┘   └─────────────▲────────────┘
                       │ Transcript                    │ Approved Text
                       ▼                               │
         ┌───────────────────────────┐   ┌─────────────┴────────────┐
         │    Six-Stage Sales FSM    │──►│  Runtime Output Guardrail│
         │ (Lead History Context In) │   │ (No unapproved promises) │
         └─────────────┬─────────────┘   └──────────────────────────┘
                       │ CTI Actions
                       ▼
         ┌───────────────────────────┐
         │    VICIdial CTI Adapter   │
         │ (Transfer/Dispo/DNC/AMD)  │
         └───────────────────────────┘
```

---

## Directory Structure

```
g:/Shadow Voice/
├── pyproject.toml              # Pinned Python 3.12 dependencies & pytest config
├── README.md                   # Complete architectural guide & documentation
├── config/
│   ├── default_campaign.json   # Campaign script, approved pricing, and extensions
│   └── compliance_rules.json   # Calling windows, DNC, safe harbor, spend limits
├── src/
│   └── shadow_voice/
│       ├── core/               # Audio contract, jitter buffer, playout buffer, kill switch
│       │   ├── audio.py        # 16-bit linear PCM contract & 8kHz<->16kHz resampling
│       │   ├── jitter_buffer.py# Ingress jitter buffer (drift comp, PLC, telemetry)
│       │   ├── playout_buffer.py# Paced TTS egress playout buffer (monotonic clock)
│       │   ├── kill_switch.py  # System-wide kill switch & graceful wind-down
│       │   └── logging.py      # Structured JSON logging & session tracing
│       ├── telephony/          # Telephony transport & metadata
│       │   ├── audiosocket.py  # Native Asterisk AudioSocket TCP server/client
│       │   ├── sip_rtp.py      # BaseTransportAdapter abstraction
│       │   ├── resampler.py    # Gateway boundary resampling bridge
│       │   ├── session.py      # TelephonySession manager & lifecycle
│       │   ├── metadata.py     # Normalized metadata (SIP, X-headers, UUI)
│       │   └── amd.py          # Answering Machine Detection (2-sec safe harbor)
│       ├── conversation/       # Conversational AI pipeline
│       │   ├── stt.py          # Deepgram Nova-3 / Flux streaming STT
│       │   ├── vad.py          # 280-320ms target endpointing VAD
│       │   ├── llm.py          # Streaming LLM wrapper with TTFT instrumentation
│       │   ├── tts.py          # Qwen3-TTS streaming backend & style control
│       │   ├── barge_in.py     # Sub-millisecond barge-in controller
│       │   ├── guardrail.py    # Runtime output guardrail filter
│       │   └── outage_monitor.py# Vendor outage fallback & circuit breaker
│       ├── cti/                # Dialer integrations & history
│       │   ├── base.py         # BaseDialerAdapter ABC
│       │   ├── factory.py      # DialerFactory
│       │   ├── vicidial.py     # VICIdial Non-Agent & Agent API adapter
│       │   └── lead_history.py # Lead history store (lookup & append)
│       ├── dialogue/           # Dialogue management & natural language standards
│       │   ├── fsm.py          # Six-stage sales conversation FSM
│       │   ├── objections.py   # Comprehensive objection library
│       │   ├── natural_rules.py# Section 7 natural quality & anti-filler auditor
│       │   ├── script_registry.py# Versioned campaign scripts & prompt configs
│       │   ├── access_control.py# Dual sign-off deployment gate (PM + Dialogue Eng)
│       │   └── feedback_loop.py# Outcome feedback loop & closer ratings
│       ├── compliance/         # TCPA/TSR regulatory enforcement
│       │   ├── call_window.py  # Local daytime calling window (8am-9pm)
│       │   ├── dnc.py          # National (31-day staleness block), State, & Internal DNC
│       │   ├── abandonment.py  # Regulatory abandonment rate (<3%) vs technical failures
│       │   ├── audit_logger.py # 5-year cryptographic hash chain compliance store
│       │   ├── spend_guard.py  # Runaway cost guard & daily ceiling kill switch
│       │   └── legal_gates.py  # Jurisdiction confirmation & pre-dial legal basis
│       ├── testing/            # Benchmarking & test harnesses
│       │   ├── latency.py      # Percentile latency distribution (P50, P95, P99)
│       │   ├── canary.py       # Phase 4.5 canary rollout controller
│       │   ├── mock_telephony.py# Simulated AudioSocket client
│       │   └── load_harness.py # 5-concurrent-session load harness
│       └── monitoring/         # Live production monitoring
│           ├── metrics.py      # Prometheus exporter
│           └── dashboard.py    # Terminal health dashboard & alerting rules
└── tests/                      # Automated test suite (33 passing unit & load tests)
    ├── test_audio_and_buffers.py
    ├── test_audiosocket_and_amd.py
    ├── test_barge_in_and_guardrail.py
    ├── test_cti_and_lead_history.py
    ├── test_fsm_and_natural_dialogue.py
    ├── test_compliance_and_kill_switch.py
    └── test_canary_and_load.py
```

---

## Verification & Test Results

The platform includes an automated regression test suite covering all 40-day deliverables:

```bash
uv run pytest -v
```

Output:
```
tests/test_audio_and_buffers.py::test_audio_frame_validation PASSED
tests/test_audio_and_buffers.py::test_audio_resampling_boundary PASSED
tests/test_audio_and_buffers.py::test_ingress_jitter_buffer PASSED
tests/test_audio_and_buffers.py::test_paced_playout_buffer_and_barge_in_flush PASSED
tests/test_audiosocket_and_amd.py::test_gateway_resampler PASSED
tests/test_audiosocket_and_amd.py::test_metadata_normalization PASSED
tests/test_audiosocket_and_amd.py::test_amd_human_greeting PASSED
tests/test_audiosocket_and_amd.py::test_amd_machine_greeting PASSED
tests/test_barge_in_and_guardrail.py::test_barge_in_instant_cancellation PASSED
tests/test_barge_in_and_guardrail.py::test_runtime_guardrail_pass_clean_speech PASSED
tests/test_barge_in_and_guardrail.py::test_runtime_guardrail_catches_unauthorized_pricing PASSED
tests/test_barge_in_and_guardrail.py::test_runtime_guardrail_catches_unauthorized_guarantee PASSED
tests/test_barge_in_and_guardrail.py::test_runtime_guardrail_catches_legal_claim PASSED
tests/test_barge_in_and_guardrail.py::test_vendor_outage_circuit_breaker PASSED
tests/test_canary_and_load.py::test_5_concurrent_sessions_load_and_latency PASSED
tests/test_canary_and_load.py::test_canary_rollout_staged_promotion_and_rejection PASSED
tests/test_compliance_and_kill_switch.py::test_call_window_daytime_enforcement PASSED
tests/test_compliance_and_kill_switch.py::test_national_dnc_staleness_gate PASSED
tests/test_compliance_and_kill_switch.py::test_internal_and_state_dnc PASSED
tests/test_compliance_and_kill_switch.py::test_regulatory_abandonment_vs_technical_failures PASSED
tests/test_compliance_and_kill_switch.py::test_spend_ceiling_guard_kill_switch_trigger PASSED
tests/test_compliance_and_kill_switch.py::test_kill_switch_session_registration_and_wind_down PASSED
tests/test_compliance_and_kill_switch.py::test_compliance_audit_store_hash_chain_and_backup PASSED
tests/test_cti_and_lead_history.py::test_vicidial_adapter_operations PASSED
tests/test_cti_and_lead_history.py::test_vicidial_dnc_suppression_and_readback PASSED
tests/test_cti_and_lead_history.py::test_lead_history_lookup_and_append PASSED
tests/test_cti_and_lead_history.py::test_lead_history_corrupted_failsafe PASSED
tests/test_fsm_and_natural_dialogue.py::test_section_7_1_opening_greeting_natural_standard PASSED
tests/test_fsm_and_natural_dialogue.py::test_section_7_3_corporate_filler_detection PASSED
tests/test_fsm_and_natural_dialogue.py::test_fsm_six_stage_progression PASSED
tests/test_fsm_and_natural_dialogue.py::test_fsm_dnc_immediate_compliance_path PASSED
tests/test_fsm_and_natural_dialogue.py::test_fsm_human_transfer_path PASSED
tests/test_fsm_and_natural_dialogue.py::test_script_deployment_access_control_dual_signoff PASSED

tests/test_reach_eyes.py::test_reach_analyzer_extraction PASSED
tests/test_reach_eyes.py::test_reach_reader_validation PASSED
tests/test_cognitive_brain.py::test_brain_instructions_crud PASSED
tests/test_cognitive_brain.py::test_customer_question_learning_and_approval PASSED
tests/test_cognitive_brain.py::test_story_bank_receipts PASSED
tests/test_cognitive_brain.py::test_conversational_system_prompt_builder PASSED
tests/test_webphone_and_api.py::test_webphone_session_lifecycle PASSED
tests/test_webphone_and_api.py::test_api_instructions_and_natural_audit PASSED
tests/test_webphone_and_api.py::test_api_brain_endpoints PASSED
tests/test_webphone_and_api.py::test_api_dialer_endpoints PASSED
tests/test_webphone_and_api.py::test_api_call_start_and_turn PASSED

============================= 46 passed in 39.68s =============================
```

---

## 🚀 Quick Start (< 1 Minute)

### Option A: 1-Click Launch (Windows)
Double-click `launch.bat` in the repository root:
```cmd
launch.bat
```

### Option B: Terminal / uv (All Platforms)
```bash
# Run web studio server on port 8002
python run.py
```
Open your browser to **http://localhost:8002**.

---

## 🎛️ Shadow Voice Studio Features

1. **Live Console & Built-in Web Phone (Softphone)**:
   - Make and receive test calls directly inside the browser using microphone & speakers.
   - Real-time HTML5 audio waveform canvas.
   - Symmetrical barge-in (<5ms flush).
   - Turn-by-turn latency measurement: STT (65ms) -> LLM TTFT (110ms) -> TTS (75ms) -> Total playout (<540ms).
   - Mid-call controls: Mute, Warm/Blind Transfer (x8300), and Dispositions (SALE, CALLBK, XFER, NI, DNC).

2. **Instruction Studio & Section 7.1 Natural Dialogue Standard**:
   - Plain-English editor for Agent Persona (Name, Company, Industry, Tone).
   - Opening Greeting editor strictly enforcing Section 7.1 natural human business greetings (`"Hi, this is [Name] calling from [Company] — do you have a quick minute?"`) with **ZERO** robotic/AI disclosures.
   - Real-time Humanizer Auditor badge and violation prevention.
   - Live Prompt Simulation Sandbox for rapid testing before live dialing.

3. **Cognitive Brain & Customer Learning Bank**:
   - Long-term evolving SQLite memory with WAL mode (`storage/shadow_voice.db`).
   - Automatically detects questions asked by customers during live calls.
   - Tracks frequency, categorizes by topic, drafts suggested answers, and flags for 1-click user review & approval.
   - Story Bank: stores verified technical receipts, ROI metrics, and benchmarks.

4. **Pluggable Dialers & CTI Hub**:
   - **VICIdial Cluster**: Non-Agent API (`/vicidial/non_agent_api.php`) and Agent API (`/agc/api.php`) with disposition write-back, closer transfers, and DNC read-back verification.
   - **Asterisk / FreePBX AudioSocket**: Direct TCP streaming socket (port 9092) with 16kHz linear PCM mono.
   - **Cloud CPaaS**: Twilio / Telnyx SIP trunks.
   - **Built-in Web Phone**: Browser Web Audio softphone.
   - Real-time connection testing button on every card.

5. **Agent Reach Eyes (Web & Competitor Learning)**:
   - High-speed Jina Reader (`https://r.jina.ai/{url}`) + DOM scraper.
   - Ingests company landing pages, competitor offerings, or lead websites.
   - Automatically extracts core value propositions, pricing tiers, and candidate Q&As.
   - 1-Click "Digest into Cognitive Brain" action button.

6. **Model Context Protocol (MCP Server)**:
   - JSON-RPC 2.0 stdio server (`run_mcp.py`) compatible with Antigravity, Cursor, and Claude Desktop.
   - Tools: `update_instructions`, `get_brain_knowledge`, `review_customer_question`, `scan_url_with_reach_eyes`, `simulate_call_turn`.