"""
Spend Ceiling & Runaway-Cost Guard
===================================
Fulfills Section 8.4 Gap-Fill:
- Hard per-day and per-campaign cap on GPU/API spend
- Tied directly to KillSwitch mechanism: if spend limit is hit, new outbound dialing halts immediately!
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional
from shadow_voice.core.kill_switch import KillSwitch, KillSwitchRole

logger = logging.getLogger("shadow_voice.spend_guard")


@dataclass
class CampaignSpend:
    current_spend_usd: float = 0.0
    spend_ceiling_usd: float = 100.0


class SpendCeilingGuard:
    """
    Monitors daily and per-campaign API / GPU costs.
    Automatically halts new outbound dialing if spend cap is reached.
    """

    def __init__(
        self,
        daily_ceiling_usd: float = 500.0,
        kill_switch: Optional[KillSwitch] = None
    ) -> None:
        self.daily_ceiling_usd = daily_ceiling_usd
        self.total_daily_spend_usd = 0.0
        self.campaign_spends: Dict[str, CampaignSpend] = {}
        self.kill_switch = kill_switch or KillSwitch.get_instance()

    def set_campaign_ceiling(self, campaign_id: str, ceiling_usd: float) -> None:
        camp_id = (campaign_id or "DEFAULT_CAMPAIGN").strip()
        ceiling = max(0.0, float(ceiling_usd or 0.0))
        if camp_id not in self.campaign_spends:
            self.campaign_spends[camp_id] = CampaignSpend(spend_ceiling_usd=ceiling)
        else:
            self.campaign_spends[camp_id].spend_ceiling_usd = ceiling

    def record_cost(
        self,
        campaign_id: str,
        cost_usd: float,
        cost_type: str = "API_INFERENCE"
    ) -> bool:
        """
        Records an incremental cost.
        Returns True if spend is within budget, False if cap was breached (triggering kill switch).
        """
        camp_id = (campaign_id or "DEFAULT_CAMPAIGN").strip()
        valid_cost = max(0.0, float(cost_usd or 0.0))
        self.total_daily_spend_usd += valid_cost

        if camp_id not in self.campaign_spends:
            self.campaign_spends[camp_id] = CampaignSpend()

        camp = self.campaign_spends[camp_id]
        camp.current_spend_usd += valid_cost

        logger.debug(f"[SPEND GUARD] Added ${cost_usd:.4f} ({cost_type}) to campaign={camp_id}. Total daily: ${self.total_daily_spend_usd:.2f}")

        # 1. Check Global Daily Ceiling
        if self.total_daily_spend_usd >= self.daily_ceiling_usd:
            msg = f"Global daily spend limit reached: ${self.total_daily_spend_usd:.2f} >= ${self.daily_ceiling_usd:.2f}"
            logger.critical(f"[SPEND CEILING BREACH] {msg}. Triggering kill switch!")
            self.kill_switch.trigger(
                role=KillSwitchRole.AUTOMATED_SPEND_GUARD,
                reason=msg
            )
            return False

        # 2. Check Per-Campaign Ceiling
        if camp.current_spend_usd >= camp.spend_ceiling_usd:
            msg = f"Campaign '{camp_id}' spend limit reached: ${camp.current_spend_usd:.2f} >= ${camp.spend_ceiling_usd:.2f}"
            logger.critical(f"[SPEND CEILING BREACH] {msg}. Triggering kill switch!")
            self.kill_switch.trigger(
                role=KillSwitchRole.AUTOMATED_SPEND_GUARD,
                reason=msg
            )
            return False

        return True
