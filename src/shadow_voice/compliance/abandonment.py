"""
Abandonment Rate & Safe-Harbor Monitor
======================================
Strictly separates:
(A) Technical Call Failure Rate (SIP errors, network disconnects, carrier rejects)
(B) Regulatory Abandoned-Call Rate (Live human answers but audio/rep not connected within 2 seconds)

Enforces the FCC / FTC 3.0% maximum abandonment safe harbor threshold.
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("shadow_voice.abandonment")

REGULATORY_DROP_RATE_CEILING = 0.03  # 3.0% max allowed by FCC/FTC


@dataclass
class AbandonmentMetrics:
    total_outbound_attempts: int = 0
    total_answered_calls: int = 0
    live_human_answers: int = 0
    regulatory_abandoned_calls: int = 0  # Answered by human but no rep/audio within 2.0s
    technical_failures: int = 0          # Carrier errors, SIP 503, packet loss disconnects

    @property
    def regulatory_abandonment_rate(self) -> float:
        """Percentage of live-answered calls abandoned under regulatory definition."""
        if self.live_human_answers == 0:
            return 0.0
        return self.regulatory_abandoned_calls / float(self.live_human_answers)

    @property
    def technical_failure_rate(self) -> float:
        """Percentage of total call attempts that failed due to technical/network reasons."""
        if self.total_outbound_attempts == 0:
            return 0.0
        return self.technical_failures / float(self.total_outbound_attempts)


class SafeHarborAbandonmentMonitor:
    """
    Monitors call outcomes and tracks regulatory safe-harbor compliance in real time.
    """

    def __init__(self, warning_threshold: float = 0.025) -> None:
        self.warning_threshold = warning_threshold
        self.metrics = AbandonmentMetrics()

    def record_call_attempt(self) -> None:
        self.metrics.total_outbound_attempts += 1

    def record_technical_failure(self, reason: str) -> None:
        """Records a transport / network / carrier failure."""
        self.metrics.technical_failures += 1
        logger.info(f"[TECHNICAL FAILURE] Reason: {reason} (Total technical failures: {self.metrics.technical_failures})")

    def record_live_answer(
        self,
        time_to_connect_audio_ms: float,
        is_human: bool = True
    ) -> bool:
        """
        Records an answered call.
        If live human is answered and time to audio > 2000 ms, it is classified as a REGULATORY ABANDONMENT!
        Returns True if call satisfied the 2-second safe harbor.
        """
        self.metrics.total_answered_calls += 1
        if not is_human:
            # Machine / fax / silence does not count toward telemarketing abandonment denominator
            return True

        self.metrics.live_human_answers += 1
        is_safe = time_to_connect_audio_ms <= 2000.0

        if not is_safe:
            self.metrics.regulatory_abandoned_calls += 1
            rate = self.metrics.regulatory_abandonment_rate
            logger.warning(
                f"[REGULATORY ABANDONMENT] Live human audio connect took {time_to_connect_audio_ms:.1f}ms (>2000ms safe harbor). "
                f"Current abandonment rate: {rate * 100:.2f}%"
            )
            if rate >= self.warning_threshold:
                logger.critical(
                    f"[REGULATORY CEILING WARNING] Abandonment rate {rate * 100:.2f}% is approaching 3.0% FCC limit!"
                )
        else:
            logger.info(f"[SAFE HARBOR CLEARED] Live human audio connected in {time_to_connect_audio_ms:.1f}ms (<=2000ms)")

        return is_safe
