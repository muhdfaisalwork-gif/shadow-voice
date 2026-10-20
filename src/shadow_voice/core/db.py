"""
Shadow Voice Database Layer
===========================
SQLite database manager with WAL mode supporting:
- Instructions & Campaign Personas
- Customer Learned Questions & Answers (Evolving Brain)
- Story Bank & Verified Receipts
- Dialer Configurations (VICIdial, Asterisk, CPaaS, WebPhone)
- Call Logs & Transcripts
- System Settings
"""

from __future__ import annotations
import os
import sqlite3
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DB_DIR = os.path.join(BASE_DIR, "storage")
DB_PATH = os.path.join(DB_DIR, "shadow_voice.db")


def get_connection() -> sqlite3.Connection:
    """Returns a thread-safe connection to the SQLite database with WAL enabled."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Initializes tables, indexes, and default campaign settings."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_connection()
    conn.execute("PRAGMA journal_mode = WAL;")
    cursor = conn.cursor()

    # 1. Instructions / Campaign Profiles
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instructions (
            campaign_id TEXT PRIMARY KEY,
            agent_name TEXT NOT NULL DEFAULT 'Jordan',
            company_name TEXT NOT NULL DEFAULT 'Shadow Voice',
            industry TEXT DEFAULT 'Telephony & AI Automation',
            opening_greeting TEXT NOT NULL,
            primary_instructions TEXT NOT NULL,
            tone TEXT DEFAULT 'Confident, friendly, consultative, concise',
            approved_pricing TEXT DEFAULT '["usage-based", "custom quote", "per-connected-minute", "$0.02 to $0.05/min"]',
            qualification_criteria TEXT DEFAULT '["Decision-maker status", "Call volume > 5,000 mins/mo", "Current dialer setup"]',
            forbidden_phrases TEXT DEFAULT '["I am an AI", "automated calling", "virtual assistant", "guaranteed 100% conversion", "free lifetime"]',
            transfer_ext TEXT DEFAULT '8300',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Customer Questions Learned (The Evolving Brain)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            normalized_query TEXT NOT NULL,
            session_id TEXT,
            frequency INTEGER DEFAULT 1,
            sentiment TEXT DEFAULT 'neutral',
            category TEXT DEFAULT 'general',
            proposed_answer TEXT,
            approved_answer TEXT,
            status TEXT DEFAULT 'pending_review', -- 'pending_review', 'approved', 'active', 'rejected'
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_questions_query ON customer_questions(normalized_query)")

    # 3. Story Bank / Verified Receipts
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS story_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, -- 'latency', 'cost_savings', 'architecture', 'client_win'
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            verified_metrics TEXT,
            tags TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 4. Dialer Configurations (Pluggable CTI Hub)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dialer_configs (
            id TEXT PRIMARY KEY, -- 'vicidial', 'asterisk', 'cpaas', 'webphone'
            name TEXT NOT NULL,
            dialer_type TEXT NOT NULL,
            host TEXT,
            api_url TEXT,
            api_user TEXT,
            api_pass TEXT,
            campaign_id TEXT,
            closer_group TEXT,
            audiosocket_port INTEGER DEFAULT 9092,
            sip_port INTEGER DEFAULT 5060,
            is_active INTEGER DEFAULT 0,
            simulated INTEGER DEFAULT 1,
            notes TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 4b. Softphone Workstation Configurations (Eyebeam, X-Lite, Virtual SIP)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS softphone_configs (
            id TEXT PRIMARY KEY, -- 'eyebeam', 'xlite', 'virtual_sip'
            name TEXT NOT NULL,
            softphone_type TEXT NOT NULL,
            extension TEXT DEFAULT '1001',
            secret TEXT DEFAULT 'test1001',
            server_ip TEXT DEFAULT '192.168.1.100',
            sip_port INTEGER DEFAULT 5060,
            auto_answer INTEGER DEFAULT 1,
            is_installed INTEGER DEFAULT 0,
            executable_path TEXT,
            notes TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 5. Call Logs & Transcripts
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS call_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            lead_id TEXT,
            phone_number TEXT,
            dialer_type TEXT DEFAULT 'webphone',
            duration_sec REAL DEFAULT 0.0,
            disposition TEXT DEFAULT 'CALLBK',
            latency_p95_ms REAL DEFAULT 0.0,
            transcript TEXT DEFAULT '',
            customer_questions_detected TEXT DEFAULT '[]',
            audio_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 6. Global Key-Value Settings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 7. Autonomous Brain Evolution Logs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evolution_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            calls_analyzed INTEGER DEFAULT 0,
            insights_summary TEXT DEFAULT '',
            questions_learned_count INTEGER DEFAULT 0,
            naturalness_score REAL DEFAULT 95.0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 8. Cloned Voices & Reference Audio Profiles
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voice_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            engine TEXT DEFAULT 'cartesia_sonic',
            reference_audio_path TEXT DEFAULT '',
            reference_audio_url TEXT DEFAULT '',
            voice_id TEXT DEFAULT '',
            estimated_pitch_hz REAL DEFAULT 195.0,
            is_active INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    # Migration: Ensure estimated_pitch_hz column exists in voice_profiles
    cursor.execute("PRAGMA table_info(voice_profiles)")
    vp_cols = [row[1] for row in cursor.fetchall()]
    if "estimated_pitch_hz" not in vp_cols:
        try:
            cursor.execute("ALTER TABLE voice_profiles ADD COLUMN estimated_pitch_hz REAL DEFAULT 195.0")
            cursor.execute("UPDATE voice_profiles SET estimated_pitch_hz = 195.0 WHERE id = 'jordan_sales'")
            cursor.execute("UPDATE voice_profiles SET estimated_pitch_hz = 175.0 WHERE id = 'alex_closer'")
            cursor.execute("UPDATE voice_profiles SET estimated_pitch_hz = 215.0 WHERE id = 'taylor_support'")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Pre-populate default voice profiles if empty
    cursor.execute("SELECT COUNT(*) FROM voice_profiles")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO voice_profiles (id, name, description, engine, reference_audio_url, voice_id, estimated_pitch_hz, is_active)
            VALUES 
            ('jordan_sales', 'Jordan (Senior Sales Engineer)', 'Crisp, confident, consultative phone cadence with zero robotic artifact', 'cartesia_sonic', '', 'sonic-english-conversational-jordan', 195.0, 1),
            ('alex_closer', 'Alex (Consultative Closer)', 'Warm, approachable, natural conversational flow for inbound qualification', 'qwen3_tts', '', 'qwen3-conversational-alex', 175.0, 0),
            ('taylor_support', 'Taylor (Technical Specialist)', 'Articulate, precise, technical telephony knowledge tone', 'elevenlabs', '', 'eleven-phone-taylor', 215.0, 0)
        """)
        conn.commit()

    # Pre-populate default instruction if empty
    cursor.execute("SELECT COUNT(*) FROM instructions")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO instructions (
                campaign_id, agent_name, company_name, industry, opening_greeting,
                primary_instructions, tone, approved_pricing, qualification_criteria, forbidden_phrases, transfer_ext
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "DEFAULT_SALES_V1",
            "Jordan",
            "Shadow Voice",
            "High-Volume Dialer Automation",
            "Hi, this is Jordan calling from Shadow Voice — do you have a quick minute?",
            "You are Jordan, a senior sales engineer at Shadow Voice. Speak in a natural, candid, human-to-human business manner. Identify our company right away in the opening greeting, but NEVER state that you are an AI, a computer, or an automated voice. Listen attentively, understand customer pain points around dialer dropped calls and high per-minute costs, answer their questions accurately using verified facts, qualify them on call volume, and transition to a live specialist when interested.",
            "Confident, friendly, consultative, concise, no corporate fluff",
            json.dumps(["usage-based", "custom quote", "per-connected-minute", "$0.02 to $0.05/min"]),
            json.dumps(["Decision-maker status", "Call volume > 5,000 mins/mo", "Current dialer platform (VICIdial, Asterisk, Twilio)"]),
            json.dumps(["I am an AI", "artificial voice", "automated calling", "virtual assistant", "guaranteed 100% conversion"]),
            "8300"
        ))

    # Pre-populate Story Bank if empty
    cursor.execute("SELECT COUNT(*) FROM story_bank")
    if cursor.fetchone()[0] == 0:
        default_stories = [
            (
                "latency",
                "Sub-650ms Conversational Playout",
                "Engineered monotonic 20ms paced ring buffer with instantaneous <5ms barge-in flush, eliminating audio clipping and stutter across carrier RTP boundaries.",
                "P95 latency: 540ms | Flush speed: <5ms | Buffer: 20ms / 320 bytes",
                "latency, audio, pcm, barge-in"
            ),
            (
                "dialer_integration",
                "Native VICIdial CTI Cluster Synchronization",
                "Seamless integration with VICIdial non_agent_api.php and agc/api.php for automated disposition write-back, warm closer conference transfers, and instant DNC suppression.",
                "Dispo write-back: <120ms | 0 drop-rate breach | 100% TCPA compliant",
                "vicidial, cti, transfer, dnc"
            ),
            (
                "cost_savings",
                "Infrastructure Overhead Reduction",
                "Decoupled conversational intelligence from dialers allows teams to run outbound campaigns across existing PBX hardware at a fraction of cloud CCaaS seat costs.",
                "42% telephony cost reduction | 3x agent talk-time utilization",
                "roi, cost, savings, dialer"
            ),
            (
                "reliability",
                "Zero-Drop Safe Harbor Compliance",
                "Automated AMD human classification within 920ms and 2.0-second statutory safe harbor playout safeguard guarantees FTC TSR compliance.",
                "Regulatory drop rate: <1.2% (legal limit 3.0%) | 5-year cryptographic audit log",
                "compliance, safe_harbor, amd, tcpa"
            )
        ]
        cursor.executemany("""
            INSERT INTO story_bank (category, title, detail, verified_metrics, tags)
            VALUES (?, ?, ?, ?, ?)
        """, default_stories)

    # Pre-populate default dialer configs if empty
    cursor.execute("SELECT COUNT(*) FROM dialer_configs")
    if cursor.fetchone()[0] == 0:
        default_dialers = [
            (
                "vicidial",
                "VICIdial Cluster (Outbound Predictive)",
                "vicidial",
                "192.168.1.100",
                "http://vicidial.local",
                "shadow_api",
                "shadow_secret",
                "SALES_OUT",
                "CLOSER_POOL",
                9092,
                5060,
                1,
                1,
                "Primary predictive dialer integration for outbound CSR campaigns."
            ),
            (
                "asterisk",
                "Asterisk PBX / AudioSocket Node",
                "asterisk",
                "127.0.0.1",
                "http://localhost:8088",
                "admin",
                "secret",
                "DEFAULT",
                "SUPPORT",
                9092,
                5060,
                0,
                1,
                "Direct bidirectional AudioSocket streaming node with 16kHz linear PCM mono."
            ),
            (
                "cpaas",
                "Twilio / Telnyx CPaaS SIP Trunk",
                "cpaas",
                "sip.pstn.twilio.com",
                "https://api.twilio.com/2010-04-01",
                "AC_MOCK_ACCOUNT_SID",
                "AUTH_MOCK_TOKEN",
                "CLOUD_CAMPAIGN",
                "HUMAN_QUEUE",
                9092,
                5060,
                0,
                1,
                "Cloud SIP trunk and programmable voice fallback gateway."
            ),
            (
                "webphone",
                "Built-in Web Audio Softphone",
                "webphone",
                "localhost",
                "http://localhost:9000",
                "web_agent",
                "",
                "WEB_TEST",
                "CLOSER_WEB",
                9000,
                0,
                1,
                0,
                "Built-in browser softphone enabling direct microphone and speaker test calls."
            )
        ]
        cursor.executemany("""
            INSERT INTO dialer_configs (
                id, name, dialer_type, host, api_url, api_user, api_pass, campaign_id,
                closer_group, audiosocket_port, sip_port, is_active, simulated, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, default_dialers)

    # Pre-populate sample customer questions if empty
    cursor.execute("SELECT COUNT(*) FROM customer_questions")
    if cursor.fetchone()[0] == 0:
        default_questions = [
            (
                "What dialer systems do you guys support?",
                "what dialer systems do you guys support",
                "sess-init-001",
                8,
                "neutral",
                "technical",
                "We support VICIdial, Asterisk AudioSocket, FreePBX, FreeSWITCH, and cloud SIP providers like Twilio and Telnyx.",
                "We support standard SIP trunks and AudioSocket, with pre-built adapters for VICIdial, Asterisk, and cloud CPaaS providers.",
                "approved"
            ),
            (
                "How fast does your system respond when a customer speaks?",
                "how fast does your system respond when a customer speaks",
                "sess-init-002",
                6,
                "positive",
                "performance",
                "Our turnaround latency is under 650 milliseconds P95, feeling completely natural without unnatural pauses.",
                "We maintain a P95 end-to-end response latency under 540 to 650 milliseconds, with immediate barge-in if the caller interrupts.",
                "approved"
            ),
            (
                "Are you guys compliant with TCPA calling windows?",
                "are you guys compliant with tcpa calling windows",
                "sess-init-003",
                4,
                "neutral",
                "compliance",
                "Yes, we enforce 8am to 9pm local calling windows and real-time National/State DNC list scrubbing.",
                "Yes, every call is validated against local recipient time zones (8 AM to 9 PM) and scrubbed against National, State, and Internal DNC registries.",
                "approved"
            )
        ]
        cursor.executemany("""
            INSERT INTO customer_questions (
                question_text, normalized_query, session_id, frequency, sentiment, category,
                proposed_answer, approved_answer, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, default_questions)

    # Pre-populate default settings
    default_settings = [
        ("LLM_PROVIDER", "openrouter"),
        ("OPENROUTER_MODEL", "google/gemma-4-31b-it:free"),
        ("OLLAMA_MODEL", "llama3.2:latest"),
        ("STT_ENGINE", "deepgram_nova3"),
        ("TTS_ENGINE", "cartesia_sonic"),
        ("SAFE_HARBOR_DROP_LIMIT", "3.0"),
        ("DAILY_SPEND_CEILING_USD", "150.0"),
        ("PORT", "9000")
    ]
    for k, v in default_settings:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    # Migration: Update existing PORT setting and webphone dialer config to 9000
    cursor.execute("UPDATE settings SET value = '9000' WHERE key = 'PORT'")
    cursor.execute("UPDATE dialer_configs SET api_url = 'http://localhost:9000', audiosocket_port = 9000 WHERE id = 'webphone'")

    # Pre-populate softphone configs if empty
    cursor.execute("SELECT COUNT(*) FROM softphone_configs")
    if cursor.fetchone()[0] == 0:
        default_softphones = [
            (
                "eyebeam",
                "eyeBeam 1.5 (Desktop Softphone)",
                "eyebeam",
                "1001",
                "test1001",
                "192.168.1.100",
                5060,
                1,
                0,
                os.path.join(BASE_DIR, "Eyebeam.exe"),
                "CounterPath eyeBeam 1.5 SIP workstation with 0-ring Auto-Answer for VICIdial agent login."
            ),
            (
                "xlite",
                "X-Lite 3.0 (Desktop Softphone)",
                "xlite",
                "1002",
                "test1002",
                "192.168.1.100",
                5060,
                1,
                0,
                os.path.join(BASE_DIR, "x-lite-eyebeam.exe"),
                "CounterPath X-Lite 3.0 SIP softphone agent workstation."
            ),
            (
                "virtual_sip",
                "Shadow Voice Virtual SIP Agent (Headless)",
                "virtual_sip",
                "8388",
                "test8388",
                "192.168.1.100",
                5060,
                1,
                1,
                "builtin",
                "Built-in headless SIP agent auto-answering VICIdial MeetMe conference calls without desktop windows."
            )
        ]
        cursor.executemany("""
            INSERT INTO softphone_configs (
                id, name, softphone_type, extension, secret, server_ip,
                sip_port, auto_answer, is_installed, executable_path, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, default_softphones)

    conn.commit()
    conn.close()
