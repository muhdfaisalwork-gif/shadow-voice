"""
Campaign Script Registry & Prompt Versioning
=============================================
Manages versioned campaign scripts, system prompts, and approved pricing/commitments.
"""

from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Set


@dataclass
class CampaignScriptConfig:
    campaign_id: str
    version_id: str
    agent_name: str
    company_name: str
    opening_greeting: str
    approved_pricing: Set[str] = field(default_factory=set)
    transfer_extension: str = "8300"
    created_at: float = 0.0
    approved_by: str = ""
    is_active: bool = True

    @property
    def config_hash(self) -> str:
        content = f"{self.campaign_id}:{self.version_id}:{self.opening_greeting}"
        return hashlib.sha256(content.encode()).hexdigest()[:12]


class ScriptRegistry:
    """Registry maintaining active and historical campaign script versions."""

    def __init__(self) -> None:
        self._campaigns: Dict[str, CampaignScriptConfig] = {}
        self._init_defaults()

    def _init_defaults(self) -> None:
        default_config = CampaignScriptConfig(
            campaign_id="DEFAULT_SALES_V1",
            version_id="v2.1.0-pinned",
            agent_name="Jordan",
            company_name="Shadow Voice",
            opening_greeting="Hi, this is Jordan calling from Shadow Voice  -  do you have a quick minute?",
            approved_pricing={"usage-based", "custom quote", "per-connected-minute"},
            transfer_extension="8300",
            approved_by="PM_Faisal"
        )
        self.register_campaign(default_config)

    def register_campaign(self, config: CampaignScriptConfig) -> None:
        self._campaigns[config.campaign_id] = config

    def get_campaign(self, campaign_id: Optional[str]) -> CampaignScriptConfig:
        cid = campaign_id or "DEFAULT_SALES_V1"
        return self._campaigns.get(cid, self._campaigns["DEFAULT_SALES_V1"])
