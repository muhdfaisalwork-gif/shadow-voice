"""Tests for 5-Session Concurrent Load Harness and Phase 4.5 Canary Rollout."""

import pytest
from shadow_voice.testing.load_harness import ConcurrencyLoadHarness
from shadow_voice.testing.canary import CanaryRolloutController, CanaryStage
from shadow_voice.core.kill_switch import KillSwitch


@pytest.mark.asyncio
async def test_5_concurrent_sessions_load_and_latency():
    KillSwitch.reset_for_test()
    harness = ConcurrencyLoadHarness(concurrency_count=5)

    results = await harness.run_concurrent_load_test()

    assert len(results) == 5
    for r in results:
        assert r.turns_completed == 3
        assert r.cross_contamination_detected is False

    # Check Latency Percentiles across all turns
    report = harness.latency_tracker.generate_report()
    assert report.total_turns == 15  # 5 sessions * 3 turns

    # TARGET LATENCY VERIFICATION: P95 speech-end-to-first-audio < 650 ms!
    print(f"\n--- LATENCY REPORT ---")
    print(f"Total turns: {report.total_turns}")
    print(f"P50: {report.e2e_distribution.p50:.1f}ms")
    print(f"P95: {report.e2e_distribution.p95:.1f}ms (Target <650ms)")
    print(f"P99: {report.e2e_distribution.p99:.1f}ms")

    assert report.passed_p95_under_650ms is True
    assert report.e2e_distribution.p95 < 650.0


def test_canary_rollout_staged_promotion_and_rejection():
    ks = KillSwitch.reset_for_test()
    canary = CanaryRolloutController(kill_switch=ks)

    # 1. Day 36 Stage 1: 1 line passes cleanly
    res_s1 = canary.evaluate_stage(
        stage=CanaryStage.STAGE_1_SINGLE_LINE,
        calls_completed=10,
        regulatory_drop_rate=0.01,
        latency_p95_ms=520.0,
        compliance_violations=0
    )
    assert res_s1.passed is True
    assert canary.current_stage == CanaryStage.STAGE_2_THREE_LINES
    assert ks.can_dial() is True

    # 2. Day 37 Stage 2: 3 lines trips compliance violation -> triggers kill switch & blocks promotion
    res_s2 = canary.evaluate_stage(
        stage=CanaryStage.STAGE_2_THREE_LINES,
        calls_completed=15,
        regulatory_drop_rate=0.015,
        latency_p95_ms=540.0,
        compliance_violations=1  # Violation tripped!
    )
    assert res_s2.passed is False
    assert ks.is_triggered is True
    assert ks.can_dial() is False
    assert canary.current_stage == CanaryStage.STAGE_2_THREE_LINES  # Did not promote
