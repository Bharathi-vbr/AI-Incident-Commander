from __future__ import annotations

import json
from typing import Any


def build_incident_analysis_prompt(context: dict[str, Any]) -> str:
    """Construct a concise Claude prompt that enforces JSON incident output."""
    schema = {
        "likely_root_cause": "string",
        "confidence_level": "low|medium|high",
        "impacted_component": "string",
        "business_impact_summary": "string",
        "immediate_remediation_steps": ["string", "string"],
        "long_term_prevention_actions": ["string", "string"],
        "evidence_signals": ["string", "string"],
    }

    return (
        "You are an incident automation assistant for a fintech payment platform. "
        "Analyze the incident context and respond with VALID JSON only. "
        "Do not include markdown, prose outside JSON, or code fences. "
        "Keep each recommendation practical for production SRE teams.\n\n"
        f"Required JSON schema: {json.dumps(schema, ensure_ascii=True)}\n\n"
        f"Incident context: {json.dumps(context, ensure_ascii=True)}"
    )
