from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from app.config import Settings
from app.services.incident_service import IncidentSummaryService
from app.services.simulation import SimulationEngine


class ContextCollector:
    """Aggregates operational context used by automation-grade incident analysis."""

    def __init__(
        self,
        settings: Settings,
        simulation: SimulationEngine,
        incident_summary_service: IncidentSummaryService,
        redis_client: Redis,
    ) -> None:
        self.settings = settings
        self.simulation = simulation
        self.incident_summary_service = incident_summary_service
        self.redis = redis_client

    async def collect(self, alert_payload: dict[str, Any]) -> dict[str, Any]:
        signal = await self.incident_summary_service.build_dashboard_data()
        backend = await self._backend_context()

        return {
            "collected_at": datetime.now(UTC).isoformat(),
            "alert": alert_payload,
            "incident_signal": signal,
            "deployment": self._deployment_context(),
            "config": self._configuration_context(),
            "backend_connectivity": backend,
            "trace_patterns": self._trace_patterns(signal),
        }

    async def _backend_context(self) -> dict[str, Any]:
        try:
            redis_ok = bool(await self.redis.ping())
            redis_status = "ok" if redis_ok else "unhealthy"
        except Exception as exc:
            redis_status = f"error: {exc}"

        return {
            "redis": redis_status,
            "simulation_mode": self.simulation.mode,
        }

    def _deployment_context(self) -> dict[str, Any]:
        def run_git(args: list[str]) -> str:
            try:
                return subprocess.check_output(["git", *args], text=True).strip()
            except Exception:
                return "unavailable"

        return {
            "branch": run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
            "commit": run_git(["rev-parse", "--short", "HEAD"]),
            "recent_commits": run_git(["log", "-n", "5", "--pretty=format:%h|%s|%cr"]),
        }

    def _configuration_context(self) -> dict[str, Any]:
        return {
            "request_timeout_seconds": self.settings.request_timeout_seconds,
            "db_pool_size": self.settings.db_pool_size,
            "default_simulation_mode": self.settings.default_simulation_mode,
            "alert_thresholds": {
                "error_rate_percent": self.settings.alert_error_rate_threshold_percent,
                "p95_latency_seconds": self.settings.alert_p95_latency_threshold_seconds,
                "timeout_count": self.settings.alert_timeout_threshold,
                "db_exhausted_count": self.settings.alert_db_exhausted_threshold,
            },
        }

    def _trace_patterns(self, signal: dict[str, Any]) -> dict[str, Any]:
        return {
            "scenario": signal.get("scenario", "unknown"),
            "error_rate_percent": float(signal.get("error_rate_percent", 0.0)),
            "p95_latency_seconds": float(signal.get("p95_latency_seconds", 0.0)),
            "recent_error_count": int(signal.get("recent_error_count", 0)),
            "incident_likely": bool(signal.get("incident_likely", False)),
            "breached_signals": signal.get("breached_signals", []),
            "failure_types": signal.get("failure_types", []),
        }
