"""
Prometheus Production Metrics Exporter
======================================
Fulfills Phase 5 Ongoing Monitoring:
- P50, P95, P99 Latency percentiles
- Technical drop rate vs Regulatory abandonment rate
- Kill-switch status
- DNC snapshot freshness
- Spend tracking vs daily ceiling
- Playout buffer & Jitter buffer health
"""

from __future__ import annotations
import logging
from typing import Optional
from prometheus_client import Gauge, Counter, CollectorRegistry, generate_latest

logger = logging.getLogger("shadow_voice.metrics")


class ShadowVoiceMetrics:
    """Prometheus metrics collector for Shadow Voice platform."""

    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry(auto_describe=True)

        # Latency metrics
        self.latency_p50 = Gauge("shadow_voice_latency_p50_ms", "Median speech-end-to-first-audio latency in ms", registry=self.registry)
        self.latency_p95 = Gauge("shadow_voice_latency_p95_ms", "95th percentile speech-end-to-first-audio latency in ms", registry=self.registry)
        self.latency_p99 = Gauge("shadow_voice_latency_p99_ms", "99th percentile speech-end-to-first-audio latency in ms", registry=self.registry)

        # Call health & Regulatory drop rates
        self.regulatory_abandonment_rate = Gauge("shadow_voice_regulatory_abandonment_rate", "Regulatory abandonment rate (FCC limit 3.0%)", registry=self.registry)
        self.technical_failure_rate = Gauge("shadow_voice_technical_failure_rate", "Technical transport failure rate", registry=self.registry)
        self.active_sessions = Gauge("shadow_voice_active_sessions", "Number of currently active concurrent calls", registry=self.registry)

        # Compliance & Security
        self.kill_switch_active = Gauge("shadow_voice_kill_switch_active", "1 if kill switch is triggered, 0 otherwise", registry=self.registry)
        self.dnc_snapshot_age_days = Gauge("shadow_voice_dnc_snapshot_age_days", "Age of National DNC snapshot in days (max 31)", registry=self.registry)
        self.daily_spend_usd = Gauge("shadow_voice_daily_spend_usd", "Total API and GPU spend today in USD", registry=self.registry)

        # Events & Counters
        self.total_calls = Counter("shadow_voice_calls_total", "Total call sessions processed", registry=self.registry)
        self.barge_in_events = Counter("shadow_voice_barge_in_events_total", "Total user speech barge-in interruptions", registry=self.registry)
        self.guardrail_triggers = Counter("shadow_voice_guardrail_triggers_total", "Total runtime output guardrail blocks", registry=self.registry)
        self.jitter_buffer_underflows = Counter("shadow_voice_jitter_buffer_underflows_total", "Ingress jitter buffer underflow frames", registry=self.registry)

    def export_prometheus_text(self) -> str:
        """Returns Prometheus text formatted metrics payload."""
        return generate_latest(self.registry).decode("utf-8")
