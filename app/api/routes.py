from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.metrics import REQUEST_FAILED, render_metrics
from app.services.incident_service import IncidentSummaryService
from app.services.payment_service import (
    DbPoolExhaustedError,
    DuplicateTransactionError,
    InsufficientFundsError,
    PaymentError,
    PaymentService,
    PaymentTimeoutError,
)
from app.services.simulation import VALID_SIMULATION_MODES


router = APIRouter()
logger = logging.getLogger("payment_api.routes")


class PaymentRequest(BaseModel):
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3, default="USD")
    merchant_id: str = Field(min_length=3)
    customer_id: str = Field(min_length=3, default="cust_demo_001")


class SimulationResponse(BaseModel):
    mode: str
    switched_at: str


class SlackNotificationRequest(BaseModel):
    message: str = Field(default="Manual incident update from AI Incident Commander")


class AlertWebhookPayload(BaseModel):
    source: str = Field(default="prometheus")
    severity: str = Field(default="critical")
    alert_name: str = Field(default="payment_api_high_error_rate")
    description: str = Field(default="Automated alert received")
    labels: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    triggered_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ChaosDrillRequest(BaseModel):
    runbook_update: bool = Field(default=True)


@router.get("/dashboard/data")
async def dashboard_data(request: Request) -> dict:
    summary_service: IncidentSummaryService = request.app.state.incident_summary_service
    return await summary_service.build_dashboard_data()


@router.post("/alerts/webhook")
async def alerts_webhook(payload: AlertWebhookPayload, request: Request) -> dict:
    automation_service = request.app.state.automation_service
    result = await automation_service.process_alert(payload.model_dump())
    return {
        "status": "processed",
        "result": result,
    }


@router.post("/drill/chaos")
async def run_chaos_drill(payload: ChaosDrillRequest, request: Request) -> dict:
    chaos_service = request.app.state.chaos_drill_service
    result = await chaos_service.run()

    if payload.runbook_update:
        automation_service = request.app.state.automation_service
        await automation_service.process_alert(
            {
                "source": "chaos-drill",
                "severity": "critical",
                "alert_name": "chaos_drill_completed",
                "description": "Automated chaos drill completed; generating consolidated RCA update",
                "labels": {"team": "sre", "service": "payment-api"},
                "annotations": {"summary": "Chaos drill runbook update"},
                "triggered_at": datetime.now(UTC).isoformat(),
            }
        )

    return {"status": "completed", "result": result}


@router.post("/pay")
async def pay(payload: PaymentRequest, request: Request) -> dict:
    service: PaymentService = request.app.state.payment_service
    simulation = request.app.state.simulation
    transaction_id = request.headers.get("x-transaction-id", f"tx_{uuid.uuid4().hex[:12]}")

    try:
        result = await service.process_payment(
            amount=payload.amount,
            currency=payload.currency.upper(),
            merchant_id=payload.merchant_id,
            customer_id=payload.customer_id,
            transaction_id=transaction_id,
        )
        return {
            "transaction_id": transaction_id,
            "payment_id": result.payment_id,
            "status": result.status,
            "outcome": result.outcome,
            "duration_ms": round(result.duration_ms, 2),
            "simulation_mode": result.simulation_mode,
            "processor": result.processor,
            "mocked": True,
        }
    except InsufficientFundsError as exc:
        REQUEST_FAILED.labels(endpoint="/pay", error_type="insufficient_funds", mode=simulation.mode).inc()
        raise HTTPException(status_code=402, detail={"transaction_id": transaction_id, "error": str(exc), "error_type": "insufficient_funds"})
    except DuplicateTransactionError as exc:
        REQUEST_FAILED.labels(endpoint="/pay", error_type="duplicate_transaction", mode=simulation.mode).inc()
        raise HTTPException(status_code=409, detail={"transaction_id": transaction_id, "error": str(exc), "error_type": "duplicate_transaction"})
    except DbPoolExhaustedError as exc:
        REQUEST_FAILED.labels(endpoint="/pay", error_type="db_pool_exhausted", mode=simulation.mode).inc()
        logger.warning(
            "db_pool_exhausted",
            extra={
                "transaction_id": transaction_id,
                "endpoint": "/pay",
                "customer_id": payload.customer_id,
                "error_type": "db_pool_exhausted",
                "latency_ms": 0,
                "incident_mode": simulation.mode,
                "event": "db_pool_exhausted",
            },
        )
        raise HTTPException(status_code=503, detail={"transaction_id": transaction_id, "error": str(exc), "error_type": "db_pool_exhausted"})
    except PaymentTimeoutError as exc:
        REQUEST_FAILED.labels(endpoint="/pay", error_type="downstream_timeout", mode=simulation.mode).inc()
        logger.warning(
            "downstream_timeout",
            extra={
                "transaction_id": transaction_id,
                "endpoint": "/pay",
                "customer_id": payload.customer_id,
                "error_type": "downstream_timeout",
                "latency_ms": 0,
                "incident_mode": simulation.mode,
                "event": "downstream_timeout",
            },
        )
        raise HTTPException(status_code=504, detail={"transaction_id": transaction_id, "error": str(exc), "error_type": "downstream_timeout"})
    except PaymentError as exc:
        REQUEST_FAILED.labels(endpoint="/pay", error_type="payment_error", mode=simulation.mode).inc()
        logger.error(
            "payment_error",
            extra={
                "transaction_id": transaction_id,
                "endpoint": "/pay",
                "customer_id": payload.customer_id,
                "error_type": "payment_error",
                "latency_ms": 0,
                "incident_mode": simulation.mode,
                "event": "payment_error",
            },
        )
        raise HTTPException(status_code=500, detail={"transaction_id": transaction_id, "error": str(exc), "error_type": "payment_error"})


@router.get("/health")
async def health(request: Request) -> dict:
    redis_client: Redis = request.app.state.redis
    simulation = request.app.state.simulation
    try:
        pong = await redis_client.ping()
    except Exception as exc:
        return {
            "status": "degraded",
            "app": "payment-api",
            "mode": simulation.mode,
            "redis": f"error: {exc}",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    return {
        "status": "ok",
        "app": "payment-api",
        "mode": simulation.mode,
        "redis": "ok" if pong else "unhealthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/metrics")
async def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


@router.post("/simulate/{mode}", response_model=SimulationResponse)
async def simulate(mode: str, request: Request) -> SimulationResponse:
    simulation = request.app.state.simulation
    if mode not in VALID_SIMULATION_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Use one of: {sorted(VALID_SIMULATION_MODES)}")

    simulation.set_mode(mode)
    logger.info(
        "simulation_mode_changed",
        extra={
            "transaction_id": "system",
            "endpoint": "/simulate",
            "customer_id": "system",
            "error_type": "",
            "latency_ms": 0,
            "incident_mode": mode,
            "event": "simulation_mode_changed",
        },
    )
    return SimulationResponse(mode=mode, switched_at=datetime.now(UTC).isoformat())


@router.get("/incident/summary")
async def incident_summary(request: Request) -> dict:
    summary_service: IncidentSummaryService = request.app.state.incident_summary_service
    return await summary_service.build_summary()


@router.post("/notifications/slack/test")
async def slack_test_notification(payload: SlackNotificationRequest, request: Request) -> dict:
    slack_notifier = request.app.state.slack_notifier
    return await slack_notifier.send_notification(message=payload.message, title="AI Incident Commander - Test")


@router.post("/notifications/slack/incident")
async def slack_incident_notification(request: Request) -> dict:
    summary_service: IncidentSummaryService = request.app.state.incident_summary_service
    slack_notifier = request.app.state.slack_notifier

    summary = await summary_service.build_dashboard_data()
    message = (
        f"Mode: {summary.get('current_incident_mode')}\n"
        f"Scenario: {summary.get('scenario')}\n"
        f"Error Count: {summary.get('recent_error_count')}\n"
        f"Error Rate: {summary.get('error_rate_percent')}%\n"
        f"p95 Latency: {summary.get('p95_latency_seconds')}s\n"
        f"Remediation: {summary.get('recommended_remediation')}"
    )
    result = await slack_notifier.send_notification(message=message, title="AI Incident Commander - Incident Update")
    return {
        "notification": result,
        "summary_snapshot": {
            "mode": summary.get("current_incident_mode"),
            "scenario": summary.get("scenario"),
            "errors": summary.get("recent_error_count"),
            "p95_latency_seconds": summary.get("p95_latency_seconds"),
        },
    }
