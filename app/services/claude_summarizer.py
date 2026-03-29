from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import Settings
from app.services.prompt_builder import build_incident_analysis_prompt


class ClaudeIncidentSummarizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger("payment_api.claude")

    async def summarize(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.claude_api_key.strip():
            return self._mock_summary(context, "CLAUDE_API_KEY is not configured")

        prompt = self._build_summary_prompt(context)
        payload = {
            "model": self.settings.claude_model,
            "max_tokens": 700,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.settings.claude_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=14.0) as client:
                response = await client.post(self.settings.claude_api_url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
                text = self._extract_message_text(body)
                if not text:
                    return self._mock_summary(context, "Claude response did not include summary text")
                return {
                    "provider": "claude",
                    "model": self.settings.claude_model,
                    "mocked": False,
                    "summary": text,
                    "fallback_reason": "",
                }
        except Exception as exc:
            self.logger.warning("claude_summary_failed", extra={"event": "claude_summary_failed", "error": str(exc)})
            return self._mock_summary(context, f"Claude API error: {exc}")

    async def analyze_incident(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.claude_api_key.strip():
            return self._mock_structured_analysis("CLAUDE_API_KEY is not configured", context)

        prompt = build_incident_analysis_prompt(context)
        payload = {
            "model": self.settings.claude_model,
            "max_tokens": 900,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.settings.claude_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=18.0) as client:
                response = await client.post(self.settings.claude_api_url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
                text = self._extract_message_text(body)

            parsed = self._parse_json_payload(text)
            parsed.setdefault("likely_root_cause", "Insufficient context from model")
            parsed.setdefault("confidence_level", "medium")
            parsed.setdefault("impacted_component", "payment-api")
            parsed.setdefault("business_impact_summary", "Potential transaction degradation")
            parsed.setdefault("immediate_remediation_steps", ["Reduce blast radius", "Validate recovery metrics"])
            parsed.setdefault("long_term_prevention_actions", ["Strengthen alerting", "Harden dependency protections"])
            parsed.setdefault("evidence_signals", ["Recent failures observed"])

            return {
                "provider": "claude",
                "model": self.settings.claude_model,
                "mocked": False,
                "analysis": parsed,
                "fallback_reason": "",
            }
        except Exception as exc:
            self.logger.warning("claude_structured_analysis_failed", extra={"event": "claude_structured_analysis_failed", "error": str(exc)})
            return self._mock_structured_analysis(f"Claude API error: {exc}", context)

    def _extract_message_text(self, payload: dict[str, Any]) -> str:
        blocks = payload.get("content", [])
        if not blocks:
            return ""
        lines: list[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                lines.append(str(block.get("text", "")).strip())
        return "\n".join([line for line in lines if line]).strip()

    def _parse_json_payload(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        return json.loads(cleaned)

    def _build_summary_prompt(self, context: dict[str, Any]) -> str:
        return (
            "You are an SRE incident commander for a fintech payments platform. "
            "Create a concise production-style incident summary with likely root cause, impact, immediate mitigation, "
            "and next preventive actions. Use concrete evidence only from the provided context.\n\n"
            "Output format:\n"
            "1) Incident Title\n"
            "2) RCA Summary\n"
            "3) Customer Impact\n"
            "4) Immediate Mitigations\n"
            "5) Preventive Follow-ups\n\n"
            f"Incident context JSON:\n{json.dumps(context, ensure_ascii=True, indent=2)}"
        )

    def _mock_summary(self, context: dict[str, Any], reason: str) -> dict[str, Any]:
        scenario = context.get("scenario", "Unknown")
        mode = context.get("mode", "unknown")
        metrics = context.get("metrics", {})
        failures = context.get("snapshot", {}).get("failed_payments", 0)
        timeouts = metrics.get("timeout_total", 0)
        db_exhausted = metrics.get("db_pool_exhausted_total", 0)

        summary = (
            f"1) Incident Title\n"
            f"{scenario} in payment-api (mode={mode})\n\n"
            f"2) RCA Summary\n"
            f"Observed elevated payment failures ({failures}) with supporting telemetry in logs and metrics. "
            f"Timeout events={timeouts}, DB pool exhaustion events={db_exhausted}. "
            f"The active simulation mode indicates a controlled fault injection scenario for SRE triage practice.\n\n"
            f"3) Customer Impact\n"
            f"A subset of payment attempts returned failures or high latency, increasing checkout risk for merchants.\n\n"
            f"4) Immediate Mitigations\n"
            f"Switch simulation to normal mode, reduce traffic rate, and verify stabilization via /health, /metrics, and incident counters.\n\n"
            f"5) Preventive Follow-ups\n"
            f"Add alert thresholds for failure ratio, enforce timeout budgets, and add runbooks for rapid mode-based diagnosis."
        )

        return {
            "provider": "mocked_claude",
            "model": "mocked",
            "mocked": True,
            "summary": summary,
            "fallback_reason": reason,
        }

    def _mock_structured_analysis(self, reason: str, context: dict[str, Any]) -> dict[str, Any]:
        signal = context.get("incident_signal", {})
        scenario = signal.get("scenario", context.get("mode", "unknown"))
        return {
            "provider": "mocked_claude",
            "model": "mocked",
            "mocked": True,
            "analysis": {
                "likely_root_cause": f"Detected {scenario} based on local telemetry thresholds and recent failures",
                "confidence_level": "medium",
                "impacted_component": "payment-api / dependency-path",
                "business_impact_summary": "Transaction failure risk increased and customer checkout reliability may be degraded.",
                "immediate_remediation_steps": [
                    "Switch incident mode to normal and reduce traffic pressure",
                    "Validate timeout/db-exhaustion counters and confirm error-rate recovery",
                ],
                "long_term_prevention_actions": [
                    "Define SLO-based alerting with p95 and error-budget thresholds",
                    "Add dependency circuit-breakers and runbook automation checks",
                ],
                "evidence_signals": [
                    f"Error rate: {signal.get('error_rate_percent', 0)}%",
                    f"p95 latency: {signal.get('p95_latency_seconds', 0)}s",
                    f"fallback_reason: {reason}",
                ],
            },
            "fallback_reason": reason,
        }
