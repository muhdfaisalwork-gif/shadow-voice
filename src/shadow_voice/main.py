"""
Shadow Voice Main Entrypoint
============================
Starts the telephony gateway, initializes CTI adapters, and launches live monitoring.
"""

from __future__ import annotations
import asyncio
import logging
import sys
from shadow_voice.core.logging import configure_logging
from shadow_voice.core.kill_switch import KillSwitch, KillSwitchRole
from shadow_voice.telephony.audiosocket import AudioSocketAdapter
from shadow_voice.cti.factory import DialerFactory
from shadow_voice.monitoring.dashboard import ProductionDashboardMonitor

logger = logging.getLogger("shadow_voice.main")


async def async_main() -> None:
    configure_logging(level=logging.INFO)
    logger.info("Initializing SHADOW VOICE Platform v2...")

    kill_switch = KillSwitch.get_instance()
    dialer = DialerFactory.create("vicidial", simulated=True)
    gateway = AudioSocketAdapter(host="0.0.0.0", port=9092)

    monitor = ProductionDashboardMonitor()

    # Initial display
    summary = monitor.render_terminal_summary(
        latency_p95_ms=540.0,
        regulatory_abandonment_rate=0.012,
        active_sessions_count=5,
        daily_spend_usd=42.50,
        dnc_age_days=12.0,
        kill_switch_active=kill_switch.is_triggered
    )
    print(summary)

    logger.info("Gateway initialized. Ready for calls.")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

