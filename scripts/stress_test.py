#!/usr/bin/env python3
"""stress_test.py -- Concurrent /run load test for multi-replica stress environment.

Usage:
    python scripts/stress_test.py --url http://localhost:8000 --concurrency 10 --total 50

Prerequisites:
    docker compose -f docker/docker-compose.stress.yml up --build

This script sends --total POST /run requests with --concurrency in flight at once.
It reports: total requests, successes, failures, avg response time, p95 response time.

NOT a pytest test -- manual use only for stress/performance validation.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import NamedTuple


class RunResult(NamedTuple):
    success: bool
    elapsed: float
    status_code: int
    error: str


TEST_MISSION = {
    "user_input": "Compute 10 + 10 and write the result to /tmp/stress_result.txt",
}


async def run_single(
    client,  # httpx.AsyncClient
    url: str,
    semaphore: asyncio.Semaphore,
) -> RunResult:
    """Send one POST /run request and record timing."""
    async with semaphore:
        start = time.monotonic()
        try:
            resp = await client.post(
                f"{url}/run",
                json=TEST_MISSION,
                timeout=60.0,
            )
            elapsed = time.monotonic() - start
            return RunResult(
                success=resp.status_code in (200, 201, 202),
                elapsed=elapsed,
                status_code=resp.status_code,
                error="",
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            return RunResult(
                success=False,
                elapsed=elapsed,
                status_code=0,
                error=str(exc)[:100],
            )


async def run_stress(url: str, concurrency: int, total: int) -> None:
    """Run the stress test and print a summary report."""
    try:
        import httpx
    except ImportError:
        print("ERROR: httpx not installed. Run: pip install httpx")
        raise SystemExit(1)

    semaphore = asyncio.Semaphore(concurrency)
    print(f"Stress test: {total} requests, {concurrency} concurrent -> {url}")
    print("-" * 60)

    start_all = time.monotonic()
    async with httpx.AsyncClient() as client:
        tasks = [run_single(client, url, semaphore) for _ in range(total)]
        results: list[RunResult] = await asyncio.gather(*tasks)
    total_elapsed = time.monotonic() - start_all

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    elapsed_times = [r.elapsed for r in results]

    success_rate = len(successes) / total * 100
    avg_elapsed = statistics.mean(elapsed_times)
    p95_elapsed = sorted(elapsed_times)[int(len(elapsed_times) * 0.95)]

    print(f"Total:        {total}")
    print(f"Success:      {len(successes)} ({success_rate:.1f}%)")
    print(f"Failure:      {len(failures)}")
    print(f"Avg response: {avg_elapsed:.2f}s")
    print(f"p95 response: {p95_elapsed:.2f}s")
    print(f"Wall time:    {total_elapsed:.2f}s")
    print(f"Throughput:   {total / total_elapsed:.2f} req/s")

    if failures:
        print("\nFailure sample (first 5):")
        for r in failures[:5]:
            print(f"  status={r.status_code} error={r.error!r}")

    # Exit non-zero if success rate < 95%
    if success_rate < 95.0:
        print(f"\nFAIL: success rate {success_rate:.1f}% < 95% threshold")
        raise SystemExit(1)
    print(f"\nPASS: success rate {success_rate:.1f}% >= 95% threshold")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stress test for agentic_workflows API")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent requests in flight (default: 10)",
    )
    parser.add_argument(
        "--total",
        type=int,
        default=50,
        help="Total number of requests to send (default: 50)",
    )
    args = parser.parse_args()
    asyncio.run(run_stress(args.url, args.concurrency, args.total))


if __name__ == "__main__":
    main()
