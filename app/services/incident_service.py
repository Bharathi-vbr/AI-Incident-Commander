from __future__ import annotations

import json
import logging
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.metrics import INCIDENT_THRESHOLD_BREACH, render_metrics
from app.services.claude_summarizer import ClaudeIncidentSummarizer
from app.services.simulation import SimulationEngine


class IncidentSummaryService:
    def __init__(self, settings: Settings, simulation: SimulationEngine, summarizer: ClaudeIncidentSummarizer) -> None:
        self.settings = settings
        self.simulation = simulation
        self.summarizer = summarizer
        self.logger = logging.getLogger("payment_api.incident")

    async def build_summary(self) -> dict[str, Any]:
        snapshot = self.simulation.snapshot
        metrics = self._read_metrics_snapshot()
        log_events = self._read_recent_log_events(limit=160)
        scenario = self._infer_scenario(metrics, snapshot.failed_payments)
        incident_signal = self._evaluate_incident_signal(metrics)

        context = {
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": self.simulation.mode,
            "scenario": scenario,
            "snapshot": {
                "mode_switches": snapshot.mode_switches,
                "successful_payments": snapshot.successful_payments,
                "failed_payments": snapshot.failed_payments,
                "db_pool_exhausted_count": snapshot.db_pool_exhausted_count,
                "timeout_count": snapshot.timeout_count,
                "insufficient_funds_count": snapshot.insufficient_funds_count,
                "duplicate_transaction_count": snapshot.duplicate_transaction_count,
            },
            "metrics": metrics,
            "incident_signal": incident_signal,
            "recent_log_evidence": log_events,
            "recent_events": list(snapshot.recent_events)[:12],
        }

        ai_summary = await self.summarizer.summarize(context)
        self.logger.info(
            "incident_summary_generated",
            extra={
                "transaction_id": "system",
                "endpoint": "/incident/summary",
                "customer_id": "system",
                "error_type": "",
                "latency_ms": 0,
                "incident_mode": self.simulation.mode,
                "event": "incident_summary_generated",
            },
        )

        return {
            "generated_at": context["generated_at"],
            "mode": self.simulation.mode,
            "scenario": scenario,
            "snapshot": context["snapshot"],
            "metrics": metrics,
            "incident_signal": incident_signal,
            "recent_log_evidence": log_events,
            "ai_summary": ai_summary,
        }

    async def build_dashboard_data(self) -> dict[str, Any]:
        summary = await self.build_summary()
        ai_text = str(summary.get("ai_summary", {}).get("summary", "")).strip()
        failure_types = self._top_failure_types(summary.get("recent_log_evidence", []))

        signal = summary.get("incident_signal", {})
        requests_total = float(summary.get("metrics", {}).get("requests_total", 0.0))

        return {
            "generated_at": summary.get("generated_at"),
            "current_incident_mode": summary.get("mode"),
            "scenario": summary.get("scenario"),
            "recent_error_count": summary.get("snapshot", {}).get("failed_payments", 0),
            "p95_latency_seconds": summary.get("metrics", {}).get("payment_latency_p95_seconds", 0.0),
            "requests_total": requests_total,
            "error_rate_percent": signal.get("error_rate_percent", 0.0),
            "failure_types": failure_types,
            "incident_likely": signal.get("incident_likely", False),
            "breached_signals": signal.get("breached_signals", []),
            "latest_ai_incident_summary": ai_text,
            "recommended_remediation": self._extract_recommended_remediation(ai_text),
            "ai_provider": summary.get("ai_summary", {}).get("provider", "unknown"),
            "ai_mocked": summary.get("ai_summary", {}).get("mocked", True),
            "metrics_snapshot": summary.get("metrics", {}),
            "incident_signal": summary.get("incident_signal", {}),
            "recent_log_evidence": summary.get("recent_log_evidence", [])[:25],
        }

    def _read_recent_log_events(self, limit: int = 120) -> list[dict[str, Any]]:
        log_path = Path(self.settings.log_file)
        if not log_path.exists():
            return []

        lines: deque[str] = deque(maxlen=limit)
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                lines.append(line)

        interesting: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            error_type = str(payload.get("error_type", "")).strip()
            level = str(payload.get("level", ""))
            status = int(payload.get("status", 0)) if str(payload.get("status", "")).isdigit() else 0

            if error_type or level in {"ERROR", "WARNING"} or status >= 500:
                interesting.append(
                    {
                        "timestamp": payload.get("timestamp", ""),
                        "event": payload.get("event", payload.get("message", "")),
                        "error_type": error_type,
                        "status": status,
                        "message": payload.get("message", ""),
                    }
                )

            if len(interesting) >= 40:
                break

        return interesting

    def _read_metrics_snapshot(self) -> dict[str, float]:
        payload, _ = render_metrics()
        text = payload.decode("utf-8")

        targets = {
            "payment_api_requests_total": 0.0,
            "payment_api_failed_requests_total": 0.0,
            "payment_api_payment_latency_seconds_sum": 0.0,
            "payment_api_payment_latency_seconds_count": 0.0,
            "payment_api_db_pool_exhausted_total": 0.0,
            "payment_api_timeout_total": 0.0,
        }
        latency_buckets: dict[str, float] = {}

        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue

            if line.startswith("payment_api_payment_latency_seconds_bucket"):
                try:
                    metric_label, value = line.rsplit(" ", 1)
                    le = metric_label.split('le="')[1].split('"')[0]
                    latency_buckets[le] = latency_buckets.get(le, 0.0) + float(value)
                except (IndexError, ValueError):
                    continue
                continue

            for metric_name in list(targets.keys()):
                if line.startswith(metric_name):
                    try:
                        value = float(line.split(" ")[-1])
                        targets[metric_name] += value
                    except ValueError:
                        continue

        latency_avg = 0.0
        if targets["payment_api_payment_latency_seconds_count"] > 0:
            latency_avg = targets["payment_api_payment_latency_seconds_sum"] / targets["payment_api_payment_latency_seconds_count"]

        latency_p95 = self._estimate_p95_latency(latency_buckets)
        failed_requests_total = targets["payment_api_failed_requests_total"]
        requests_total = targets["payment_api_requests_total"]
        error_rate = (failed_requests_total / requests_total * 100.0) if requests_total > 0 else 0.0

        return {
            "requests_total": round(requests_total, 2),
            "failed_requests_total": round(failed_requests_total, 2),
            "error_rate_percent": round(error_rate, 2),
            "payment_latency_avg_seconds": round(latency_avg, 4),
            "payment_latency_p95_seconds": round(latency_p95, 4),
            "db_pool_exhausted_total": round(targets["payment_api_db_pool_exhausted_total"], 2),
            "timeout_total": round(targets["payment_api_timeout_total"], 2),
        }

    def _evaluate_incident_signal(self, metrics: dict[str, float]) -> dict[str, Any]:
        breached_signals: list[str] = []

        if metrics["error_rate_percent"] >= self.settings.alert_error_rate_threshold_percent:
            breached_signals.append("error_rate")
        if metrics["payment_latency_p95_seconds"] >= self.settings.alert_p95_latency_threshold_seconds:
            breached_signals.append("p95_latency")
        if metrics["timeout_total"] >= self.settings.alert_timeout_threshold:
            breached_signals.append("timeout_count")
        if metrics["db_pool_exhausted_total"] >= self.settings.alert_db_exhausted_threshold:
            breached_signals.append("db_pool_exhausted_count")

        for signal in breached_signals:
            INCIDENT_THRESHOLD_BREACH.labels(signal=signal).inc()

        return {
            "incident_likely": len(breached_signals) > 0,
            "breached_signals": breached_signals,
            "error_rate_percent": metrics["error_rate_percent"],
            "p95_latency_seconds": metrics["payment_latency_p95_seconds"],
        }

    def _estimate_p95_latency(self, buckets: dict[str, float]) -> float:
        if not buckets:
            return 0.0

        total_count = buckets.get("+Inf", 0.0)
        if total_count <= 0:
            return 0.0

        target = total_count * 0.95
        finite_pairs: list[tuple[float, float]] = []
        for le, count in buckets.items():
            if le == "+Inf":
                continue
            try:
                finite_pairs.append((float(le), count))
            except ValueError:
                continue

        finite_pairs.sort(key=lambda item: item[0])
        if not finite_pairs:
            return 0.0

        for bucket_limit, cumulative_count in finite_pairs:
            if cumulative_count >= target:
                return bucket_limit

        return finite_pairs[-1][0]

    def _infer_scenario(self, metrics: dict[str, float], failed_payments: int) -> str:
        mode = self.simulation.mode
        if mode == "timeout_storm":
            return "Dependency Timeout Storm"
        if mode == "db_pool_exhausted":
            return "Database Pool Exhaustion"
        if mode == "error_spike":
            return "Payment Validation/Error Spike"
        if mode == "latency_spike":
            return "Payment Latency Spike"

        if metrics["timeout_total"] > 0 or metrics["db_pool_exhausted_total"] > 0 or failed_payments > 0:
            return "Post-Incident Stabilization"

        return "Steady-State Healthy Traffic"

    def _extract_recommended_remediation(self, summary_text: str) -> str:
        if not summary_text:
            return "Continue monitoring key SLOs and keep incident mode at normal."

        lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
        immediate_section = False
        remediation_lines: list[str] = []

        for line in lines:
            lower_line = line.lower()
            if "immediate" in lower_line and ("mitigation" in lower_line or "remediation" in lower_line):
                immediate_section = True
                continue

            if immediate_section and (line.startswith("##") or line.startswith("5)") or "preventive" in lower_line):
                break

            if immediate_section:
                remediation_lines.append(line.lstrip("-• "))

        if remediation_lines:
            return " ".join(remediation_lines[:2])

        return "Switch to normal mode, reduce traffic pressure, and validate recovery with p95/error-rate thresholds."

    def _top_failure_types(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: Counter[str] = Counter()
        for event in events:
            event_name = str(event.get("error_type") or event.get("event") or "unknown").strip() or "unknown"
            counts[event_name] += 1

        return [{"type": event_type, "count": count} for event_type, count in counts.most_common(5)]
