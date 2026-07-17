"""One-liner API — get working proxies in a single function call.

.. code-block:: python

    from asockslib import get_proxies

    proxies = await get_proxies("US")
    # → ["socks5://user:pass@host:port", ...]

Creation, verification and cleanup happen transparently under the hood.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

from beartype import beartype

from asockslib.client import ASocksClient
from asockslib.models import CreatePortRequest


@beartype
async def get_proxies(
    country: str,
    count: int = 10,
    *,
    api_key: str | None = None,
    verify: bool = False,
    timeout: float = 3.0,
    server_port_type_id: int = 0,
    proxy_type_id: int = 1,
    type_id: int = 1,
    ttl: int = 1,
    traffic_limit: int = 1,
) -> list[str]:
    """Get working proxies for a country in one call.

    Args:
        country: ISO country code (``"US"``, ``"DE"``, ``"GB"``, ...).
        count: Number of proxies to return (default ``10``).
        api_key: ASocks API key.  Falls back to ``ASOCKS_API_KEY`` env var.
        verify: When ``True``, create ``2×count`` proxies, ping them all,
            keep the fastest *count* and delete the rest (~3-5 s).
        timeout: Per-proxy health-check timeout when *verify* is enabled.
        server_port_type_id: ``0`` = shared (default), ``1`` = dedicated.
        proxy_type_id: ``1`` = residential, ``3`` = mobile, ``4`` = corporate.
        type_id: ``1`` = keep-proxy, ``2`` = keep-connection, ``3`` = rotate.
        ttl: Port lifetime in days.
        traffic_limit: Traffic limit in GB.

    Returns:
        Ready-to-use proxy URLs (``socks5://login:password@host:port``).

    Raises:
        ValueError: API key is missing.
        ASocksError: API communication error.

    Example::

        proxies = await get_proxies("US")

        # With verification — keeps only alive proxies
        proxies = await get_proxies("US", count=10, verify=True)

        # Usage with httpx
        import httpx
        async with httpx.AsyncClient(proxy=proxies[0]) as client:
            resp = await client.get("https://example.com")
    """
    key = api_key or os.environ.get("ASOCKS_API_KEY", "")
    if not key:
        msg = (
            "API key not found. Pass api_key= or set ASOCKS_API_KEY env variable. "
            "Get your key at https://my.asocks.com"
        )
        raise ValueError(msg)

    create_count = count * 2 if verify else count

    async with ASocksClient(api_key=key) as client:
        req = CreatePortRequest(
            country_code=country,
            count=min(create_count, 1000),
            type_id=type_id,
            proxy_type_id=proxy_type_id,
            server_port_type_id=server_port_type_id,
            ttl=ttl,
            traffic_limit=traffic_limit,
        )
        ports = await client.create_ports(req)
        urls = [p.proxy_url for p in ports]

        if not verify or not urls:
            return urls[:count]

        # Verify — parallel health-check via asyncio.gather
        from asockslib.benchmark import ping_proxy

        sem = asyncio.Semaphore(100)

        async def _check(url: str) -> tuple[str, float | None]:
            async with sem:
                result = await ping_proxy(url, timeout=timeout)
                return url, result.latency_ms if result.is_alive else None

        checks = await asyncio.gather(*[_check(u) for u in urls])

        # Keep alive proxies, sort by latency
        alive = sorted(
            [(url, lat) for url, lat in checks if lat is not None],
            key=lambda x: x[1],
        )

        best_urls = [url for url, _ in alive[:count]]

        # Delete unused ports in parallel
        best_set = set(best_urls)
        url_to_id = {p.proxy_url: p.id for p in ports}
        to_delete = [url_to_id[u] for u in urls if u not in best_set and u in url_to_id]

        if to_delete:

            async def _del(pid: int) -> None:
                with contextlib.suppress(Exception):
                    await client.delete_port(pid)

            await asyncio.gather(*[_del(pid) for pid in to_delete])

        return best_urls


@beartype
def get_proxies_sync(
    country: str,
    count: int = 10,
    *,
    api_key: str | None = None,
    verify: bool = False,
    timeout: float = 3.0,
    server_port_type_id: int = 0,
    proxy_type_id: int = 1,
    type_id: int = 1,
    ttl: int = 1,
    traffic_limit: int = 1,
) -> list[str]:
    """Synchronous wrapper around :func:`get_proxies`.

    Convenient for scripts, notebooks and non-async code.
    Parameters are identical to :func:`get_proxies`.

    Example::

        from asockslib import get_proxies_sync

        proxies = get_proxies_sync("US", count=5)
        print(proxies[0])
    """
    return asyncio.run(
        get_proxies(
            country,
            count,
            api_key=api_key,
            verify=verify,
            timeout=timeout,
            server_port_type_id=server_port_type_id,
            proxy_type_id=proxy_type_id,
            type_id=type_id,
            ttl=ttl,
            traffic_limit=traffic_limit,
        )
    )
