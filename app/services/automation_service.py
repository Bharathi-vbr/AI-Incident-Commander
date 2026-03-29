from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from app.services.claude_summarizer import ClaudeIncidentSummarizer
from app.services.context_collector import ContextCollector
from app.services.runbook_manager import RunbookManager
from app.services.slack_notifier import SlackNotifier


class AutomationService:
    """Orchestrates alert-driven analysis, notification, and runbook updates."""

    def __init__(
        self,
        collector: ContextCollector,
        summarizer: ClaudeIncidentSummarizer,
        runbook_manager: RunbookManager,
        slack_notifier: SlackNotifier,
    ) -> None:
        self.collector = collector
        self.summarizer = summarizer
        self.runbook_manager = runbook_manager
        self.slack_notifier = slack_notifier

    async def process_alert(self, alert_payload: dict[str, Any]) -> dict[str, Any]:
        context = await self.collector.collect(alert_payload)
        analysis = await self.summarizer.analyze_incident(context)

        runbook_paths = self.runbook_manager.append_incident_update(
            alert_payload=alert_payload,
            context=context,
            analysis=analysis,
        )

        analysis_data = analysis.get("analysis", {})
        message = (
            f"Alert: {alert_payload.get('alert_name', 'unknown')}\n"
            f"Severity: {alert_payload.get('severity', 'unknown')}\n"
            f"Likely Root Cause: {analysis_data.get('likely_root_cause', 'n/a')}\n"
            f"Confidence: {analysis_data.get('confidence_level', 'n/a')}\n"
            f"Impacted Component: {analysis_data.get('impacted_component', 'n/a')}\n"
            f"Business Impact: {analysis_data.get('business_impact_summary', 'n/a')}"
        )
        slack_result = await self.slack_notifier.send_notification(message=message, title="AI Incident Commander - Automated Alert")

        return {
            "processed_at": datetime.now(UTC).isoformat(),
            "alert": alert_payload,
            "incident_signal": context.get("incident_signal", {}),
            "trace_patterns": context.get("trace_patterns", {}),
            "deployment": context.get("deployment", {}),
            "backend_connectivity": context.get("backend_connectivity", {}),
            "analysis": analysis,
            "slack_notification": slack_result,
            "runbook_update": runbook_paths,
        }
