"""Comprehensive tests for ProxyPool manager."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from asockslib.client import ASocksClient
from asockslib.exceptions import NoAvailableProxyError
from asockslib.models import (
    PortInfo,
    PortListResponse,
)
from asockslib.proxy_pool import PoolStrategy, ProxyPool, ProxyPoolStats


def _make_port(port_id: int = 1, *, status: int = 1) -> PortInfo:
    """Helper to create a PortInfo with the given id."""
    return PortInfo(
        id=port_id,
        host="proxy.asocks.com",
        port=10000 + port_id,
        login=f"user{port_id}",
        password=f"pass{port_id}",
        protocol="socks5",
        country="United States",
        country_code="US",
        city="New York",
        state="NY",
        status=status,
        name=f"port-{port_id}",
    )


@pytest.fixture()
def mock_client() -> AsyncMock:
    """Return a fully mocked ASocksClient."""
    client = AsyncMock(spec=ASocksClient)
    client.list_ports = AsyncMock()
    client.create_ports = AsyncMock()
    client.get_port = AsyncMock()
    return client


# --------------------------------------------------------------------------- #
#  Initialization
# --------------------------------------------------------------------------- #


class TestInit:
    """Test ProxyPool.__init__."""

    def test_defaults(self, mock_client: AsyncMock) -> None:
        pool = ProxyPool(mock_client, country_code="US")
        assert pool._country_code == "US"
        assert pool._pool_size == 10
        assert pool._strategy == PoolStrategy.STICKY
        assert pool._failure_threshold == 3
        assert pool._initialized is False

    def test_custom_params(self, mock_client: AsyncMock) -> None:
        pool = ProxyPool(
            mock_client,
            country_code="DE",
            city="Berlin",
            state="Berlin",
            pool_size=50,
            type_id=2,
            proxy_type_id=3,
            server_port_type_id=0,
            ttl=7,
            traffic_limit=100,
            strategy=PoolStrategy.ROUND_ROBIN,
            failure_threshold=5,
        )
        assert pool._country_code == "DE"
        assert pool._city == "Berlin"
        assert pool._state == "Berlin"
        assert pool._pool_size == 50
        assert pool._type_id == 2
        assert pool._proxy_type_id == 3
        assert pool._server_port_type_id == 0
        assert pool._ttl == 7
        assert pool._traffic_limit == 100
        assert pool._strategy == PoolStrategy.ROUND_ROBIN
        assert pool._failure_threshold == 5


# --------------------------------------------------------------------------- #
#  initialize()
# --------------------------------------------------------------------------- #


class TestInitialize:
    """Test ProxyPool.initialize()."""

    @pytest.mark.asyncio()
    async def test_initialize_with_existing_ports(self, mock_client: AsyncMock) -> None:
        """Reuse existing active ports when available."""
        ports = [_make_port(i) for i in range(5)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)
        mock_client.create_ports.return_value = []

        pool = ProxyPool(mock_client, country_code="US", pool_size=5)
        await pool.initialize()

        assert pool._initialized is True
        assert len(pool._slots) == 5
        mock_client.create_ports.assert_not_called()

    @pytest.mark.asyncio()
    async def test_initialize_creates_deficit(self, mock_client: AsyncMock) -> None:
        """Create ports when existing are fewer than pool_size."""
        existing = [_make_port(1), _make_port(2)]
        new_ports = [_make_port(3), _make_port(4), _make_port(5)]

        mock_client.list_ports.return_value = PortListResponse(success=True, message=existing)
        mock_client.create_ports.return_value = new_ports

        pool = ProxyPool(mock_client, country_code="US", pool_size=5)
        await pool.initialize()

        assert len(pool._slots) == 5
        mock_client.create_ports.assert_called_once()
        req = mock_client.create_ports.call_args[0][0]
        assert req.count == 3

    @pytest.mark.asyncio()
    async def test_initialize_empty_creates_all(self, mock_client: AsyncMock) -> None:
        """Create all ports if none exist."""
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[])
        mock_client.create_ports.return_value = [_make_port(i) for i in range(3)]

        pool = ProxyPool(mock_client, country_code="US", pool_size=3)
        await pool.initialize()

        assert len(pool._slots) == 3
        req = mock_client.create_ports.call_args[0][0]
        assert req.count == 3


# --------------------------------------------------------------------------- #
#  get_proxy() — STICKY
# --------------------------------------------------------------------------- #


class TestGetProxySticky:
    """Test get_proxy() with STICKY strategy."""

    @pytest.mark.asyncio()
    async def test_not_initialized_raises(self, mock_client: AsyncMock) -> None:
        pool = ProxyPool(mock_client)
        with pytest.raises(NoAvailableProxyError, match="not initialized"):
            await pool.get_proxy("acc1")

    @pytest.mark.asyncio()
    async def test_sticky_assigns_same_proxy(self, mock_client: AsyncMock) -> None:
        """STICKY: same account always gets same proxy."""
        ports = [_make_port(1), _make_port(2), _make_port(3)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=3, strategy=PoolStrategy.STICKY)
        await pool.initialize()

        url1 = await pool.get_proxy("acc1")
        url2 = await pool.get_proxy("acc1")
        assert url1 == url2

    @pytest.mark.asyncio()
    async def test_sticky_distributes_evenly(self, mock_client: AsyncMock) -> None:
        """STICKY: accounts distributed across slots."""
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=2, strategy=PoolStrategy.STICKY)
        await pool.initialize()

        url1 = await pool.get_proxy("acc1")
        url2 = await pool.get_proxy("acc2")
        # Both assigned, possibly to different slots
        assert url1 is not None
        assert url2 is not None

    @pytest.mark.asyncio()
    async def test_sticky_reassigns_on_dead(self, mock_client: AsyncMock) -> None:
        """STICKY: reassign to alive slot if current is dead."""
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=2, strategy=PoolStrategy.STICKY)
        await pool.initialize()

        url1 = await pool.get_proxy("acc1")
        # Kill the assigned slot
        idx = pool._account_map["acc1"]
        pool._slots[idx].is_dead = True

        url2 = await pool.get_proxy("acc1")
        assert url2 != url1  # Reassigned to another


# --------------------------------------------------------------------------- #
#  get_proxy() — ROUND_ROBIN
# --------------------------------------------------------------------------- #


class TestGetProxyRoundRobin:
    """Test get_proxy() with ROUND_ROBIN strategy."""

    @pytest.mark.asyncio()
    async def test_round_robin_cycles(self, mock_client: AsyncMock) -> None:
        """ROUND_ROBIN: cycles through alive slots."""
        ports = [_make_port(1), _make_port(2), _make_port(3)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=3, strategy=PoolStrategy.ROUND_ROBIN)
        await pool.initialize()

        urls = [await pool.get_proxy(f"acc{i}") for i in range(6)]
        # Should cycle through all 3 slots twice
        assert len(set(urls)) == 3


# --------------------------------------------------------------------------- #
#  get_proxy() — RANDOM
# --------------------------------------------------------------------------- #


class TestGetProxyRandom:
    """Test get_proxy() with RANDOM strategy."""

    @pytest.mark.asyncio()
    async def test_random_returns_alive(self, mock_client: AsyncMock) -> None:
        """RANDOM: returns a live proxy."""
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=2, strategy=PoolStrategy.RANDOM)
        await pool.initialize()

        url = await pool.get_proxy("acc1")
        assert "proxy.asocks.com" in url


# --------------------------------------------------------------------------- #
#  get_proxies() — bulk
# --------------------------------------------------------------------------- #


class TestGetProxies:
    """Test get_proxies() bulk method."""

    @pytest.mark.asyncio()
    async def test_bulk_mapping(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(i) for i in range(5)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=5)
        await pool.initialize()

        mapping = await pool.get_proxies(["a1", "a2", "a3"])
        assert len(mapping) == 3
        assert all("proxy.asocks.com" in v for v in mapping.values())


# --------------------------------------------------------------------------- #
#  report_failure()
# --------------------------------------------------------------------------- #


class TestReportFailure:
    """Test report_failure() and auto-replacement."""

    @pytest.mark.asyncio()
    async def test_below_threshold_no_replace(self, mock_client: AsyncMock) -> None:
        """Failure count below threshold — no replacement."""
        ports = [_make_port(1)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=1, failure_threshold=3)
        await pool.initialize()
        await pool.get_proxy("acc1")

        replaced = await pool.report_failure("acc1")
        assert replaced is False
        assert pool._slots[0].failure_count == 1

    @pytest.mark.asyncio()
    async def test_threshold_triggers_api_check(self, mock_client: AsyncMock) -> None:
        """At threshold — triggers API health check."""
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)
        # Port is still alive per API
        mock_client.get_port.return_value = _make_port(1, status=1)

        pool = ProxyPool(mock_client, pool_size=2, failure_threshold=2)
        await pool.initialize()
        await pool.get_proxy("acc1")

        await pool.report_failure("acc1")
        replaced = await pool.report_failure("acc1")

        # API said alive → not replaced, counter reset
        assert replaced is False
        assert pool._api_checks >= 1
        assert pool._slots[0].failure_count == 0

    @pytest.mark.asyncio()
    async def test_dead_proxy_replaced(self, mock_client: AsyncMock) -> None:
        """Dead proxy (API says inactive) triggers replacement."""
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)
        # API says port is dead
        mock_client.get_port.return_value = _make_port(1, status=0)
        # Replacement port
        mock_client.create_ports.return_value = [_make_port(99)]

        pool = ProxyPool(mock_client, pool_size=2, failure_threshold=2)
        await pool.initialize()
        await pool.get_proxy("acc1")

        await pool.report_failure("acc1")
        replaced = await pool.report_failure("acc1")

        assert replaced is True
        assert pool._replaced_total == 1
        # New port should be slot 0
        assert pool._slots[pool._account_map["acc1"]].port.id == 99

    @pytest.mark.asyncio()
    async def test_unknown_account_no_crash(self, mock_client: AsyncMock) -> None:
        """report_failure for unknown account returns False."""
        pool = ProxyPool(mock_client, pool_size=1)
        pool._initialized = True

        result = await pool.report_failure("unknown")
        assert result is False


# --------------------------------------------------------------------------- #
#  report_failures() — bulk
# --------------------------------------------------------------------------- #


class TestReportFailures:
    """Test bulk report_failures()."""

    @pytest.mark.asyncio()
    async def test_bulk_failures(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=1, failure_threshold=5)
        await pool.initialize()
        await pool.get_proxy("a1")

        results = await pool.report_failures(["a1", "unknown"])
        assert results["a1"] is False
        assert results["unknown"] is False


# --------------------------------------------------------------------------- #
#  force_replace()
# --------------------------------------------------------------------------- #


class TestForceReplace:
    """Test force_replace()."""

    @pytest.mark.asyncio()
    async def test_force_replace_success(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)
        mock_client.get_port.return_value = _make_port(1, status=1)
        mock_client.create_ports.return_value = [_make_port(50)]

        pool = ProxyPool(mock_client, pool_size=1)
        await pool.initialize()
        await pool.get_proxy("acc1")

        new_url = await pool.force_replace("acc1")
        assert new_url is not None
        assert "10050" in new_url
        assert pool._replaced_total == 1

    @pytest.mark.asyncio()
    async def test_force_replace_unknown(self, mock_client: AsyncMock) -> None:
        pool = ProxyPool(mock_client)
        pool._initialized = True
        result = await pool.force_replace("unknown")
        assert result is None


# --------------------------------------------------------------------------- #
#  release_account()
# --------------------------------------------------------------------------- #


class TestReleaseAccount:
    """Test release_account()."""

    @pytest.mark.asyncio()
    async def test_release(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=1)
        await pool.initialize()
        await pool.get_proxy("acc1")

        assert "acc1" in pool._account_map
        await pool.release_account("acc1")
        assert "acc1" not in pool._account_map


# --------------------------------------------------------------------------- #
#  check_pool_health()
# --------------------------------------------------------------------------- #


class TestCheckPoolHealth:
    """Test check_pool_health()."""

    @pytest.mark.asyncio()
    async def test_marks_dead_ports(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)
        # Port 1 alive, port 2 dead
        mock_client.get_port.side_effect = [
            _make_port(1, status=1),
            _make_port(2, status=0),
        ]

        pool = ProxyPool(mock_client, pool_size=2)
        await pool.initialize()

        stats = await pool.check_pool_health()
        assert stats.alive == 1
        assert stats.dead == 1
        assert pool._api_checks == 2


# --------------------------------------------------------------------------- #
#  stats property
# --------------------------------------------------------------------------- #


class TestStats:
    """Test stats property."""

    @pytest.mark.asyncio()
    async def test_initial_stats(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1), _make_port(2), _make_port(3)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=3)
        await pool.initialize()

        stats = pool.stats
        assert stats.total == 3
        assert stats.alive == 3
        assert stats.dead == 0
        assert stats.replaced == 0
        assert stats.accounts == 0
        assert stats.api_checks == 0


# --------------------------------------------------------------------------- #
#  account_map property
# --------------------------------------------------------------------------- #


class TestAccountMap:
    """Test account_map property."""

    @pytest.mark.asyncio()
    async def test_account_map(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=1)
        await pool.initialize()
        await pool.get_proxy("acc1")

        am = pool.account_map
        assert "acc1" in am
        assert "proxy.asocks.com" in am["acc1"]


# --------------------------------------------------------------------------- #
#  replace_dead_proxies()
# --------------------------------------------------------------------------- #


class TestReplaceDeadProxies:
    """Test replace_dead_proxies()."""

    @pytest.mark.asyncio()
    async def test_replaces_dead(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)
        mock_client.create_ports.return_value = [_make_port(99)]

        pool = ProxyPool(mock_client, pool_size=2)
        await pool.initialize()

        # Mark one as dead
        pool._slots[0].is_dead = True
        replaced = await pool.replace_dead_proxies()

        assert replaced == 1
        assert pool._slots[0].port.id == 99
        assert not pool._slots[0].is_dead


# --------------------------------------------------------------------------- #
#  shutdown()
# --------------------------------------------------------------------------- #


class TestShutdown:
    """Test shutdown()."""

    @pytest.mark.asyncio()
    async def test_shutdown_no_monitor(self, mock_client: AsyncMock) -> None:
        pool = ProxyPool(mock_client)
        pool._initialized = True
        await pool.shutdown()  # Should not raise


# --------------------------------------------------------------------------- #
#  All proxies dead
# --------------------------------------------------------------------------- #


class TestAllDead:
    """Test behavior when all proxies are dead."""

    @pytest.mark.asyncio()
    async def test_all_dead_raises(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        pool = ProxyPool(mock_client, pool_size=1)
        await pool.initialize()

        pool._slots[0].is_dead = True
        with pytest.raises(NoAvailableProxyError, match="All proxies.*dead"):
            await pool.get_proxy("acc1")


# --------------------------------------------------------------------------- #
#  _api_health_check()
# --------------------------------------------------------------------------- #


class TestApiHealthCheck:
    """Test _api_health_check() (zero-traffic)."""

    @pytest.mark.asyncio()
    async def test_active_port_returns_true(self, mock_client: AsyncMock) -> None:
        mock_client.get_port.return_value = _make_port(1, status=1)

        pool = ProxyPool(mock_client)
        result = await pool._api_health_check(1)

        assert result is True
        assert pool._api_checks == 1

    @pytest.mark.asyncio()
    async def test_inactive_port_returns_false(self, mock_client: AsyncMock) -> None:
        mock_client.get_port.return_value = _make_port(1, status=0)

        pool = ProxyPool(mock_client)
        result = await pool._api_health_check(1)

        assert result is False

    @pytest.mark.asyncio()
    async def test_api_exception_returns_false(self, mock_client: AsyncMock) -> None:
        mock_client.get_port.side_effect = Exception("API down")

        pool = ProxyPool(mock_client)
        result = await pool._api_health_check(1)

        assert result is False
        assert pool._api_checks == 1


# --------------------------------------------------------------------------- #
#  PoolStrategy enum
# --------------------------------------------------------------------------- #


class TestPoolStrategy:
    """Test PoolStrategy enum."""

    def test_values(self) -> None:
        assert PoolStrategy.STICKY == "sticky"
        assert PoolStrategy.ROUND_ROBIN == "round_robin"
        assert PoolStrategy.RANDOM == "random"


# --------------------------------------------------------------------------- #
#  ProxyPoolStats
# --------------------------------------------------------------------------- #


class TestProxyPoolStats:
    """Test ProxyPoolStats dataclass."""

    def test_stats_attrs(self) -> None:
        s = ProxyPoolStats(total=10, alive=8, dead=2, replaced=5, accounts=100, api_checks=50)
        assert s.total == 10
        assert s.alive == 8
        assert s.dead == 2
        assert s.replaced == 5
        assert s.accounts == 100
        assert s.api_checks == 50


# --------------------------------------------------------------------------- #
#  _create_ports passes correct params
# --------------------------------------------------------------------------- #


class TestCreatePortsParams:
    """Test that create_ports is called with correct parameters."""

    @pytest.mark.asyncio()
    async def test_params_forwarded(self, mock_client: AsyncMock) -> None:
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[])
        mock_client.create_ports.return_value = [_make_port(1)]

        pool = ProxyPool(
            mock_client,
            country_code="DE",
            city="Berlin",
            state="Berlin",
            pool_size=1,
            type_id=2,
            proxy_type_id=3,
            server_port_type_id=0,
            ttl=7,
            traffic_limit=100,
        )
        await pool.initialize()

        req = mock_client.create_ports.call_args[0][0]
        assert req.country_code == "DE"
        assert req.city == "Berlin"
        assert req.state == "Berlin"
        assert req.type_id == 2
        assert req.proxy_type_id == 3
        assert req.server_port_type_id == 0
        assert req.ttl == 7
        assert req.traffic_limit == 100
