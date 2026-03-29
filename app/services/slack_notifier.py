from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings


class SlackNotifier:
    """Sends incident notifications to Slack webhook, with local mock fallback."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger("payment_api.slack")

    async def send_notification(self, message: str, title: str = "AI Incident Commander") -> dict[str, Any]:
        webhook_url = self.settings.slack_webhook_url.strip()
        payload = {
            "text": f"*{title}*\n{message}",
        }

        if not webhook_url:
            return {
                "sent": False,
                "mocked": True,
                "reason": "SLACK_WEBHOOK_URL is not configured",
                "preview": payload["text"][:500],
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
            return {
                "sent": True,
                "mocked": False,
                "reason": "",
                "preview": payload["text"][:500],
            }
        except Exception as exc:
            self.logger.warning("slack_notification_failed", extra={"event": "slack_notification_failed", "error": str(exc)})
            return {
                "sent": False,
                "mocked": True,
                "reason": f"Slack webhook failed: {exc}",
                "preview": payload["text"][:500],
            }
