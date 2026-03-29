from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any


class StructuredJsonFormatter(logging.Formatter):
    """Emit strict structured JSON required by the incident automation pipeline."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "payment-api",
            "level": record.levelname,
            "transaction_id": getattr(record, "transaction_id", "system"),
            "endpoint": getattr(record, "endpoint", getattr(record, "path", "")),
            "customer_id": getattr(record, "customer_id", "unknown"),
            "error_type": getattr(record, "error_type", ""),
            "message": record.getMessage(),
            "latency_ms": round(float(getattr(record, "latency_ms", getattr(record, "duration_ms", 0.0))), 2),
            "incident_mode": getattr(record, "incident_mode", getattr(record, "mode", "unknown")),
        }

        # Keep a few extra keys for troubleshooting without breaking the required schema.
        for field in ("event", "status", "method", "payment_id", "amount", "currency", "merchant_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        return json.dumps(payload, ensure_ascii=True)


def configure_logging(log_file: str) -> None:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = StructuredJsonFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
