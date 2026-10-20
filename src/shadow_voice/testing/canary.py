"""
Phase 4.5 Canary Rollout Controller
===================================
Fulfills Principle 10 & Phase 4.5:
- Staged production deployment preventing cold-start failures
- Stage 1: 1 Line (Day 36)
- Stage 2: 3 Lines (Day 37)
- Stage 3: 5 Lines (Full production scale)
- Strict compliance & latency gate verification before each promotion
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, List
from shadow_voice.core.kill_switch import KillSwitch, KillSwitchRole
from shadow_voice.testing.latency import LatencyTracker

logger = logging.getLogger("shadow_voice.canary")


class CanaryStage(IntEnum):
    STAGE_1_SINGLE_LINE = 1
    STAGE_2_THREE_LINES = 3
    STAGE_3_FULL_SCALE = 5


@dataclass
class CanaryEvaluationResult:
    stage: CanaryStage
    total_calls_completed: int
    regulatory_drop_rate: float
    latency_p95_ms: float
    compliance_violations: int
    passed: bool
    rejection_reason: Optional[str] = None


class CanaryRolloutController:
    """Controls staged capacity scaling and verifies compliance gates."""

    def __init__(
        self,
        kill_switch: Optional[KillSwitch] = None,
        max_allowed_drop_rate: float = 0.025,
        max_allowed_p95_ms: float = 650.0
    ) -> None:
        self.kill_switch = kill_switch or KillSwitch.get_instance()
        self.max_allowed_drop_rate = max_allowed_drop_rate
        self.max_allowed_p95_ms = max_allowed_p95_ms
        self.current_stage: CanaryStage = CanaryStage.STAGE_1_SINGLE_LINE
        self.history: List[CanaryEvaluationResult] = []

    def evaluate_stage(
        self,
        stage: CanaryStage,
        calls_completed: int,
        regulatory_drop_rate: float,
        latency_p95_ms: float,
        compliance_violations: int
    ) -> CanaryEvaluationResult:
        """Evaluates canary performance metrics before allowing next stage promotion."""
        passed = True
        reasons = []

        if compliance_violations > 0:
            passed = False
            reasons.append(f"{compliance_violations} compliance violation(s) detected")

        if regulatory_drop_rate > self.max_allowed_drop_rate:
            passed = False
            reasons.append(f"Regulatory drop rate {regulatory_drop_rate * 100:.2f}% exceeded limit {self.max_allowed_drop_rate * 100:.2f}%")

        if latency_p95_ms > self.max_allowed_p95_ms:
            passed = False
            reasons.append(f"P95 latency {latency_p95_ms:.1f}ms exceeded ceiling {self.max_allowed_p95_ms:.1f}ms")

        if calls_completed < 5:
            passed = False
            reasons.append(f"Insufficient call volume ({calls_completed} calls, minimum 5 required for canary gate)")

        rejection_reason = "; ".join(reasons) if not passed else None
        res = CanaryEvaluationResult(
            stage=stage,
            total_calls_completed=calls_completed,
            regulatory_drop_rate=regulatory_drop_rate,
            latency_p95_ms=latency_p95_ms,
            compliance_violations=compliance_violations,
            passed=passed,
            rejection_reason=rejection_reason
        )
        self.history.append(res)

        if not passed:
            logger.critical(
                f"[CANARY GATE FAILED] Stage {stage.name} failed: {rejection_reason}. Triggering kill switch!"
            )
            self.kill_switch.trigger(
                role=KillSwitchRole.QA_COMPLIANCE_ENG,
                reason=f"Canary stage {stage.value} verification failure: {rejection_reason}"
            )
        else:
            logger.info(f"[CANARY GATE CLEARED] Stage {stage.name} passed all quality and compliance checks.")
            if stage == CanaryStage.STAGE_1_SINGLE_LINE:
                self.current_stage = CanaryStage.STAGE_2_THREE_LINES
            elif stage == CanaryStage.STAGE_2_THREE_LINES:
                self.current_stage = CanaryStage.STAGE_3_FULL_SCALE

        return res
