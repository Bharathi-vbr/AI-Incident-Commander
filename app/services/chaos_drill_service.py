from __future__ import annotations

import asyncio
import random
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.services.incident_service import IncidentSummaryService
from app.services.payment_service import PaymentError, PaymentService
from app.services.simulation import SimulationEngine
from app.services.slack_notifier import SlackNotifier


class ChaosDrillService:
    """Runs staged incident drills and posts stage updates to Slack."""

    def __init__(
        self,
        simulation: SimulationEngine,
        payment_service: PaymentService,
        incident_summary_service: IncidentSummaryService,
        slack_notifier: SlackNotifier,
    ) -> None:
        self.simulation = simulation
        self.payment_service = payment_service
        self.incident_summary_service = incident_summary_service
        self.slack_notifier = slack_notifier

    async def run(self) -> dict[str, Any]:
        started_at = datetime.now(UTC).isoformat()
        stages = [
            {"name": "Latency Spike", "mode": "latency_spike", "requests": 140, "concurrency": 16},
            {"name": "DB Pool Exhaustion", "mode": "db_pool_exhausted", "requests": 180, "concurrency": 20},
            {"name": "Timeout Storm", "mode": "timeout_storm", "requests": 160, "concurrency": 18},
        ]

        await self.slack_notifier.send_notification(
            title="AI Incident Commander - Chaos Drill",
            message=f"Chaos drill started at {started_at}. Stages: latency spike, db pool exhaustion, timeout storm.",
        )

        stage_results: list[dict[str, Any]] = []

        for index, stage in enumerate(stages, start=1):
            self.simulation.set_mode(stage["mode"])
            await self.slack_notifier.send_notification(
                title="AI Incident Commander - Chaos Drill Stage",
                message=f"Stage {index}/{len(stages)} started: {stage['name']} (mode={stage['mode']}).",
            )

            stats = await self._generate_payments(total=stage["requests"], concurrency=stage["concurrency"])
            dashboard = await self.incident_summary_service.build_dashboard_data()

            result = {
                "stage": stage["name"],
                "mode": stage["mode"],
                "load_stats": stats,
                "dashboard_snapshot": {
                    "scenario": dashboard.get("scenario"),
                    "error_rate_percent": dashboard.get("error_rate_percent"),
                    "recent_error_count": dashboard.get("recent_error_count"),
                    "p95_latency_seconds": dashboard.get("p95_latency_seconds"),
                    "breached_signals": dashboard.get("breached_signals", []),
                },
            }
            stage_results.append(result)

            await self.slack_notifier.send_notification(
                title="AI Incident Commander - Chaos Drill Stage Complete",
                message=(
                    f"{stage['name']} completed. "
                    f"Success={stats['success_count']}, Failures={stats['failure_count']}, "
                    f"ErrorRate={dashboard.get('error_rate_percent')}%, "
                    f"Breached={', '.join(dashboard.get('breached_signals', [])) or 'none'}."
                ),
            )
            await asyncio.sleep(1.0)

        self.simulation.set_mode("normal")
        recovery_stats = await self._generate_payments(total=60, concurrency=10)
        recovery_dashboard = await self.incident_summary_service.build_dashboard_data()

        completed_at = datetime.now(UTC).isoformat()
        await self.slack_notifier.send_notification(
            title="AI Incident Commander - Chaos Drill Completed",
            message=(
                f"Chaos drill completed at {completed_at}. "
                f"Recovery mode=normal, Success={recovery_stats['success_count']}, Failures={recovery_stats['failure_count']}. "
                f"Current scenario={recovery_dashboard.get('scenario')}"
            ),
        )

        return {
            "started_at": started_at,
            "completed_at": completed_at,
            "stages": stage_results,
            "recovery": {
                "mode": "normal",
                "load_stats": recovery_stats,
                "dashboard_snapshot": {
                    "scenario": recovery_dashboard.get("scenario"),
                    "error_rate_percent": recovery_dashboard.get("error_rate_percent"),
                    "recent_error_count": recovery_dashboard.get("recent_error_count"),
                    "p95_latency_seconds": recovery_dashboard.get("p95_latency_seconds"),
                    "breached_signals": recovery_dashboard.get("breached_signals", []),
                },
            },
        }

    async def _generate_payments(self, total: int, concurrency: int) -> dict[str, Any]:
        semaphore = asyncio.Semaphore(concurrency)
        status_counts: Counter[str] = Counter()
        error_counts: Counter[str] = Counter()

        async def run_one(_: int) -> None:
            async with semaphore:
                amount = round(random.uniform(10.0, 250.0), 2)
                merchant_id = random.choice(
                    [
                        "merchant_cardhub",
                        "merchant_quickpay",
                        "merchant_checkout_io",
                        "merchant_finstore",
                    ]
                )
                customer_id = f"cust_drill_{random.randint(100, 999)}"
                transaction_id = f"tx_drill_{uuid.uuid4().hex[:10]}"

                try:
                    await self.payment_service.process_payment(
                        amount=amount,
                        currency="USD",
                        merchant_id=merchant_id,
                        customer_id=customer_id,
                        transaction_id=transaction_id,
                    )
                    status_counts["success"] += 1
                except PaymentError as exc:
                    status_counts["failed"] += 1
                    error_counts[getattr(exc, "error_type", "payment_error")] += 1

        await asyncio.gather(*(run_one(i) for i in range(total)))

        return {
            "total_requests": total,
            "success_count": int(status_counts["success"]),
            "failure_count": int(status_counts["failed"]),
            "failure_breakdown": dict(error_counts),
        }
