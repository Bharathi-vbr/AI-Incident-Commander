#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from collections import Counter

import httpx


MERCHANTS = [
    "merchant_cardhub",
    "merchant_quickpay",
    "merchant_finstore",
    "merchant_checkout_io",
    "merchant_shoply",
]

CURRENCIES = ["USD", "EUR", "GBP"]


def build_payload() -> dict:
    return {
        "amount": round(random.uniform(5, 350), 2),
        "currency": random.choices(CURRENCIES, weights=[0.8, 0.15, 0.05], k=1)[0],
        "merchant_id": random.choice(MERCHANTS),
    }


async def single_request(client: httpx.AsyncClient, base_url: str) -> tuple[int, float]:
    payload = build_payload()
    start = time.perf_counter()
    try:
        resp = await client.post(f"{base_url}/pay", json=payload)
        latency_ms = (time.perf_counter() - start) * 1000
        return resp.status_code, latency_ms
    except httpx.HTTPError:
        latency_ms = (time.perf_counter() - start) * 1000
        return 599, latency_ms


async def run_load(base_url: str, duration: int, concurrency: int, rps: int) -> None:
    timeout = httpx.Timeout(5.0)
    interval = 1 / max(rps, 1)

    status_counts: Counter[int] = Counter()
    latencies: list[float] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        end_time = time.monotonic() + duration
        workers = set()

        while time.monotonic() < end_time:
            if len(workers) < concurrency:
                workers.add(asyncio.create_task(single_request(client, base_url)))

            done, workers = await asyncio.wait(workers, timeout=0, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                status, latency = task.result()
                status_counts[status] += 1
                latencies.append(latency)

            await asyncio.sleep(interval + random.uniform(0, interval * 0.3))

        if workers:
            done, _ = await asyncio.wait(workers)
            for task in done:
                status, latency = task.result()
                status_counts[status] += 1
                latencies.append(latency)

    total = sum(status_counts.values())
    success = sum(count for code, count in status_counts.items() if 200 <= code < 300)
    failures = total - success

    p50 = statistics.quantiles(latencies, n=100)[49] if len(latencies) >= 100 else (statistics.median(latencies) if latencies else 0)
    p95 = statistics.quantiles(latencies, n=100)[94] if len(latencies) >= 100 else max(latencies) if latencies else 0

    print("\n=== Traffic Generator Summary ===")
    print(f"Total requests: {total}")
    print(f"Successful (2xx): {success}")
    print(f"Failures: {failures}")
    print(f"Latency p50 (ms): {p50:.2f}")
    print(f"Latency p95 (ms): {p95:.2f}")
    print("Status breakdown:")
    for code, count in sorted(status_counts.items()):
        print(f"  {code}: {count}")


async def set_mode(base_url: str, mode: str) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(f"{base_url}/simulate/{mode}")
        resp.raise_for_status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate realistic traffic for payment-api")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Payment API base URL")
    parser.add_argument("--duration", type=int, default=60, help="Duration in seconds")
    parser.add_argument("--concurrency", type=int, default=20, help="Maximum concurrent in-flight requests")
    parser.add_argument("--rps", type=int, default=40, help="Approximate requests per second")
    parser.add_argument(
        "--mode",
        default="",
        choices=["", "normal", "latency_spike", "db_pool_exhausted", "timeout_storm", "error_spike"],
        help="Optional simulation mode to set before running load",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.mode:
        print(f"Setting simulation mode to {args.mode}...")
        await set_mode(args.base_url, args.mode)

    await run_load(
        base_url=args.base_url,
        duration=args.duration,
        concurrency=args.concurrency,
        rps=args.rps,
    )


if __name__ == "__main__":
    asyncio.run(main())
