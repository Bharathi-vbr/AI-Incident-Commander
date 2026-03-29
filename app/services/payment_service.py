from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from app.config import Settings
from app.metrics import DB_POOL_EXHAUSTED, PAYMENT_LATENCY, PAYMENT_OUTCOMES, TIMEOUT_COUNT
from app.services.simulation import (
    PAYMENT_OUTCOME_DB_POOL_EXHAUSTED,
    PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT,
    PAYMENT_OUTCOME_DUPLICATE,
    PAYMENT_OUTCOME_INSUFFICIENT_FUNDS,
    PAYMENT_OUTCOME_SUCCESS,
    SimulationEngine,
)


class PaymentError(Exception):
    error_type = "payment_error"


class DbPoolExhaustedError(PaymentError):
    error_type = PAYMENT_OUTCOME_DB_POOL_EXHAUSTED


class PaymentTimeoutError(PaymentError):
    error_type = PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT


class InsufficientFundsError(PaymentError):
    error_type = PAYMENT_OUTCOME_INSUFFICIENT_FUNDS


class DuplicateTransactionError(PaymentError):
    error_type = PAYMENT_OUTCOME_DUPLICATE


@dataclass
class PaymentResult:
    payment_id: str
    status: str
    duration_ms: float
    simulation_mode: str
    processor: str
    outcome: str


class PaymentService:
    def __init__(self, redis_client: Redis, settings: Settings, simulation: SimulationEngine) -> None:
        self.redis = redis_client
        self.settings = settings
        self.simulation = simulation
        self.logger = logging.getLogger("payment_api.payment")

    async def process_payment(
        self,
        amount: float,
        currency: str,
        merchant_id: str,
        customer_id: str,
        transaction_id: str,
    ) -> PaymentResult:
        mode = self.simulation.mode
        start = time.perf_counter()

        await asyncio.sleep(self.simulation.latency_seconds())
        outcome = self.simulation.draw_payment_outcome()

        with PAYMENT_LATENCY.labels(endpoint="/pay", outcome=outcome, mode=mode).time():
            PAYMENT_OUTCOMES.labels(outcome=outcome, mode=mode).inc()

            if outcome == PAYMENT_OUTCOME_DB_POOL_EXHAUSTED:
                DB_POOL_EXHAUSTED.labels(mode=mode).inc()
                self.simulation.snapshot.db_pool_exhausted_count += 1
                self.simulation.snapshot.failed_payments += 1
                self.simulation.record_event("db_pool_exhausted", {"merchant_id": merchant_id, "customer_id": customer_id})
                raise DbPoolExhaustedError("Database connection pool exhausted while processing payment")

            if outcome == PAYMENT_OUTCOME_DOWNSTREAM_TIMEOUT:
                TIMEOUT_COUNT.labels(mode=mode).inc()
                self.simulation.snapshot.timeout_count += 1
                self.simulation.snapshot.failed_payments += 1
                self.simulation.record_event("downstream_timeout", {"merchant_id": merchant_id, "customer_id": customer_id})
                raise PaymentTimeoutError("Downstream payment processor timeout")

            if outcome == PAYMENT_OUTCOME_INSUFFICIENT_FUNDS:
                self.simulation.snapshot.insufficient_funds_count += 1
                self.simulation.snapshot.failed_payments += 1
                self.simulation.record_event("insufficient_funds", {"merchant_id": merchant_id, "customer_id": customer_id})
                raise InsufficientFundsError("Customer has insufficient funds")

            if outcome == PAYMENT_OUTCOME_DUPLICATE:
                self.simulation.snapshot.duplicate_transaction_count += 1
                self.simulation.snapshot.failed_payments += 1
                self.simulation.record_event("duplicate_transaction", {"merchant_id": merchant_id, "customer_id": customer_id})
                raise DuplicateTransactionError("Duplicate transaction detected")

            payment_id = f"pay_{uuid.uuid4().hex[:12]}"
            await self.redis.hset(
                f"payment:{payment_id}",
                mapping={
                    "amount": amount,
                    "currency": currency,
                    "merchant_id": merchant_id,
                    "customer_id": customer_id,
                    "status": "accepted",
                    "processor": "mocked_processor",
                },
            )
            await self.redis.expire(f"payment:{payment_id}", 3600)

            duration_ms = (time.perf_counter() - start) * 1000
            self.simulation.snapshot.successful_payments += 1
            self.simulation.record_event(
                "payment_accepted",
                {
                    "payment_id": payment_id,
                    "amount": amount,
                    "currency": currency,
                    "merchant_id": merchant_id,
                    "customer_id": customer_id,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            self.logger.info(
                "payment_processed",
                extra={
                    "transaction_id": transaction_id,
                    "endpoint": "/pay",
                    "customer_id": customer_id,
                    "error_type": "",
                    "latency_ms": duration_ms,
                    "incident_mode": mode,
                    "event": "payment_processed",
                    "payment_id": payment_id,
                    "amount": amount,
                    "currency": currency,
                    "merchant_id": merchant_id,
                },
            )

            return PaymentResult(
                payment_id=payment_id,
                status="accepted",
                duration_ms=duration_ms,
                simulation_mode=mode,
                processor="mocked_processor",
                outcome=PAYMENT_OUTCOME_SUCCESS,
            )
