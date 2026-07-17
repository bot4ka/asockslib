"""Proxy health-checking, latency measurement and benchmarking utilities.

All operations are fully async and parallelised with ``asyncio.gather``.

Public API:
    - :func:`ping_proxy` — measure latency of a single proxy.
    - :func:`benchmark_proxies` — benchmark a batch in parallel.
    - :func:`select_best_proxies` — keep the fastest *N* proxies.
    - :func:`find_best_proxies` — create, test, keep best, delete the rest.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from beartype import beartype

# Runtime import (not TYPE_CHECKING): @beartype resolves the ASocksClient
# annotation at call time, so the name must exist in the module namespace.
from asockslib.client import ASocksClient  # noqa: TC001
from asockslib.models import CreatePortRequest

logger = logging.getLogger("asockslib")

ProgressCallback = Callable[[str, int, int], None]
"""``(stage, current, total) -> None`` callback for :func:`find_best_proxies`."""

_PING_URLS = [
    "https://api.ipify.org?format=json",
    "https://httpbin.org/ip",
    "https://ifconfig.me/ip",
]

_PING_TIMEOUT = 5.0
_BENCHMARK_CONCURRENT = 200
_DELETE_CONCURRENT = 50


# ── Data classes ──────────────────────────────────────────────────────────── #


@dataclass
class ProxyBenchmarkResult:
    """Result of benchmarking a single proxy.

    Attributes:
        proxy_url: Full proxy URL.
        port_id: ASocks port ID.
        latency_ms: Round-trip latency in milliseconds (``None`` on failure).
        external_ip: External IP seen through the proxy.
        is_alive: Whether the proxy responded successfully.
        country: Country name from port metadata.
        city: City name from port metadata.
        error: Error message on failure.
    """

    proxy_url: str
    port_id: int = 0
    latency_ms: float | None = None
    external_ip: str = ""
    is_alive: bool = False
    country: str = ""
    city: str = ""
    error: str = ""


@dataclass
class CountryPingResult:
    """Aggregated ping statistics for a country/region."""

    country_name: str = ""
    country_code: str = ""
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    alive_count: int = 0
    total_count: int = 0
    availability: str = ""
    samples: list[ProxyBenchmarkResult] = field(default_factory=list[ProxyBenchmarkResult])


@dataclass
class FindBestResult:
    """Result of the :func:`find_best_proxies` pipeline.

    Attributes:
        best: Top proxies that passed the benchmark.
        total_created: Number of ports created.
        total_tested: Number of proxies tested.
        total_alive: Number of alive proxies.
        total_deleted: Number of discarded ports deleted.
        delete_errors: Port IDs that failed to delete.
        avg_latency_ms: Average latency of the best proxies.
        min_latency_ms: Best (lowest) latency.
        max_latency_ms: Worst latency among the best.
    """

    best: list[ProxyBenchmarkResult] = field(default_factory=list[ProxyBenchmarkResult])
    total_created: int = 0
    total_tested: int = 0
    total_alive: int = 0
    total_deleted: int = 0
    delete_errors: list[int] = field(default_factory=list[int])
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0


# ── Single-proxy ping ────────────────────────────────────────────────────── #


@beartype
async def ping_proxy(
    proxy_url: str,
    *,
    timeout: float = _PING_TIMEOUT,
    ping_urls: list[str] | None = None,
) -> ProxyBenchmarkResult:
    """Measure latency of a single proxy.

    Sends requests to multiple lightweight endpoints in parallel
    and keeps the fastest successful result.

    Args:
        proxy_url: Full proxy URL.
        timeout: Request timeout in seconds.
        ping_urls: Custom list of check URLs.
    """
    urls = ping_urls or _PING_URLS
    result = ProxyBenchmarkResult(proxy_url=proxy_url)

    async def _try_url(url: str) -> tuple[float, str] | None:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout) as client:
                resp = await client.get(url)
                elapsed = (time.monotonic() - start) * 1000
                if resp.is_success:
                    ip = ""
                    try:
                        data = resp.json()
                        ip = data.get("ip", data.get("origin", ""))
                    except Exception:  # noqa: BLE001
                        ip = resp.text.strip()
                    return elapsed, ip
        except Exception:  # noqa: BLE001
            pass
        return None

    ping_results = await asyncio.gather(*[_try_url(u) for u in urls])

    best: tuple[float, str] | None = None
    for r in ping_results:
        if r is not None and (best is None or r[0] < best[0]):
            best = r

    if best is not None:
        result.latency_ms = round(best[0], 1)
        result.is_alive = True
        result.external_ip = best[1]
    else:
        result.error = "All ping endpoints failed"

    return result


# ── Batch benchmark ───────────────────────────────────────────────────────── #


@beartype
async def benchmark_proxies(
    proxy_urls: list[str],
    *,
    timeout: float = _PING_TIMEOUT,
    concurrency: int = _BENCHMARK_CONCURRENT,
) -> list[ProxyBenchmarkResult]:
    """Benchmark a batch of proxies in parallel.

    Returns:
        Results sorted alive-first by ascending latency.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded_ping(url: str) -> ProxyBenchmarkResult:
        async with semaphore:
            return await ping_proxy(url, timeout=timeout)

    results = await asyncio.gather(*[_bounded_ping(url) for url in proxy_urls])

    alive = sorted(
        [r for r in results if r.is_alive],
        key=lambda r: r.latency_ms or float("inf"),
    )
    dead = [r for r in results if not r.is_alive]
    return alive + dead


@beartype
async def select_best_proxies(
    proxy_urls: list[str],
    *,
    keep: int = 10,
    timeout: float = _PING_TIMEOUT,
    concurrency: int = _BENCHMARK_CONCURRENT,
) -> tuple[list[ProxyBenchmarkResult], list[ProxyBenchmarkResult]]:
    """Select the fastest proxies by latency.

    Returns:
        ``(best, discarded)`` tuple.
    """
    results = await benchmark_proxies(proxy_urls, timeout=timeout, concurrency=concurrency)
    best = results[:keep]
    discarded = results[keep:]
    logger.info(
        "Selected %d best proxies out of %d (discarded %d)",
        len(best),
        len(results),
        len(discarded),
    )
    return best, discarded


# ── Full pipeline ─────────────────────────────────────────────────────────── #


@beartype
async def find_best_proxies(
    client: ASocksClient,
    *,
    country_code: str = "US",
    city: str = "",
    state: str = "",
    total: int = 100,
    keep: int = 10,
    batch_size: int = 1000,
    timeout: float = 5.0,
    concurrency: int = 200,
    type_id: int = 1,
    proxy_type_id: int = 1,
    server_port_type_id: int = 0,
    ttl: int = 1,
    traffic_limit: int = 1,
    delete_failures: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> FindBestResult:
    """Create *total* proxies, benchmark them all, keep the fastest *keep*, delete the rest.

    The entire pipeline is parallelised: creation in batches, benchmark
    with up to *concurrency* simultaneous pings, deletion in parallel.

    Args:
        client: :class:`ASocksClient` instance.
        country_code: ISO country code.
        total: How many proxies to create.
        keep: How many fastest proxies to keep.
        timeout: Benchmark timeout per proxy.
        concurrency: Maximum concurrent benchmark connections.
        delete_failures: Delete discarded ports (default ``True``).
        progress_callback: ``(stage, current, total) -> None``.
    """
    result = FindBestResult()
    all_ports: list[tuple[int, str]] = []

    def _progress(stage: str, current: int, total_n: int) -> None:
        if progress_callback is not None:
            progress_callback(stage, current, total_n)

    # Step 1: Create proxies in parallel batches
    batches: list[int] = []
    remaining = total
    while remaining > 0:
        chunk = min(remaining, batch_size, 1000)
        batches.append(chunk)
        remaining -= chunk

    async def _create_batch(chunk: int, batch_num: int) -> list[tuple[int, str]]:
        logger.info("Creating batch %d: %d proxies", batch_num, chunk)
        req = CreatePortRequest(
            country_code=country_code,
            city=city,
            state=state,
            count=chunk,
            type_id=type_id,
            proxy_type_id=proxy_type_id,
            server_port_type_id=server_port_type_id,
            ttl=ttl,
            traffic_limit=traffic_limit,
        )
        try:
            ports = await client.create_ports(req)
            return [(p.id, p.proxy_url) for p in ports]
        except Exception:  # noqa: BLE001
            logger.exception("Failed to create batch %d", batch_num)
            return []

    _progress("creating", 0, total)
    batch_results = await asyncio.gather(
        *[_create_batch(chunk, i + 1) for i, chunk in enumerate(batches)]
    )
    for batch_ports in batch_results:
        all_ports.extend(batch_ports)
    result.total_created = len(all_ports)
    _progress("creating", result.total_created, total)

    if not all_ports:
        return result

    # Step 2: Benchmark all proxies
    _progress("benchmarking", 0, len(all_ports))
    url_to_id: dict[str, int] = {url: pid for pid, url in all_ports}
    urls = [url for _, url in all_ports]

    bench_results = await benchmark_proxies(urls, timeout=timeout, concurrency=concurrency)
    for r in bench_results:
        r.port_id = url_to_id.get(r.proxy_url, 0)

    result.total_tested = len(bench_results)
    result.total_alive = sum(1 for r in bench_results if r.is_alive)
    _progress("benchmarking", len(bench_results), len(all_ports))

    # Step 3: Select best
    result.best = bench_results[:keep]
    best_latencies = [r.latency_ms for r in result.best if r.latency_ms is not None]
    if best_latencies:
        result.avg_latency_ms = round(sum(best_latencies) / len(best_latencies), 1)
        result.min_latency_ms = round(min(best_latencies), 1)
        result.max_latency_ms = round(max(best_latencies), 1)

    best_ids = {r.port_id for r in result.best if r.port_id}

    # Step 4: Delete discarded ports
    if delete_failures:
        to_delete = [pid for pid, _ in all_ports if pid not in best_ids]
        _progress("deleting", 0, len(to_delete))
        delete_sem = asyncio.Semaphore(_DELETE_CONCURRENT)

        async def _delete_one(pid: int) -> bool:
            async with delete_sem:
                try:
                    await client.delete_port(pid)
                    return True
                except Exception:  # noqa: BLE001
                    return False

        delete_results = await asyncio.gather(*[_delete_one(pid) for pid in to_delete])
        for pid, ok in zip(to_delete, delete_results, strict=False):
            if ok:
                result.total_deleted += 1
            else:
                result.delete_errors.append(pid)
        _progress("deleting", len(to_delete), len(to_delete))

    logger.info(
        "find_best_proxies complete: %d best (avg %.0fms), %d deleted, %d errors",
        len(result.best),
        result.avg_latency_ms,
        result.total_deleted,
        len(result.delete_errors),
    )
    return result
