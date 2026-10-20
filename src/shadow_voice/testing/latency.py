"""
Latency Percentile Instrumentation & Benchmarking
=================================================
Measures and validates:
- STT latency (speech-end to transcript)
- LLM TTFT (prompt to first token)
- TTS first-audio latency (first token to first 20ms audio chunk)
- End-to-End Latency: Speech-End to First-Audio-Playout

Target: P95 speech-end-to-first-audio < 650 ms!
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import numpy as np


@dataclass
class TurnLatencyRecord:
    turn_id: int
    session_id: str
    speech_end_timestamp_ms: float
    stt_ready_timestamp_ms: float
    llm_first_token_timestamp_ms: float
    tts_first_audio_timestamp_ms: float
    first_audio_played_timestamp_ms: float

    @property
    def stt_latency_ms(self) -> float:
        return max(0.0, self.stt_ready_timestamp_ms - self.speech_end_timestamp_ms)

    @property
    def llm_ttft_ms(self) -> float:
        return max(0.0, self.llm_first_token_timestamp_ms - self.stt_ready_timestamp_ms)

    @property
    def tts_first_audio_ms(self) -> float:
        return max(0.0, self.tts_first_audio_timestamp_ms - self.llm_first_token_timestamp_ms)

    @property
    def playout_transit_ms(self) -> float:
        return max(0.0, self.first_audio_played_timestamp_ms - self.tts_first_audio_timestamp_ms)

    @property
    def total_speech_end_to_first_audio_ms(self) -> float:
        return max(0.0, self.first_audio_played_timestamp_ms - self.speech_end_timestamp_ms)


@dataclass
class PercentileDistribution:
    p50: float
    p90: float
    p95: float
    p99: float
    min_ms: float
    max_ms: float
    mean_ms: float
    sample_count: int


@dataclass
class LatencyBenchmarkReport:
    total_turns: int
    e2e_distribution: PercentileDistribution
    stt_distribution: PercentileDistribution
    ttft_distribution: PercentileDistribution
    tts_distribution: PercentileDistribution
    passed_p95_under_650ms: bool


class LatencyTracker:
    """Collects per-turn timing markers and computes statistical distributions."""

    def __init__(self, target_p95_ms: float = 650.0) -> None:
        self.target_p95_ms = target_p95_ms
        self.records: List[TurnLatencyRecord] = []

    def add_record(self, record: TurnLatencyRecord) -> None:
        self.records.append(record)

    def _calc_percentiles(self, values: List[float]) -> PercentileDistribution:
        if not values:
            return PercentileDistribution(0, 0, 0, 0, 0, 0, 0, 0)
        arr = np.array(values)
        return PercentileDistribution(
            p50=float(np.percentile(arr, 50)),
            p90=float(np.percentile(arr, 90)),
            p95=float(np.percentile(arr, 95)),
            p99=float(np.percentile(arr, 99)),
            min_ms=float(np.min(arr)),
            max_ms=float(np.max(arr)),
            mean_ms=float(np.mean(arr)),
            sample_count=len(values)
        )

    def generate_report(self) -> LatencyBenchmarkReport:
        e2e_vals = [r.total_speech_end_to_first_audio_ms for r in self.records]
        stt_vals = [r.stt_latency_ms for r in self.records]
        ttft_vals = [r.llm_ttft_ms for r in self.records]
        tts_vals = [r.tts_first_audio_ms for r in self.records]

        e2e_dist = self._calc_percentiles(e2e_vals)
        passed = e2e_dist.p95 <= self.target_p95_ms and e2e_dist.sample_count > 0

        return LatencyBenchmarkReport(
            total_turns=len(self.records),
            e2e_distribution=e2e_dist,
            stt_distribution=self._calc_percentiles(stt_vals),
            ttft_distribution=self._calc_percentiles(ttft_vals),
            tts_distribution=self._calc_percentiles(tts_vals),
            passed_p95_under_650ms=passed
        )
