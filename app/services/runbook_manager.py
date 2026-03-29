from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from app.config import Settings


class RunbookManager:
    """Maintains incident runbook artifacts updated by automation workflows."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runbook_dir = Path(settings.runbook_dir)
        self.runbook_dir.mkdir(parents=True, exist_ok=True)
        self.runbook_file = self.runbook_dir / "incident_runbook.md"
        self.history_file = self.runbook_dir / "incident_history.jsonl"

        if not self.runbook_file.exists():
            self.runbook_file.write_text("# Automated Incident Runbook\n\n")

    def append_incident_update(
        self,
        alert_payload: dict[str, Any],
        context: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, str]:
        timestamp = datetime.now(UTC).isoformat()
        signal = context.get("incident_signal", {})
        details = analysis.get("analysis", {})

        markdown_section = (
            f"## Incident Update - {timestamp}\n\n"
            f"- Alert: {alert_payload.get('alert_name', 'unknown')}\n"
            f"- Severity: {alert_payload.get('severity', 'unknown')}\n"
            f"- Mode: {signal.get('current_incident_mode', 'unknown')}\n"
            f"- Scenario: {signal.get('scenario', 'unknown')}\n"
            f"- Error Rate: {signal.get('error_rate_percent', 0)}%\n"
            f"- p95 Latency: {signal.get('p95_latency_seconds', 0)}s\n"
            f"- Likely Root Cause: {details.get('likely_root_cause', 'n/a')}\n"
            f"- Confidence: {details.get('confidence_level', 'n/a')}\n"
            f"- Impacted Component: {details.get('impacted_component', 'n/a')}\n\n"
            f"### Immediate Remediation\n"
            + "".join([f"- {step}\n" for step in details.get("immediate_remediation_steps", [])])
            + "\n### Long-Term Prevention\n"
            + "".join([f"- {step}\n" for step in details.get("long_term_prevention_actions", [])])
            + "\n"
        )

        with self.runbook_file.open("a", encoding="utf-8") as handle:
            handle.write(markdown_section)

        history_record = {
            "timestamp": timestamp,
            "alert": alert_payload,
            "signal": signal,
            "analysis": details,
        }
        with self.history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(history_record, ensure_ascii=True) + "\n")

        return {
            "runbook_file": str(self.runbook_file),
            "history_file": str(self.history_file),
        }
