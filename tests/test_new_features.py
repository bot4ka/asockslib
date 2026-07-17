"""Tests for the audit additions: pagination, geo filtering, pluggable
persistence store, benchmark-on-init and input validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from asockslib.benchmark import ProxyBenchmarkResult
from asockslib.client import ASocksClient
from asockslib.models import PortInfo, PortListResponse
from asockslib.proxy_pool import ProxyPool


def _make_port(
    port_id: int, *, status: int = 1, city: str = "New York", state: str = "NY"
) -> PortInfo:
    return PortInfo(
        id=port_id,
        host="proxy.asocks.com",
        port=10000 + port_id,
        login=f"user{port_id}",
        password=f"pass{port_id}",
        protocol="socks5",
        country="United States",
        country_code="US",
        city=city,
        state=state,
        status=status,
        name=f"port-{port_id}",
    )


@pytest.fixture()
def mock_client() -> AsyncMock:
    client = AsyncMock(spec=ASocksClient)
    client.list_ports = AsyncMock()
    client.create_ports = AsyncMock()
    client.get_port = AsyncMock()
    client.delete_port = AsyncMock()
    return client


class DictStore:
    """In-memory ProxyStore for testing persistence wiring."""

    def __init__(self, initial: dict[str, int] | None = None) -> None:
        self.data: dict[str, int] = dict(initial or {})
        self.saves: list[tuple[str, int]] = []
        self.deletes: list[str] = []

    async def load(self) -> dict[str, int]:
        return dict(self.data)

    async def save(self, account_id: str, port_id: int) -> None:
        self.data[account_id] = port_id
        self.saves.append((account_id, port_id))

    async def delete(self, account_id: str) -> None:
        self.data.pop(account_id, None)
        self.deletes.append(account_id)


# --------------------------------------------------------------------------- #
#  Pagination — _fetch_matching_ports
# --------------------------------------------------------------------------- #


class TestPagination:
    @pytest.mark.asyncio()
    async def test_fetches_beyond_first_page(self, mock_client: AsyncMock) -> None:
        """A full first page triggers a second request (regression: 50-cap)."""
        page1 = [_make_port(i) for i in range(200)]
        page2 = [_make_port(1000 + i) for i in range(30)]

        async def _list_ports(filters: object) -> PortListResponse:
            page = filters.page  # type: ignore[attr-defined]
            return PortListResponse(success=True, message=page1 if page == 1 else page2)

        mock_client.list_ports.side_effect = _list_ports

        pool = ProxyPool(mock_client, country_code="US", pool_size=250)
        collected = await pool._fetch_matching_ports(limit=250)

        assert len(collected) == 230
        assert mock_client.list_ports.await_count == 2

    @pytest.mark.asyncio()
    async def test_stops_at_limit(self, mock_client: AsyncMock) -> None:
        page1 = [_make_port(i) for i in range(200)]
        page2 = [_make_port(1000 + i) for i in range(30)]

        async def _list_ports(filters: object) -> PortListResponse:
            page = filters.page  # type: ignore[attr-defined]
            return PortListResponse(success=True, message=page1 if page == 1 else page2)

        mock_client.list_ports.side_effect = _list_ports

        pool = ProxyPool(mock_client, pool_size=210)
        collected = await pool._fetch_matching_ports(limit=210)
        assert len(collected) == 210


# --------------------------------------------------------------------------- #
#  Geo filtering
# --------------------------------------------------------------------------- #


class TestGeoFilter:
    @pytest.mark.asyncio()
    async def test_wrong_city_excluded(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1, city="New York"), _make_port(2, city="Boston")]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, country_code="US", city="New York", pool_size=5)
        collected = await pool._fetch_matching_ports()
        assert [p.id for p in collected] == [1]

    @pytest.mark.asyncio()
    async def test_missing_city_metadata_kept(self, mock_client: AsyncMock) -> None:
        """Ports lacking city metadata are trusted (not discarded)."""
        ports = [_make_port(1, city=""), _make_port(2, city="Boston")]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, country_code="US", city="New York", pool_size=5)
        collected = await pool._fetch_matching_ports()
        assert [p.id for p in collected] == [1]


# --------------------------------------------------------------------------- #
#  Pluggable persistence store
# --------------------------------------------------------------------------- #


class TestProxyStore:
    @pytest.mark.asyncio()
    async def test_restore_bindings_on_init(self, mock_client: AsyncMock) -> None:
        store = DictStore({"acc1": 2})
        ports = [_make_port(1), _make_port(2), _make_port(3)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=3, store=store)
        await pool.initialize()

        assert "acc1" in pool._account_map
        url = await pool.get_proxy("acc1")
        assert ":10002" in url  # bound to the restored port id 2

    @pytest.mark.asyncio()
    async def test_save_on_assignment(self, mock_client: AsyncMock) -> None:
        store = DictStore()
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=2, store=store)
        await pool.initialize()
        await pool.get_proxy("acc1")

        assert "acc1" in store.data
        assert len(store.saves) == 1

    @pytest.mark.asyncio()
    async def test_delete_on_release(self, mock_client: AsyncMock) -> None:
        store = DictStore()
        mock_client.list_ports.return_value = PortListResponse(
            success=True, message=[_make_port(1)]
        )
        pool = ProxyPool(mock_client, pool_size=1, store=store)
        await pool.initialize()
        await pool.get_proxy("acc1")
        await pool.release_account("acc1")

        assert "acc1" not in store.data
        assert store.deletes == ["acc1"]

    @pytest.mark.asyncio()
    async def test_replacement_persists_new_port(self, mock_client: AsyncMock) -> None:
        store = DictStore()
        mock_client.list_ports.return_value = PortListResponse(
            success=True, message=[_make_port(1)]
        )
        mock_client.get_port.return_value = _make_port(1, status=0)  # dead
        mock_client.create_ports.return_value = [_make_port(99)]

        pool = ProxyPool(mock_client, pool_size=1, store=store)
        await pool.initialize()
        await pool.get_proxy("acc1")

        new_url = await pool.force_replace("acc1")
        assert new_url is not None
        assert store.data["acc1"] == 99  # rebinding persisted

    @pytest.mark.asyncio()
    async def test_stale_binding_dropped(self, mock_client: AsyncMock) -> None:
        """A persisted port no longer in the pool is ignored on restore."""
        store = DictStore({"ghost": 777})
        mock_client.list_ports.return_value = PortListResponse(
            success=True, message=[_make_port(1)]
        )
        pool = ProxyPool(mock_client, pool_size=1, store=store)
        await pool.initialize()
        assert "ghost" not in pool._account_map


# --------------------------------------------------------------------------- #
#  benchmark_on_init
# --------------------------------------------------------------------------- #


class TestBenchmarkOnInit:
    @pytest.mark.asyncio()
    async def test_keeps_fastest_and_deletes_rest(self, mock_client: AsyncMock) -> None:
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[])
        created = [_make_port(i) for i in range(1, 5)]  # ids 1..4
        mock_client.create_ports.return_value = created

        async def fake_bench(
            urls: list[str], *, timeout: float = 5.0
        ) -> list[ProxyBenchmarkResult]:
            results: list[ProxyBenchmarkResult] = []
            for u in urls:
                fast = ":10001" in u or ":10002" in u  # ports 1 and 2 are fastest
                results.append(
                    ProxyBenchmarkResult(
                        proxy_url=u, latency_ms=10.0 if fast else 100.0, is_alive=True
                    )
                )
            results.sort(key=lambda r: r.latency_ms or float("inf"))
            return results

        with patch("asockslib.benchmark.benchmark_proxies", side_effect=fake_bench):
            pool = ProxyPool(
                mock_client,
                pool_size=2,
                benchmark_on_init=True,
                benchmark_oversample=2.0,
            )
            await pool.initialize()

        kept_ids = {slot.port.id for slot in pool._slots}
        assert kept_ids == {1, 2}
        deleted = {c.args[0] for c in mock_client.delete_port.call_args_list}
        assert deleted == {3, 4}


# --------------------------------------------------------------------------- #
#  Input validation
# --------------------------------------------------------------------------- #


class TestValidation:
    def test_pool_size_must_be_positive(self, mock_client: AsyncMock) -> None:
        with pytest.raises(ValueError, match="pool_size"):
            ProxyPool(mock_client, pool_size=0)

    def test_failure_threshold_must_be_positive(self, mock_client: AsyncMock) -> None:
        with pytest.raises(ValueError, match="failure_threshold"):
            ProxyPool(mock_client, failure_threshold=0)

    def test_benchmark_oversample_floor(self, mock_client: AsyncMock) -> None:
        with pytest.raises(ValueError, match="benchmark_oversample"):
            ProxyPool(mock_client, benchmark_oversample=0.5)
