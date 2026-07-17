"""ProxyPool — zero-traffic intelligent proxy pool manager.

Key feature: manages account-to-proxy mappings, automatically detects
dead proxies and replaces them **without making a single HTTP request
through the proxy** for health checks.

How it works:

1. ``ProxyPool`` creates a pool of proxy ports via the ASocks API.
2. Each account receives a *stable* proxy URL.
3. When a connection error occurs the user calls :meth:`report_failure`.
4. The pool checks the port status via the ASocks REST API
   (``GET /v2/proxy/port-info``) and, if the port is dead,
   automatically creates a replacement with identical parameters.
5. The new proxy URL is bound to the same account — the user calls
   :meth:`get_proxy` and gets a working URL immediately.

Example::

    async with ASocksClient(api_key="...") as client:
        pool = ProxyPool(client, country_code="US", pool_size=100)
        await pool.initialize()

        url = await pool.get_proxy("account_42")

        try:
            await do_request(url)
        except ConnectionError:
            await pool.report_failure("account_42")
            url = await pool.get_proxy("account_42")  # new proxy!
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import random
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from beartype import beartype

from asockslib._port_utils import PortManagerMixin

# Runtime import (not TYPE_CHECKING): @beartype resolves the ASocksClient
# annotation on __init__ at call time, so the name must exist at runtime.
from asockslib.client import ASocksClient  # noqa: TC001
from asockslib.exceptions import NoAvailableProxyError

if TYPE_CHECKING:
    from asockslib.models import PortInfo

logger = logging.getLogger("asockslib.pool")


# ── Persistence ───────────────────────────────────────────────────────────── #


@runtime_checkable
class ProxyStore(Protocol):
    """Pluggable persistence backend for ``account_id → port_id`` bindings.

    Implement this to make sticky assignments survive process restarts.
    The pool calls:

    - :meth:`load` once during :meth:`ProxyPool.initialize` to restore the
      mapping (bindings whose port no longer exists in the pool are dropped);
    - :meth:`save` whenever an account is bound to a port or its port is
      replaced;
    - :meth:`delete` when an account is released.

    All methods are async so an implementation may use Redis, a SQL database,
    a file, or any other store. Store failures are swallowed (logged, not
    raised) so persistence problems never break proxy assignment.

    Example (in-memory reference implementation)::

        class DictStore:
            def __init__(self) -> None:
                self._d: dict[str, int] = {}

            async def load(self) -> dict[str, int]:
                return dict(self._d)

            async def save(self, account_id: str, port_id: int) -> None:
                self._d[account_id] = port_id

            async def delete(self, account_id: str) -> None:
                self._d.pop(account_id, None)
    """

    async def load(self) -> dict[str, int]:
        """Return the persisted ``account_id → port_id`` mapping."""
        ...

    async def save(self, account_id: str, port_id: int) -> None:
        """Persist a single ``account_id → port_id`` binding."""
        ...

    async def delete(self, account_id: str) -> None:
        """Remove an account's persisted binding."""
        ...


# ── Data types ────────────────────────────────────────────────────────────── #


class PoolStrategy(StrEnum):
    """Strategy for assigning proxies to accounts.

    Values:
        STICKY: Each account gets one fixed proxy.
        ROUND_ROBIN: Accounts receive proxies in round-robin order.
        RANDOM: Random proxy from the pool on every request.
    """

    STICKY = "sticky"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"


@dataclass
class _ProxySlot:
    """Internal pool slot: proxy + metadata."""

    port: PortInfo
    failure_count: int = 0
    last_failure_ts: float = 0.0
    is_dead: bool = False
    assigned_accounts: set[str] = field(default_factory=set[str])


@dataclass(frozen=True, slots=True)
class ProxyPoolStats:
    """Pool statistics snapshot.

    Attributes:
        total: Total number of slots in the pool.
        alive: Number of alive proxies.
        dead: Number of dead proxies awaiting replacement.
        replaced: Total replacements since initialization.
        accounts: Number of bound accounts.
        api_checks: Total API health-check calls made.
    """

    total: int
    alive: int
    dead: int
    replaced: int
    accounts: int
    api_checks: int


# ── ProxyPool ─────────────────────────────────────────────────────────────── #


class ProxyPool(PortManagerMixin):
    """Intelligent proxy manager for large-scale projects.

    Designed for developers managing thousands of accounts who need
    stable proxies without manual intervention.

    Key principles:
        - **Zero wasted traffic** — port status is checked via the ASocks
          REST API, not by sending requests through the proxy.
        - **Failure-triggered checks** — health is verified only when the
          user reports an error via :meth:`report_failure`.
        - **Transparent replacement** — a dead proxy is replaced with one
          that has identical parameters; the account receives a new URL
          automatically.

    Args:
        client: :class:`ASocksClient` instance.
        country_code: ISO country code for proxies.
        pool_size: Number of proxies in the pool.
        strategy: Assignment strategy (default ``STICKY``).
        failure_threshold: Consecutive failures before a proxy is
            considered dead.
        monitor_interval: Background monitor interval in seconds
            (``0`` = disabled).
        store: Optional :class:`ProxyStore` for persisting ``account_id →
            port_id`` bindings across restarts. When provided, STICKY
            bindings are saved on assignment/replacement and restored during
            :meth:`initialize`.
        benchmark_on_init: When ``True``, :meth:`initialize` over-provisions
            candidates (``benchmark_oversample × pool_size``), pings them and
            keeps only the fastest *pool_size* — trading a one-off startup
            probe for a lower-latency pool. Ports the pool itself created but
            discarded are deleted; pre-existing ports are never deleted.
            Default ``False`` (zero-traffic startup).
        benchmark_oversample: Candidate multiplier when *benchmark_on_init*
            is enabled (``>= 1.0``).
        benchmark_timeout: Per-proxy ping timeout (seconds) during
            benchmark-on-init.

    Raises:
        ValueError: *pool_size* < 1, *failure_threshold* < 1, or
            *benchmark_oversample* < 1.
    """

    @beartype
    def __init__(
        self,
        client: ASocksClient,
        *,
        country_code: str = "",
        city: str = "",
        state: str = "",
        pool_size: int = 10,
        type_id: int = 1,
        proxy_type_id: int = 1,
        server_port_type_id: int = 0,
        ttl: int = 1,
        traffic_limit: int = 10,
        strategy: PoolStrategy = PoolStrategy.STICKY,
        failure_threshold: int = 3,
        monitor_interval: float = 0,
        store: ProxyStore | None = None,
        benchmark_on_init: bool = False,
        benchmark_oversample: float = 2.0,
        benchmark_timeout: float = 5.0,
    ) -> None:
        if pool_size < 1:
            raise ValueError("pool_size must be >= 1")
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if benchmark_oversample < 1:
            raise ValueError("benchmark_oversample must be >= 1.0")
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
        self._strategy = strategy
        self._failure_threshold = failure_threshold
        self._monitor_interval = monitor_interval
        self._store = store
        self._benchmark_on_init = benchmark_on_init
        self._benchmark_oversample = benchmark_oversample
        self._benchmark_timeout = benchmark_timeout

        self._slots: list[_ProxySlot] = []
        self._account_map: dict[str, int] = {}
        self._rr_index: int = 0
        self._lock = asyncio.Lock()
        self._replaced_total: int = 0
        self._api_checks: int = 0
        self._monitor_task: asyncio.Task[None] | None = None
        self._initialized: bool = False

    # ── Initialization ────────────────────────────────────────────────── #

    @beartype
    async def initialize(self) -> None:
        """Initialize the proxy pool.

        Loads existing active ports matching the criteria and creates new
        ones if fewer than *pool_size* are available. When *benchmark_on_init*
        is set, over-provisions and keeps only the fastest *pool_size*. If a
        :class:`ProxyStore` was supplied, previously persisted account
        bindings are restored.
        """
        if self._benchmark_on_init:
            ports = await self._build_benchmarked_ports()
        else:
            existing = await self._fetch_matching_ports(limit=self._pool_size)
            ports = list(existing[: self._pool_size])
            deficit = self._pool_size - len(ports)
            if deficit > 0:
                ports.extend(await self._create_ports(deficit))

        self._slots = [_ProxySlot(port=p) for p in ports]

        await self._restore_bindings()

        self._initialized = True
        logger.info("ProxyPool initialized: %d slots", len(self._slots))

        if self._monitor_interval > 0:
            self._monitor_task = asyncio.create_task(self._background_monitor())

    async def _build_benchmarked_ports(self) -> list[PortInfo]:
        """Over-provision, ping, and keep the fastest *pool_size* ports.

        Only ports created by this call are deleted when discarded;
        pre-existing user ports are always retained.
        """
        from asockslib.benchmark import benchmark_proxies

        target = max(self._pool_size, math.ceil(self._pool_size * self._benchmark_oversample))
        candidates: list[PortInfo] = list(await self._fetch_matching_ports(limit=target))[:target]
        created_ids: set[int] = set()
        deficit = target - len(candidates)
        if deficit > 0:
            new_ports = await self._create_ports(deficit)
            candidates.extend(new_ports)
            created_ids = {p.id for p in new_ports}
        if not candidates:
            return []

        url_to_port = {p.proxy_url: p for p in candidates}
        results = await benchmark_proxies(
            [p.proxy_url for p in candidates],
            timeout=self._benchmark_timeout,
        )
        # benchmark_proxies returns alive-first, ascending latency.
        ordered = [url_to_port[r.proxy_url] for r in results if r.proxy_url in url_to_port]
        kept = ordered[: self._pool_size]
        kept_ids = {p.id for p in kept}

        to_delete = [pid for pid in created_ids if pid not in kept_ids]
        if to_delete:
            await self._delete_ports_quietly(to_delete)
        logger.info(
            "benchmark_on_init: kept %d/%d candidates (deleted %d created)",
            len(kept),
            len(candidates),
            len(to_delete),
        )
        return kept

    async def _delete_ports_quietly(self, port_ids: list[int]) -> None:
        """Best-effort parallel deletion of ports; failures are logged only."""

        async def _del(pid: int) -> None:
            try:
                await self._client.delete_port(pid)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to delete port %d during cleanup", pid)

        await asyncio.gather(*[_del(pid) for pid in port_ids])

    async def _restore_bindings(self) -> None:
        """Restore ``account_id → slot`` bindings from the store, if any."""
        if self._store is None:
            return
        try:
            mapping = await self._store.load()
        except Exception:  # noqa: BLE001
            logger.exception("ProxyStore.load() failed; starting with no bindings")
            return

        port_index = {slot.port.id: i for i, slot in enumerate(self._slots)}
        restored = 0
        for account_id, port_id in mapping.items():
            slot_idx = port_index.get(port_id)
            if slot_idx is None:
                # Port is gone from the pool; account will be re-bound lazily
                # on its next get_proxy() call.
                continue
            self._account_map[account_id] = slot_idx
            self._slots[slot_idx].assigned_accounts.add(account_id)
            restored += 1
        if restored:
            logger.info("Restored %d account bindings from store", restored)

    # ── Core API ──────────────────────────────────────────────────────── #

    @beartype
    async def get_proxy(self, account_id: str | None = None) -> str:
        """Get a proxy URL for an account.

        Behaviour depends on the strategy:
            - **STICKY** — account is bound to a single proxy.
            - **ROUND_ROBIN** — next proxy in rotation.
            - **RANDOM** — random alive proxy.

        Raises:
            NoAvailableProxyError: No alive proxies in the pool.
        """
        if not self._initialized:
            raise NoAvailableProxyError("ProxyPool not initialized. Call initialize() first.")

        async with self._lock:
            alive_slots = [(i, s) for i, s in enumerate(self._slots) if not s.is_dead]
            if not alive_slots:
                raise NoAvailableProxyError("All proxies in the pool are dead.")

            if self._strategy == PoolStrategy.STICKY and account_id:
                url, persist_port_id = self._get_sticky(account_id, alive_slots)
            elif self._strategy == PoolStrategy.ROUND_ROBIN:
                url, persist_port_id = self._get_round_robin(account_id, alive_slots)
            else:
                url, persist_port_id = self._get_random(account_id, alive_slots)

        # Persist a new sticky binding outside the lock (store I/O may be slow).
        if persist_port_id is not None and account_id is not None:
            await self._persist_binding(account_id, persist_port_id)
        return url

    @beartype
    async def get_proxies(self, account_ids: list[str]) -> dict[str, str]:
        """Get proxies for multiple accounts in parallel."""
        urls = await asyncio.gather(*[self.get_proxy(acc_id) for acc_id in account_ids])
        return dict(zip(account_ids, urls, strict=False))

    @beartype
    async def report_failure(self, account_id: str) -> bool:
        """Report a proxy failure for an account.

        Increments the failure counter.  When the threshold is reached
        the port status is verified via the ASocks API and, if dead,
        replaced automatically.

        Returns:
            ``True`` if the proxy was replaced.
        """
        async with self._lock:
            slot_idx = self._account_map.get(account_id)
            if slot_idx is None:
                return False

            slot = self._slots[slot_idx]
            slot.failure_count += 1
            slot.last_failure_ts = time.monotonic()

            if slot.failure_count >= self._failure_threshold:
                return await self._check_and_replace(slot_idx)

            return False

    @beartype
    async def report_failures(self, account_ids: list[str]) -> dict[str, bool]:
        """Report failures for multiple accounts in parallel."""
        results = await asyncio.gather(*[self.report_failure(acc_id) for acc_id in account_ids])
        return dict(zip(account_ids, results, strict=False))

    @beartype
    async def force_replace(self, account_id: str) -> str | None:
        """Force-replace the proxy for an account immediately.

        Returns:
            New proxy URL, or ``None`` on failure.
        """
        async with self._lock:
            slot_idx = self._account_map.get(account_id)
            if slot_idx is None:
                return None

            replaced = await self._check_and_replace(slot_idx, force=True)
            if replaced:
                return self._slots[slot_idx].port.proxy_url
            return None

    @beartype
    async def release_account(self, account_id: str) -> None:
        """Unbind an account from its proxy (and remove it from the store)."""
        async with self._lock:
            slot_idx = self._account_map.pop(account_id, None)
            if slot_idx is not None and slot_idx < len(self._slots):
                self._slots[slot_idx].assigned_accounts.discard(account_id)
        if self._store is not None:
            try:
                await self._store.delete(account_id)
            except Exception:  # noqa: BLE001
                logger.warning("ProxyStore.delete(%s) failed", account_id, exc_info=True)

    async def _persist_binding(self, account_id: str, port_id: int) -> None:
        """Persist a single binding, swallowing store errors."""
        if self._store is None:
            return
        try:
            await self._store.save(account_id, port_id)
        except Exception:  # noqa: BLE001
            logger.warning("ProxyStore.save(%s) failed", account_id, exc_info=True)

    # ── Monitoring ────────────────────────────────────────────────────── #

    @beartype
    async def check_pool_health(self) -> ProxyPoolStats:
        """Check the health of the entire pool via the ASocks API."""
        async with self._lock:
            active_slots = [s for s in self._slots if not s.is_dead]
            if active_slots:
                checks = await asyncio.gather(
                    *[self._api_health_check(s.port.id) for s in active_slots]
                )
                for slot, is_alive in zip(active_slots, checks, strict=False):
                    if not is_alive:
                        slot.is_dead = True
                        logger.warning("Port %d marked dead by API check", slot.port.id)
        return self.stats

    @property
    def stats(self) -> ProxyPoolStats:
        """Current pool statistics snapshot."""
        alive = sum(1 for s in self._slots if not s.is_dead)
        dead = sum(1 for s in self._slots if s.is_dead)
        return ProxyPoolStats(
            total=len(self._slots),
            alive=alive,
            dead=dead,
            replaced=self._replaced_total,
            accounts=len(self._account_map),
            api_checks=self._api_checks,
        )

    @property
    def account_map(self) -> dict[str, str]:
        """Current ``account_id → proxy_url`` mapping (copy)."""
        result: dict[str, str] = {}
        for acc_id, slot_idx in self._account_map.items():
            if slot_idx < len(self._slots):
                result[acc_id] = self._slots[slot_idx].port.proxy_url
        return result

    @beartype
    async def shutdown(self) -> None:
        """Stop the pool and background monitor."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None
        logger.info("ProxyPool shut down. Stats: %s", self.stats)

    @beartype
    async def replace_dead_proxies(self) -> int:
        """Replace all dead proxies in parallel.

        Returns:
            Number of successfully replaced proxies.
        """
        async with self._lock:
            dead_indices = [i for i, s in enumerate(self._slots) if s.is_dead]
            if not dead_indices:
                return 0
            results = await asyncio.gather(*[self._replace_slot(i) for i in dead_indices])
            return sum(1 for ok in results if ok)

    # ── Strategy helpers ──────────────────────────────────────────────── #

    def _get_sticky(
        self,
        account_id: str,
        alive_slots: list[tuple[int, _ProxySlot]],
    ) -> tuple[str, int | None]:
        """Return ``(url, port_id_to_persist)``; port id is ``None`` when the
        account was already bound (nothing new to persist)."""
        if account_id in self._account_map:
            idx = self._account_map[account_id]
            slot = self._slots[idx]
            if not slot.is_dead:
                return slot.port.proxy_url, None
            slot.assigned_accounts.discard(account_id)

        # Bind to the least-loaded alive slot for even fan-out.
        best_idx, best_slot = min(alive_slots, key=lambda x: len(x[1].assigned_accounts))
        self._account_map[account_id] = best_idx
        best_slot.assigned_accounts.add(account_id)
        return best_slot.port.proxy_url, best_slot.port.id

    def _get_round_robin(
        self,
        account_id: str | None,
        alive_slots: list[tuple[int, _ProxySlot]],
    ) -> tuple[str, int | None]:
        slot_idx, slot = alive_slots[self._rr_index % len(alive_slots)]
        self._rr_index += 1
        if account_id:
            self._account_map[account_id] = slot_idx
            slot.assigned_accounts.add(account_id)
        # Round-robin binding changes every call, so it is not persisted.
        return slot.port.proxy_url, None

    def _get_random(
        self,
        account_id: str | None,
        alive_slots: list[tuple[int, _ProxySlot]],
    ) -> tuple[str, int | None]:
        slot_idx, slot = random.choice(alive_slots)  # noqa: S311
        if account_id:
            self._account_map[account_id] = slot_idx
            slot.assigned_accounts.add(account_id)
        # Random binding changes every call, so it is not persisted.
        return slot.port.proxy_url, None

    # ── Internal — API health check ───────────────────────────────────── #

    async def _api_health_check(self, port_id: int) -> bool:
        """Check port status via the ASocks REST API (zero traffic)."""
        self._api_checks += 1
        try:
            port_info = await self._client.get_port(port_id)
            return port_info.is_active
        except Exception:  # noqa: BLE001
            logger.debug("API health check failed for port %d", port_id)
            return False

    async def _check_and_replace(self, slot_idx: int, *, force: bool = False) -> bool:
        """Verify port via API and replace if dead."""
        slot = self._slots[slot_idx]
        is_alive = await self._api_health_check(slot.port.id)

        if is_alive and not force:
            slot.failure_count = 0
            return False

        slot.is_dead = True
        return await self._replace_slot(slot_idx)

    async def _replace_slot(self, slot_idx: int) -> bool:
        """Replace the proxy in a given slot."""
        old_slot = self._slots[slot_idx]
        old_id = old_slot.port.id

        try:
            new_ports = await self._create_ports(1)
            if not new_ports:
                logger.error("Failed to create replacement for port %d", old_id)
                return False

            new_slot = _ProxySlot(
                port=new_ports[0],
                assigned_accounts=old_slot.assigned_accounts.copy(),
            )
            self._slots[slot_idx] = new_slot
            self._replaced_total += 1
            # The accounts keep their slot index but the underlying port id
            # changed — persist the new binding so it survives a restart.
            for account_id in new_slot.assigned_accounts:
                await self._persist_binding(account_id, new_ports[0].id)
            logger.info(
                "Replaced port %d -> %d (%d accounts reassigned)",
                old_id,
                new_ports[0].id,
                len(new_slot.assigned_accounts),
            )
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to replace port %d", old_id)
            return False

    # _fetch_matching_ports and _create_ports inherited from PortManagerMixin

    # ── Background monitor ────────────────────────────────────────────── #

    async def _background_monitor(self) -> None:
        """Periodically check pool health and replace dead proxies."""
        while True:
            try:
                await asyncio.sleep(self._monitor_interval)
                await self.check_pool_health()
                replaced = await self.replace_dead_proxies()
                if replaced:
                    logger.info("Background monitor replaced %d proxies", replaced)
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("Background monitor error")
