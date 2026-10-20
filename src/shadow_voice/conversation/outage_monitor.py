"""
Vendor Outage Monitor & Circuit Breaker
=======================================
Fulfills Section 8.3 Gap-Fill:
- Tracks health and consecutive errors for STT, LLM, and TTS providers
- Automatically halts new outbound dialing via KillSwitch on sustained vendor outage
- Prevents dialing customers into a broken conversational pipeline (dead air)
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional
from shadow_voice.core.kill_switch import KillSwitch, KillSwitchRole

logger = logging.getLogger("shadow_voice.outage_monitor")


class ProviderType(str, Enum):
    STT = "STT"
    LLM = "LLM"
    TTS = "TTS"


@dataclass
class ProviderHealth:
    consecutive_failures: int = 0
    total_calls: int = 0
    total_failures: int = 0
    last_failure_time: Optional[float] = None
    is_healthy: bool = True


class VendorOutageMonitor:
    """
    Monitors upstream AI service health.
    Triggers automated dialing halt if any provider experiences sustained outages.
    """

    def __init__(
        self,
        consecutive_failure_threshold: int = 3,  # 3 consecutive failed calls = sustained outage
        kill_switch: Optional[KillSwitch] = None
    ) -> None:
        self.threshold = consecutive_failure_threshold
        self.kill_switch = kill_switch or KillSwitch.get_instance()
        self.providers: Dict[ProviderType, ProviderHealth] = {
            ProviderType.STT: ProviderHealth(),
            ProviderType.LLM: ProviderHealth(),
            ProviderType.TTS: ProviderHealth(),
        }

    def record_success(self, provider: ProviderType) -> None:
        health = self.providers[provider]
        health.total_calls += 1
        health.consecutive_failures = 0
        health.is_healthy = True

    def record_failure(self, provider: ProviderType, error_message: str) -> bool:
        """
        Records a provider failure.
        If consecutive failure threshold is exceeded, triggers the system kill switch.
        Returns True if threshold was breached.
        """
        health = self.providers[provider]
        health.total_calls += 1
        health.total_failures += 1
        health.consecutive_failures += 1
        health.last_failure_time = time.time()

        logger.error(
            f"[VENDOR HEALTH] {provider.value} failure ({health.consecutive_failures}/{self.threshold}): {error_message}"
        )

        if health.consecutive_failures >= self.threshold:
            health.is_healthy = False
            logger.critical(
                f"[SUSTAINED VENDOR OUTAGE] Provider {provider.value} failed {health.consecutive_failures} consecutive times! "
                f"Halting all outbound dialing via KillSwitch."
            )
            self.kill_switch.trigger(
                role=KillSwitchRole.AUTOMATED_SPEND_GUARD,
                reason=f"Sustained {provider.value} provider outage ({health.consecutive_failures} consecutive errors: {error_message})"
            )
            return True

        return False
