"""Tests for Production Evidence Package Compilation (Section 5)."""

import pytest
from shadow_voice.testing.evidence import ProductionEvidencePackage


def test_production_evidence_package_completeness():
    pkg = ProductionEvidencePackage()
    artifacts = pkg.compile_all_evidence()

    # Must contain all 25 items specified in Section 5
    assert len(artifacts) == 25

    # Check specific crucial items
    items_by_id = {a.item_id: a for a in artifacts}

    # Item 7: Latency percentile report
    assert items_by_id[7].status == "VERIFIED"
    assert items_by_id[7].details["p95_ms"] <= 650.0

    # Item 15: Natural Language & Section 7.1
    assert items_by_id[15].status == "VERIFIED"
    assert items_by_id[15].details["ai_disclosure_in_opening"] is False

    # Item 19: Kill-switch drill
    assert items_by_id[19].status == "VERIFIED"

    # Item 20: Runtime Guardrail
    assert items_by_id[20].status == "VERIFIED"

    # Markdown rendering
    md = pkg.render_markdown()
    assert "# Shadow Voice" in md
    assert "VERIFIED" in md