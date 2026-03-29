from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


VALID_SIMULATION_MODES = {
    "normal",
    "latency_spike",
    "db_pool_exhausted",
    "timeout_storm",
    "error_spike",
}

PAYMENT_OUTCOME_SUCCESS = "success"
PAYMENT_OUTCOME_INSUFFICIENT_FUNDS = "insufficient_funds"
PAYMENT_OUTCOME_DUPLICATE = "duplicate_transaction"
PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT = "downstream_timeout"
PAYMENT_OUTCOME_DB_POOL_EXHAUSTED = "db_pool_exhausted"


@dataclass
class IncidentSnapshot:
    mode_switches: int = 0
    successful_payments: int = 0
    failed_payments: int = 0
    db_pool_exhausted_count: int = 0
    timeout_count: int = 0
    insufficient_funds_count: int = 0
    duplicate_transaction_count: int = 0
    recent_events: deque[dict] = field(default_factory=lambda: deque(maxlen=50))


class SimulationEngine:
    def __init__(self, mode: str) -> None:
        if mode not in VALID_SIMULATION_MODES:
            mode = "normal"
        self._mode = mode
        self.snapshot = IncidentSnapshot()

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> str:
        if mode not in VALID_SIMULATION_MODES:
            raise ValueError(f"Unsupported simulation mode: {mode}")
        self._mode = mode
        self.snapshot.mode_switches += 1
        self.record_event("mode_switch", {"mode": mode})
        return mode

    def record_event(self, event_type: str, payload: dict) -> None:
        self.snapshot.recent_events.appendleft(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event_type": event_type,
                "payload": payload,
            }
        )

    def draw_payment_outcome(self) -> str:
        """Return a realistic fintech payment outcome based on active incident mode."""
        weights = self._outcome_weights_for_mode(self._mode)
        roll = random.random()
        cumulative = 0.0
        for outcome, weight in weights:
            cumulative += weight
            if roll <= cumulative:
                return outcome
        return PAYMENT_OUTCOME_SUCCESS

    def latency_seconds(self) -> float:
        if self._mode == "latency_spike":
            return random.uniform(0.9, 2.6)
        if self._mode == "timeout_storm":
            return random.uniform(1.8, 3.5)
        if self._mode == "error_spike":
            return random.uniform(0.18, 0.8)
        if self._mode == "db_pool_exhausted":
            return random.uniform(0.1, 0.45)
        return random.uniform(0.02, 0.12)

    def _outcome_weights_for_mode(self, mode: str) -> list[tuple[str, float]]:
        if mode == "latency_spike":
            return [
                (PAYMENT_OUTCOME_SUCCESS, 0.89),
                (PAYMENT_OUTCOME_INSUFFICIENT_FUNDS, 0.03),
                (PAYMENT_OUTCOME_DUPLICATE, 0.02),
                (PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT, 0.05),
                (PAYMENT_OUTCOME_DB_POOL_EXHAUSTED, 0.01),
            ]

        if mode == "db_pool_exhausted":
            return [
                (PAYMENT_OUTCOME_SUCCESS, 0.19),
                (PAYMENT_OUTCOME_INSUFFICIENT_FUNDS, 0.01),
                (PAYMENT_OUTCOME_DUPLICATE, 0.01),
                (PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT, 0.09),
                (PAYMENT_OUTCOME_DB_POOL_EXHAUSTED, 0.70),
            ]

        if mode == "timeout_storm":
            return [
                (PAYMENT_OUTCOME_SUCCESS, 0.20),
                (PAYMENT_OUTCOME_INSUFFICIENT_FUNDS, 0.03),
                (PAYMENT_OUTCOME_DUPLICATE, 0.03),
                (PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT, 0.72),
                (PAYMENT_OUTCOME_DB_POOL_EXHAUSTED, 0.02),
            ]

        if mode == "error_spike":
            return [
                (PAYMENT_OUTCOME_SUCCESS, 0.20),
                (PAYMENT_OUTCOME_INSUFFICIENT_FUNDS, 0.40),
                (PAYMENT_OUTCOME_DUPLICATE, 0.20),
                (PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT, 0.15),
                (PAYMENT_OUTCOME_DB_POOL_EXHAUSTED, 0.05),
            ]

        return [
            (PAYMENT_OUTCOME_SUCCESS, 0.96),
            (PAYMENT_OUTCOME_INSUFFICIENT_FUNDS, 0.02),
            (PAYMENT_OUTCOME_DUPLICATE, 0.015),
            (PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT, 0.004),
            (PAYMENT_OUTCOME_DB_POOL_EXHAUSTED, 0.001),
        ]
