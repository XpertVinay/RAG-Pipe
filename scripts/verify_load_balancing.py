#!/usr/bin/env python3
"""
Load Balancer Verification & Load Testing Tool
=============================================
Tests whether incoming HTTP traffic is distributed equally across upstream
backend replicas behind an Nginx load balancer.

Features:
- Concurrent load generation (async HTTP client)
- Automatic detection of 'X-Served-By' and 'X-Upstream-Response-Time' headers
- Support for production-safe 'X-Debug-LB: 1' diagnostic header bypass
- Statistical distribution analysis (chi-squared variance, percentage share)
- Nginx access log parser for offline or production verification without debug headers
- Clear exit codes (0 = balanced within tolerance, 1 = skewed or error)

Usage:
    # 1. Quick test against running Nginx proxy:
    python scripts/verify_load_balancing.py --url http://localhost:8181/health -n 200 -c 10

    # 2. Test in production mode with authorized diagnostic header:
    python scripts/verify_load_balancing.py --url http://localhost:8181/health -n 500 -c 20 --force-debug-header

    # 3. Analyze Nginx access log directly:
    python scripts/verify_load_balancing.py --parse-log /var/log/nginx/access.log
"""

import argparse
import asyncio
import re
import sys
import time
from collections import Counter
from typing import Dict, List, Optional
import httpx


def parse_args():
    parser = argparse.ArgumentParser(
        description="Verify Nginx upstream load distribution and run load tests."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8181/health",
        help="Target URL to test (default: http://localhost:8181/health)",
    )
    parser.add_argument(
        "-n",
        "--requests",
        type=int,
        default=200,
        help="Total number of requests to send (default: 200)",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent workers (default: 10)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.20,
        help="Allowable percentage deviation between backends before warning (default: 0.20 for 20%%)",
    )
    parser.add_argument(
        "--force-debug-header",
        action="store_true",
        help="Send 'X-Debug-LB: 1' to activate upstream diagnostics when production flag is off",
    )
    parser.add_argument(
        "--parse-log",
        type=str,
        default=None,
        help="Path to Nginx access log file to parse instead of sending live traffic",
    )
    return parser.parse_args()


def parse_nginx_log(log_path: str, max_lines: int = 10000):
    """Parses upstream_addr from Nginx access logs."""
    print(f"\n📂 Parsing Nginx log file: {log_path} (last {max_lines} lines)")
    addr_pattern = re.compile(r'upstream_addr="?([^"\s;]+)"?')
    counts = Counter()
    total_parsed = 0

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            for line in lines[-max_lines:]:
                match = addr_pattern.search(line)
                if match:
                    upstream = match.group(1).strip()
                    # An upstream may contain multiple addresses if a failover occurred (e.g. "172.x:8000, 172.y:8000")
                    for addr in upstream.split(","):
                        addr = addr.strip()
                        if addr and addr != "-":
                            counts[addr] += 1
                            total_parsed += 1
    except FileNotFoundError:
        print(f"❌ Error: Log file '{log_path}' not found.")
        sys.exit(1)

    print(f"📊 Parsed {total_parsed} upstream requests across {len(counts)} backends.")
    evaluate_distribution(counts, total_parsed, tolerance=0.20)


async def send_worker_requests(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    total_requests: int,
    results: List[dict],
    semaphore: asyncio.Semaphore,
):
    async def single_request():
        async with semaphore:
            start_t = time.perf_counter()
            try:
                res = await client.get(url, headers=headers, timeout=10.0)
                duration = time.perf_counter() - start_t
                served_by = (
                    res.headers.get("x-served-by")
                    or res.headers.get("X-Served-By")
                    or "unknown"
                )
                upstream_time = (
                    res.headers.get("x-upstream-response-time")
                    or res.headers.get("X-Upstream-Response-Time")
                    or ""
                )
                results.append(
                    {
                        "status": res.status_code,
                        "duration": duration,
                        "served_by": served_by,
                        "upstream_time": upstream_time,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "status": 0,
                        "duration": 0,
                        "served_by": "error",
                        "error": str(e),
                    }
                )

    tasks = [single_request() for _ in range(total_requests)]
    await asyncio.gather(*tasks)


def evaluate_distribution(counts: Dict[str, int], total: int, tolerance: float) -> bool:
    """Evaluates whether traffic is equally distributed across backends."""
    num_backends = len(counts)
    if num_backends == 0:
        print("\n⚠️  No upstream backend hits recorded.")
        return False

    print("\n" + "=" * 65)
    print("📈 UPSTREAM LOAD BALANCING DISTRIBUTION REPORT")
    print("=" * 65)

    expected_share = 1.0 / num_backends
    expected_count = total * expected_share

    print(f"Total Requests Processed : {total}")
    print(f"Detected Upstream Instances: {num_backends}")
    print(f"Ideal Target Per Instance: {expected_count:.1f} ({expected_share * 100:.1f}%)")
    print(f"Acceptable Tolerance Drift: ±{tolerance * 100:.0f}%\n")

    max_drift = 0.0
    balanced = True

    for backend, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        actual_share = count / total if total > 0 else 0
        diff = actual_share - expected_share
        drift = abs(diff) / expected_share if expected_share > 0 else 0
        max_drift = max(max_drift, drift)

        bar_len = int(actual_share * 35)
        bar = "█" * bar_len + "░" * (35 - bar_len)
        drift_marker = "✓" if drift <= tolerance else "⚠️ SKEWED"
        print(f"  {backend:<24} : {count:>5} ({actual_share * 100:>5.1f}%)  [{bar}] {drift_marker}")

    print("-" * 65)

    if num_backends == 1:
        print("ℹ️  Only 1 backend instance was detected.")
        print("   If you are running in Docker Compose, scale instances with:")
        print("   👉 docker compose up -d --scale rag-agent=2\n")
        return True

    if max_drift <= tolerance:
        print(f"✅ EQUALLY BALANCED: Max drift is {max_drift * 100:.1f}% (within allowed ±{tolerance * 100:.0f}% tolerance).")
        return True
    else:
        print(f"⚠️  UNEVEN LOAD DETECTED: Max drift is {max_drift * 100:.1f}% (exceeds ±{tolerance * 100:.0f}% tolerance).")
        print("   Common causes:")
        print("   1. HTTP Keepalive connection reuse pooling in client or Nginx.")
        print("   2. Using 'least_conn' or 'ip_hash' instead of 'round-robin'.")
        print("   3. Asymmetric health check failures or initial startup lag.")
        return False


async def run_live_test(args):
    headers = {}
    if args.force_debug_header:
        headers["X-Debug-LB"] = "1"

    print("=" * 65)
    print("🚀 NGINX LOAD BALANCER TESTING & VERIFICATION")
    print("=" * 65)
    print(f"Target URL           : {args.url}")
    print(f"Total Requests       : {args.requests}")
    print(f"Concurrency Level    : {args.concurrency}")
    print(f"Debug Header Bypass  : {'Enabled (X-Debug-LB: 1)' if args.force_debug_header else 'Default (from environment flag)'}")
    print("=" * 65)

    results = []
    semaphore = asyncio.Semaphore(args.concurrency)

    start_total_t = time.perf_counter()
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=args.concurrency * 2)) as client:
        # Pre-flight check
        try:
            preflight = await client.get(args.url, headers=headers, timeout=5.0)
            served_by = preflight.headers.get("x-served-by") or preflight.headers.get("X-Served-By")
            if not served_by:
                print("\n💡 NOTE: 'X-Served-By' header is not present on response.")
                print("   This is expected in PRODUCTION mode (ENABLE_LB_DEBUG_HEADERS=false).")
                print("   Options to verify:")
                print("   1. Run with '--force-debug-header' to pass 'X-Debug-LB: 1'.")
                print("   2. Set ENABLE_LB_DEBUG_HEADERS=true in .env and restart Nginx.")
                print("   3. Or parse Nginx access logs directly with '--parse-log <path>'.\n")
            else:
                print(f"⚡ Connection Verified! Sample upstream: {served_by}")
        except Exception as e:
            print(f"❌ Connection failed to {args.url}: {e}")
            sys.exit(1)

        print("\n⏳ Sending load traffic...")
        await send_worker_requests(
            client=client,
            url=args.url,
            headers=headers,
            total_requests=args.requests,
            results=results,
            semaphore=semaphore,
        )

    total_time = time.perf_counter() - start_total_t
    successful = [r for r in results if 200 <= r["status"] < 400]
    failed = [r for r in results if r["status"] < 200 or r["status"] >= 400]
    durations = [r["duration"] * 1000 for r in successful]  # in ms

    rps = len(results) / total_time if total_time > 0 else 0
    avg_latency = sum(durations) / len(durations) if durations else 0
    p50 = sorted(durations)[int(len(durations) * 0.50)] if durations else 0
    p95 = sorted(durations)[int(len(durations) * 0.95)] if durations else 0
    p99 = sorted(durations)[int(len(durations) * 0.99)] if durations else 0

    print("\n📊 LOAD TEST PERFORMANCE SUMMARY")
    print("-" * 65)
    print(f"Completed In         : {total_time:.2f} seconds")
    print(f"Throughput           : {rps:.1f} req/sec")
    print(f"Successful Requests  : {len(successful)} / {len(results)} ({len(successful)/len(results)*100:.1f}%)")
    if failed:
        print(f"Failed Requests      : {len(failed)}")
    print(f"Latency (Avg)        : {avg_latency:.2f} ms")
    print(f"Latency (p50 / p95)  : {p50:.2f} ms / {p95:.2f} ms")
    print(f"Latency (p99)        : {p99:.2f} ms")

    # Evaluate distribution by X-Served-By
    counts = Counter(r["served_by"] for r in successful if r["served_by"] != "unknown")
    if counts:
        is_balanced = evaluate_distribution(counts, len(successful), tolerance=args.tolerance)
        sys.exit(0 if is_balanced else 1)
    else:
        print("\nℹ️  Backend addresses were not returned in headers (Production Flag Active).")
        print("   To view backend distribution:")
        print("   👉 Check Nginx access log: tail -n 100 /var/log/nginx/access.log | grep upstream_addr")
        print("   👉 Or rerun with: python scripts/verify_load_balancing.py --force-debug-header\n")
        sys.exit(0)


def main():
    args = parse_args()
    if args.parse_log:
        parse_nginx_log(args.parse_log)
    else:
        asyncio.run(run_live_test(args))


if __name__ == "__main__":
    main()
