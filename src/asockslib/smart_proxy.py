"""SmartProxy — high-level proxy manager with auto-rotation and self-healing.

Abstracts the complexity of proxy lifecycle management: creates proxies,
checks their health, and transparently replaces dead ones.

Example::

    async with ASocksClient(api_key="key") as client:
        smart = SmartProxy(client, country_code="US", pool_size=5)
        await smart.initialize()

        proxy = await smart.get_proxy()
        print(proxy)  # socks5://user:pass@host:port
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx
from beartype import beartype

from asockslib._port_utils import PortManagerMixin

# Runtime import (not TYPE_CHECKING): @beartype resolves the ASocksClient
# annotation on __init__ at call time, so the name must exist at runtime.
from asockslib.client import ASocksClient  # noqa: TC001
from asockslib.exceptions import NoAvailableProxyError

if TYPE_CHECKING:
    from asockslib.models import PortInfo

logger = logging.getLogger("asockslib")

_HEALTH_CHECK_URL = "https://api.ipify.org?format=json"
_HEALTH_TIMEOUT = 10.0


class SmartProxy(PortManagerMixin):
    """High-level proxy manager with automatic rotation and self-healing.

    On each :meth:`get_proxy` call the manager returns the next
    healthy proxy from the pool.  When a proxy fails a health check
    it is replaced transparently via the ASocks API.

    Args:
        client: :class:`ASocksClient` instance.
        country_code: ISO country code for proxies.
        city: City filter (optional).
        state: State filter (optional).
        pool_size: Number of proxies to maintain.
        type_id: Connection type (1=keep-proxy, 2=keep-connection, 3=rotate).
        proxy_type_id: Proxy type (1=residential, 3=mobile, 4=corporate).
        server_port_type_id: Port type (0=shared, 1=dedicated).
        ttl: Port lifetime in days.
        traffic_limit: Traffic limit in GB.
        health_check_url: URL used for health checks.
        health_timeout: Health-check timeout in seconds.
    """

    @beartype
    def __init__(
        self,
        client: ASocksClient,
        *,
        country_code: str = "",
        city: str = "",
        state: str = "",
        pool_size: int = 0,
        type_id: int = 1,
        proxy_type_id: int = 1,
        server_port_type_id: int = 0,
        ttl: int = 1,
        traffic_limit: int = 10,
        health_check_url: str = _HEALTH_CHECK_URL,
        health_timeout: float = _HEALTH_TIMEOUT,
    ) -> None:
        self._client = client
        self._country_code = country_code
        self._city = city
        self._state = state
        self._pool_size = pool_size
        self._type_id = type_id
        self._proxy_type_id = proxy_type_id
        self._server_port_type_id = server_port_type_id
        self._ttl = ttl
        self._traffic_limit = traffic_limit
        self._health_check_url = health_check_url
        self._health_timeout = health_timeout

        self._proxies: list[PortInfo] = []
        self._index: int = 0
        self._lock = asyncio.Lock()

    @property
    def _pool(self) -> list[PortInfo]:
        """Alias for internal pool (used by tests)."""
        return self._proxies

    @property
    def pool_size(self) -> int:
        """Current number of proxies in the pool."""
        return len(self._proxies)

    @beartype
    async def initialize(self, pool_size: int | None = None) -> None:
        """Populate the proxy pool.

        Loads existing active ports that match the criteria.
        Creates new ones if fewer than *pool_size* are available.

        Args:
            pool_size: Override pool size set in constructor.
        """
        if pool_size is not None:
            self._pool_size = pool_size
        if self._pool_size < 0:
            raise ValueError("pool_size must be >= 0")
        existing = await self._fetch_matching_ports(limit=self._pool_size)
        self._proxies = list(existing[: self._pool_size])

        deficit = self._pool_size - len(self._proxies)
        if deficit > 0:
            new_ports = await self._create_ports(deficit)
            self._proxies.extend(new_ports)

        logger.info("SmartProxy initialized with %d proxies", len(self._proxies))

    @beartype
    async def get_proxy(self) -> str:
        """Return the next healthy proxy URL (round-robin).

        Runs a health check on the candidate.  If it fails, the
        proxy is replaced automatically and the next one is tried.

        Raises:
            NoAvailableProxyError: Pool is empty.
        """
        if not self._proxies:
            raise NoAvailableProxyError("Proxy pool is empty. Call initialize() first.")

        # The health check is a live network request (up to health_timeout
        # seconds). Holding the lock across it would serialize every caller
        # behind one slow probe, so the lock only guards index advancement and
        # pool mutation — the actual probe runs lock-free.
        attempts = len(self._proxies)
        for _ in range(attempts):
            async with self._lock:
                if not self._proxies:
                    break
                proxy = self._proxies[self._index % len(self._proxies)]
                self._index += 1

            if await self._is_healthy(proxy):
                return proxy.proxy_url

            logger.warning("Proxy %d unhealthy, replacing…", proxy.id)
            replacement = await self._replace_proxy(proxy)
            if replacement:
                return replacement.proxy_url

        raise NoAvailableProxyError("All proxies failed health checks.")

    @beartype
    async def get_all_proxies(self) -> list[str]:
        """Return URLs for every proxy currently in the pool."""
        return [p.proxy_url for p in self._proxies]

    @beartype
    async def health_check_all(self) -> dict[int, bool]:
        """Check all proxies in parallel.

        Returns:
            Mapping of ``port_id → is_healthy``.
        """

        async def _check(p: PortInfo) -> tuple[int, bool]:
            return p.id, await self._is_healthy(p)

        results = await asyncio.gather(*[_check(p) for p in self._proxies])
        return dict(results)

    @beartype
    async def refresh_pool(self) -> int:
        """Replace all unhealthy proxies.

        Returns:
            Number of proxies replaced.
        """
        replaced = 0
        for proxy in list(self._proxies):
            if not await self._is_healthy(proxy):
                await self._replace_proxy(proxy)
                replaced += 1
        logger.info("Refreshed pool: %d/%d replaced", replaced, len(self._proxies))
        return replaced

    # ── Internal helpers ──────────────────────────────────────────────── #

    async def _is_healthy(self, proxy: PortInfo) -> bool:
        """Ping the proxy through a lightweight HTTP request."""
        try:
            async with httpx.AsyncClient(
                proxy=proxy.proxy_url,
                timeout=self._health_timeout,
            ) as http:
                resp = await http.get(self._health_check_url)
                return resp.is_success
        except Exception:  # noqa: BLE001
            return False

    async def _replace_proxy(self, proxy: PortInfo) -> PortInfo | None:
        """Replace a dead proxy with a fresh one.

        Matches the slot by port ``id`` (not object identity) so a proxy is
        replaced correctly even after the pool list has been reordered. If a
        concurrent caller already replaced the same proxy, the freshly created
        port is deleted (best-effort) rather than leaked.

        Returns:
            The new :class:`PortInfo` or ``None`` on failure.
        """
        try:
            new_ports = await self._create_ports(1)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to replace proxy %d", proxy.id)
            return None
        if not new_ports:
            return None

        new_port = new_ports[0]
        async with self._lock:
            idx = next((i for i, p in enumerate(self._proxies) if p.id == proxy.id), None)
            if idx is not None:
                self._proxies[idx] = new_port
        if idx is None:
            # Lost a race \u2014 proxy already replaced by a concurrent caller.
            # Delete the spare port (don't leak a paid proxy) and report no
            # replacement so the caller falls through to an already-healthy one.
            logger.debug("Proxy %d already replaced; deleting spare port %d", proxy.id, new_port.id)
            try:
                await self._client.delete_port(new_port.id)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to delete spare port %d", new_port.id)
            return None
        logger.info("Replaced proxy %d \u2192 %d", proxy.id, new_port.id)
        return new_port

    # _fetch_matching_ports and _create_ports inherited from PortManagerMixin
