"""
Phase 5 Live Monitoring & Alerting Engine
=========================================
Ongoing post-launch production monitoring:
- Live status evaluator
- Alerting thresholds:
  * Drop rate approaching 3%
  * Latency P95 trending toward 650ms
  * DNC scrub snapshot approaching 31-day staleness
  * Spend approaching daily ceiling
- Real-time terminal output formatting via Rich
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

logger = logging.getLogger("shadow_voice.dashboard")


@dataclass
class AlertNotification:
    level: str  # "WARNING", "CRITICAL"
    alert_name: str
    message: str
    timestamp: float = field(default_factory=time.time)


class ProductionDashboardMonitor:
    """Evaluates telemetry against Phase 5 alerting thresholds."""

    def __init__(
        self,
        latency_p95_warning_ms: float = 600.0,
        latency_p95_critical_ms: float = 650.0,
        abandonment_warning_rate: float = 0.025,
        abandonment_critical_rate: float = 0.030,
        dnc_staleness_warning_days: float = 28.0,
        dnc_staleness_critical_days: float = 31.0
    ) -> None:
        self.latency_p95_warning_ms = latency_p95_warning_ms
        self.latency_p95_critical_ms = latency_p95_critical_ms
        self.abandonment_warning_rate = abandonment_warning_rate
        self.abandonment_critical_rate = abandonment_critical_rate
        self.dnc_staleness_warning_days = dnc_staleness_warning_days
        self.dnc_staleness_critical_days = dnc_staleness_critical_days

        self.active_alerts: List[AlertNotification] = []
        self.console = Console(force_terminal=False, color_system=None)

    def evaluate_telemetry(
        self,
        latency_p95_ms: float,
        regulatory_abandonment_rate: float,
        dnc_age_days: float,
        daily_spend_usd: float,
        daily_spend_limit_usd: float,
        active_sessions_count: int,
        kill_switch_active: bool
    ) -> List[AlertNotification]:
        """Checks thresholds and returns active alerts."""
        alerts = []

        # 1. Latency check
        if latency_p95_ms >= self.latency_p95_critical_ms:
            alerts.append(AlertNotification(
                level="CRITICAL",
                alert_name="LATENCY_SLA_BREACH",
                message=f"P95 latency {latency_p95_ms:.1f}ms exceeds target ceiling of {self.latency_p95_critical_ms:.1f}ms!"
            ))
        elif latency_p95_ms >= self.latency_p95_warning_ms:
            alerts.append(AlertNotification(
                level="WARNING",
                alert_name="LATENCY_TRENDING_HIGH",
                message=f"P95 latency {latency_p95_ms:.1f}ms trending close to {self.latency_p95_critical_ms:.1f}ms ceiling."
            ))

        # 2. Abandonment check
        if regulatory_abandonment_rate >= self.abandonment_critical_rate:
            alerts.append(AlertNotification(
                level="CRITICAL",
                alert_name="REGULATORY_DROP_RATE_LIMIT",
                message=f"Regulatory abandonment rate {regulatory_abandonment_rate * 100:.2f}% breached 3.0% FCC statutory limit!"
            ))
        elif regulatory_abandonment_rate >= self.abandonment_warning_rate:
            alerts.append(AlertNotification(
                level="WARNING",
                alert_name="REGULATORY_DROP_RATE_WARNING",
                message=f"Regulatory abandonment rate {regulatory_abandonment_rate * 100:.2f}% approaching 3.0% cap."
            ))

        # 3. DNC Staleness check
        if dnc_age_days >= self.dnc_staleness_critical_days:
            alerts.append(AlertNotification(
                level="CRITICAL",
                alert_name="DNC_STALENESS_EXPIRED",
                message=f"National DNC snapshot is {dnc_age_days:.1f} days old (exceeds 31-day legal freshness limit)!"
            ))
        elif dnc_age_days >= self.dnc_staleness_warning_days:
            alerts.append(AlertNotification(
                level="WARNING",
                alert_name="DNC_STALENESS_WARNING",
                message=f"National DNC snapshot is {dnc_age_days:.1f} days old. Refresh required within {31.0 - dnc_age_days:.1f} days."
            ))

        # 4. Spend check
        safe_spend = max(0.0, float(daily_spend_usd or 0.0))
        safe_limit = max(0.0, float(daily_spend_limit_usd or 0.0))
        spend_pct = (safe_spend / safe_limit) if safe_limit > 0 else 0.0
        if spend_pct >= 0.95:
            alerts.append(AlertNotification(
                level="CRITICAL",
                alert_name="SPEND_CAP_NEAR_EXHAUSTION",
                message=f"Daily spend ${safe_spend:.2f} is at {spend_pct * 100:.1f}% of daily ceiling (${safe_limit:.2f})."
            ))

        # 5. Kill switch state
        if kill_switch_active:
            alerts.append(AlertNotification(
                level="CRITICAL",
                alert_name="KILL_SWITCH_ACTIVE",
                message="System-wide kill switch is ACTIVE! All new outbound dialing is halted."
            ))

        self.active_alerts = alerts
        return alerts

    def render_terminal_summary(
        self,
        latency_p95_ms: float,
        regulatory_abandonment_rate: float,
        active_sessions_count: int,
        daily_spend_usd: float,
        dnc_age_days: float,
        kill_switch_active: bool
    ) -> str:
        """Renders rich formatted production status table."""
        table = Table(title="SHADOW VOICE  -  PRODUCTION STATUS & HEALTH (PHASE 5)")
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Current Value", style="magenta")
        table.add_column("Target / Safe SLA", style="green")
        table.add_column("Health Status", style="bold")

        # P95 latency row
        lat_status = "[bold red]FAIL[/bold red]" if latency_p95_ms > 650.0 else "[bold green]PASS[/bold green]"
        table.add_row("P95 Speech-End-to-Audio Latency", f"{latency_p95_ms:.1f} ms", "< 650 ms", lat_status)

        # Abandonment row
        ab_status = "[bold red]BREACH[/bold red]" if regulatory_abandonment_rate > 0.03 else "[bold green]COMPLIANT[/bold green]"
        table.add_row("Regulatory Abandonment Rate", f"{regulatory_abandonment_rate * 100:.2f}%", "< 3.00%", ab_status)

        # DNC Staleness
        dnc_status = "[bold red]EXPIRED[/bold red]" if dnc_age_days > 31.0 else "[bold green]FRESH[/bold green]"
        table.add_row("National DNC Snapshot Age", f"{dnc_age_days:.1f} days", "<= 31.0 days", dnc_status)

        # Active Lines
        table.add_row("Active Telephony Sessions", str(active_sessions_count), "5 concurrent target", "[blue]ACTIVE[/blue]")

        # Kill Switch
        ks_status = "[bold red]TRIGGERED (HALTED)[/bold red]" if kill_switch_active else "[bold green]CLEAR TO DIAL[/bold green]"
        table.add_row("System Kill Switch", str(kill_switch_active), "CLEAR", ks_status)

        # Daily Spend
        table.add_row("Daily GPU/API Expenditure", f"${daily_spend_usd:.2f}", "< Daily Cap", "[green]OK[/green]")

        with self.console.capture() as capture:
            self.console.print(table)
            if self.active_alerts:
                self.console.print(f"\n[bold yellow]ACTIVE ALERTS ({len(self.active_alerts)}):[/bold yellow]")
                for alert in self.active_alerts:
                    self.console.print(f"  * [{alert.level}] {alert.alert_name}: {alert.message}")
        return capture.get()
