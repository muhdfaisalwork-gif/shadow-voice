"""
Test Agent Reach Eyes
=====================
Validates:
- Web content parsing (Jina Reader / DOM)
- Company intelligence extraction (value props, pricing, candidate Q&As)
- One-click digestion into Cognitive Brain
"""

import pytest
from shadow_voice.core.db import init_db
from shadow_voice.brain.brain import BrainManager
from shadow_voice.reach.reader import ReachReader
from shadow_voice.reach.analyzer import ReachAnalyzer


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_reach_analyzer_extraction():
    brain = BrainManager()
    analyzer = ReachAnalyzer(brain)

    sample_html_text = """
    # Acme Telecom — Cloud PBX and Predictive Dialers
    Acme Telecom helps sales call centers reduce telemarketing costs by 35% and scale high-volume outbound lines.
    We automate lead routing with sub-500ms voice connection and full TCPA compliance.
    Pricing starts at $0.025 per minute with custom quotes for enterprise clusters over 50,000 minutes.
    """

    analysis = analyzer.analyze_content(
        title="Acme Telecom — Cloud PBX",
        content=sample_html_text,
        url="https://acmetelecom.example.com"
    )

    assert "Acme Telecom" in analysis["company_name"]
    assert len(analysis["value_propositions"]) > 0
    assert len(analysis["pricing_highlights"]) > 0
    assert len(analysis["suggested_qas"]) >= 2

    # Verify 1-click digestion into Brain
    digest_res = analyzer.digest_into_brain(analysis)
    assert digest_res["success"] is True
    assert digest_res["questions_added"] >= 2

    # Verify Story Bank contains digested receipt
    stories = brain.get_story_bank(query="Acme Telecom")
    assert len(stories) >= 1
    assert "Acme Telecom" in stories[0]["title"]


def test_reach_reader_validation():
    reader = ReachReader()
    # Invalid url handling
    err_res = reader.read_url("")
    assert err_res["status"] == "error"

    # Well-formed URL structure handling
    res = reader.read_url("https://example.com")
    assert "url" in res
