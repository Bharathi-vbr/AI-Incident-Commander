from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from app.api.routes import router
from app.config import get_settings
from app.logging_config import configure_logging
from app.metrics import REQUEST_FAILED, REQUEST_TOTAL
from app.services.automation_service import AutomationService
from app.services.claude_summarizer import ClaudeIncidentSummarizer
from app.services.chaos_drill_service import ChaosDrillService
from app.services.context_collector import ContextCollector
from app.services.incident_service import IncidentSummaryService
from app.services.payment_service import PaymentService
from app.services.runbook_manager import RunbookManager
from app.services.simulation import SimulationEngine
from app.services.slack_notifier import SlackNotifier


settings = get_settings()
configure_logging(settings.log_file)
logger = logging.getLogger("payment_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    simulation = SimulationEngine(mode=settings.default_simulation_mode)
    payment_service = PaymentService(redis_client=redis_client, settings=settings, simulation=simulation)
    claude_summarizer = ClaudeIncidentSummarizer(settings=settings)
    incident_summary_service = IncidentSummaryService(
        settings=settings,
        simulation=simulation,
        summarizer=claude_summarizer,
    )
    slack_notifier = SlackNotifier(settings=settings)

    collector = ContextCollector(
        settings=settings,
        simulation=simulation,
        incident_summary_service=incident_summary_service,
        redis_client=redis_client,
    )
    runbook_manager = RunbookManager(settings=settings)
    automation_service = AutomationService(
        collector=collector,
        summarizer=claude_summarizer,
        runbook_manager=runbook_manager,
        slack_notifier=slack_notifier,
    )

    app.state.redis = redis_client
    app.state.simulation = simulation
    app.state.payment_service = payment_service
    app.state.incident_summary_service = incident_summary_service
    app.state.slack_notifier = slack_notifier
    app.state.automation_service = automation_service
    chaos_drill_service = ChaosDrillService(
        simulation=simulation,
        payment_service=payment_service,
        incident_summary_service=incident_summary_service,
        slack_notifier=slack_notifier,
    )
    app.state.chaos_drill_service = chaos_drill_service

    logger.info(
        "application_started",
        extra={
            "transaction_id": "system",
            "endpoint": "/startup",
            "customer_id": "system",
            "error_type": "",
            "latency_ms": 0,
            "incident_mode": settings.default_simulation_mode,
            "event": "application_started",
        },
    )
    try:
        yield
    finally:
        await redis_client.close()
        logger.info(
            "application_stopped",
            extra={
                "transaction_id": "system",
                "endpoint": "/shutdown",
                "customer_id": "system",
                "error_type": "",
                "latency_ms": 0,
                "incident_mode": app.state.simulation.mode,
                "event": "application_stopped",
            },
        )


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/ui", StaticFiles(directory=str(frontend_dist), html=True), name="ui")


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    method = request.method
    simulation_mode = getattr(getattr(request.app.state, "simulation", None), "mode", "unknown")
    customer_id = request.headers.get("x-customer-id", "unknown")
    transaction_id = request.headers.get("x-transaction-id", "system")

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        REQUEST_TOTAL.labels(method=method, path=path, status="500", mode=simulation_mode).inc()
        REQUEST_FAILED.labels(endpoint=path, error_type="unhandled_exception", mode=simulation_mode).inc()
        logger.exception(
            "request_failed",
            extra={
                "transaction_id": transaction_id,
                "endpoint": path,
                "customer_id": customer_id,
                "error_type": "unhandled_exception",
                "latency_ms": duration_ms,
                "incident_mode": simulation_mode,
                "event": "request_failed",
                "method": method,
                "status": 500,
            },
        )
        raise

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    REQUEST_TOTAL.labels(method=method, path=path, status=str(status_code), mode=simulation_mode).inc()

    if status_code >= 500:
        REQUEST_FAILED.labels(endpoint=path, error_type="server_error", mode=simulation_mode).inc()

    logger.info(
        "http_request",
        extra={
            "transaction_id": transaction_id,
            "endpoint": path,
            "customer_id": customer_id,
            "error_type": "" if status_code < 400 else "http_error",
            "latency_ms": duration_ms,
            "incident_mode": simulation_mode,
            "event": "http_request",
            "method": method,
            "status": status_code,
        },
    )
    return response
