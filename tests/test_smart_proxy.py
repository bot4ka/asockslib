"""Comprehensive tests for SmartProxy manager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from asockslib.client import ASocksClient
from asockslib.exceptions import NoAvailableProxyError
from asockslib.models import (
    CreatePortRequest,
    PortFilterParams,
    PortInfo,
    PortListResponse,
    PortStatus,
)
from asockslib.smart_proxy import SmartProxy


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
    """Return a fully mocked ASocksClient that passes beartype checks."""
    client = AsyncMock(spec=ASocksClient)
    client.list_ports = AsyncMock()
    client.create_ports = AsyncMock()
    return client


# --------------------------------------------------------------------------- #
#  __init__
# --------------------------------------------------------------------------- #


class TestSmartProxyInit:
    """Tests for SmartProxy constructor."""

    def test_defaults(self, mock_client: AsyncMock) -> None:
        sp = SmartProxy(mock_client)
        assert sp.pool_size == 0
        assert sp._country_code == ""
        assert sp._city == ""

    def test_custom_params(self, mock_client: AsyncMock) -> None:
        sp = SmartProxy(
            mock_client,
            country_code="DE",
            city="Berlin",
            health_timeout=5.0,
        )
        assert sp._country_code == "DE"
        assert sp._city == "Berlin"
        assert sp._health_timeout == 5.0


# --------------------------------------------------------------------------- #
#  initialize
# --------------------------------------------------------------------------- #


class TestInitialize:
    """Tests for SmartProxy.initialize()."""

    async def test_initialize_from_existing(self, mock_client: AsyncMock) -> None:
        """Pool fills from existing ports when enough are available."""
        ports = [_make_port(i) for i in range(5)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)
        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=3)

        assert sp.pool_size == 3
        mock_client.create_ports.assert_not_called()

    async def test_initialize_creates_deficit(self, mock_client: AsyncMock) -> None:
        """Creates new ports if not enough existing ones."""
        mock_client.list_ports.return_value = PortListResponse(
            success=True, message=[_make_port(1)]
        )
        new_ports = [_make_port(10), _make_port(11)]
        mock_client.create_ports.return_value = new_ports

        sp = SmartProxy(mock_client, country_code="US")
        await sp.initialize(pool_size=3)

        assert sp.pool_size == 3
        mock_client.create_ports.assert_called_once()
        # deficit = 3 - 1 = 2
        req = mock_client.create_ports.call_args[0][0]
        assert isinstance(req, CreatePortRequest)
        assert req.count == 2

    async def test_initialize_empty_existing(self, mock_client: AsyncMock) -> None:
        """All ports created from scratch when none exist."""
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[])
        mock_client.create_ports.return_value = [_make_port(i) for i in range(5)]

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=5)

        assert sp.pool_size == 5
        req = mock_client.create_ports.call_args[0][0]
        assert req.count == 5


# --------------------------------------------------------------------------- #
#  get_proxy
# --------------------------------------------------------------------------- #


class TestGetProxy:
    """Tests for SmartProxy.get_proxy()."""

    async def test_get_proxy_healthy(self, mock_client: AsyncMock) -> None:
        """Returns proxy URL when proxy is healthy."""
        port = _make_port(1)
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[port])

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=1)

        with patch.object(sp, "_is_healthy", return_value=True):
            url = await sp.get_proxy()
            assert url == port.proxy_url
            assert "socks5://" in url

    async def test_get_proxy_rotates(self, mock_client: AsyncMock) -> None:
        """Cycles through pool in round-robin."""
        ports = [_make_port(i) for i in range(3)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=3)

        with patch.object(sp, "_is_healthy", return_value=True):
            url1 = await sp.get_proxy()
            url2 = await sp.get_proxy()
            url3 = await sp.get_proxy()
            url4 = await sp.get_proxy()  # wraps around

            # All three should differ
            assert url1 != url2
            assert url2 != url3
            # url4 should wrap to url1
            assert url4 == url1

    async def test_get_proxy_empty_pool_raises(self, mock_client: AsyncMock) -> None:
        """Raises NoAvailableProxyError on empty pool."""
        sp = SmartProxy(mock_client)
        with pytest.raises(NoAvailableProxyError, match="empty"):
            await sp.get_proxy()

    async def test_get_proxy_replaces_unhealthy(self, mock_client: AsyncMock) -> None:
        """Replaces unhealthy proxy and returns replacement URL."""
        old_port = _make_port(1)
        new_port = _make_port(99)

        mock_client.list_ports.return_value = PortListResponse(success=True, message=[old_port])
        mock_client.create_ports.return_value = [new_port]

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=1)

        with patch.object(sp, "_is_healthy", return_value=False):
            url = await sp.get_proxy()
            assert url == new_port.proxy_url

    async def test_get_proxy_all_fail(self, mock_client: AsyncMock) -> None:
        """Raises NoAvailableProxyError when all proxies fail."""
        port = _make_port(1)
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[port])
        mock_client.create_ports.return_value = []  # replacement also fails

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=1)

        with (
            patch.object(sp, "_is_healthy", return_value=False),
            pytest.raises(NoAvailableProxyError, match="failed"),
        ):
            await sp.get_proxy()


# --------------------------------------------------------------------------- #
#  get_all_proxies
# --------------------------------------------------------------------------- #


class TestGetAllProxies:
    """Tests for SmartProxy.get_all_proxies()."""

    async def test_returns_all_urls(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(i) for i in range(3)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=3)

        urls = await sp.get_all_proxies()
        assert len(urls) == 3
        for url in urls:
            assert "socks5://" in url

    async def test_empty_pool(self, mock_client: AsyncMock) -> None:
        sp = SmartProxy(mock_client)
        urls = await sp.get_all_proxies()
        assert urls == []


# --------------------------------------------------------------------------- #
#  health_check_all
# --------------------------------------------------------------------------- #


class TestHealthCheckAll:
    """Tests for SmartProxy.health_check_all()."""

    async def test_all_healthy(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=2)

        with patch.object(sp, "_is_healthy", return_value=True):
            results = await sp.health_check_all()
            assert results == {1: True, 2: True}

    async def test_some_unhealthy(self, mock_client: AsyncMock) -> None:
        ports = [_make_port(1), _make_port(2)]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=ports)

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=2)

        async def health_side_effect(proxy: PortInfo) -> bool:
            return proxy.id == 1  # only port 1 is healthy

        with patch.object(sp, "_is_healthy", side_effect=health_side_effect):
            results = await sp.health_check_all()
            assert results[1] is True
            assert results[2] is False

    async def test_empty_pool(self, mock_client: AsyncMock) -> None:
        sp = SmartProxy(mock_client)
        results = await sp.health_check_all()
        assert results == {}


# --------------------------------------------------------------------------- #
#  refresh_pool
# --------------------------------------------------------------------------- #


class TestRefreshPool:
    """Tests for SmartProxy.refresh_pool()."""

    async def test_refresh_replaces_unhealthy(self, mock_client: AsyncMock) -> None:
        old_port = _make_port(1)
        new_port = _make_port(99)
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[old_port])
        mock_client.create_ports.return_value = [new_port]

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=1)

        with patch.object(sp, "_is_healthy", return_value=False):
            replaced = await sp.refresh_pool()
            assert replaced == 1

    async def test_refresh_no_replacement_needed(self, mock_client: AsyncMock) -> None:
        port = _make_port(1)
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[port])

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=1)

        with patch.object(sp, "_is_healthy", return_value=True):
            replaced = await sp.refresh_pool()
            assert replaced == 0

    async def test_refresh_empty(self, mock_client: AsyncMock) -> None:
        sp = SmartProxy(mock_client)
        replaced = await sp.refresh_pool()
        assert replaced == 0


# --------------------------------------------------------------------------- #
#  pool_size property
# --------------------------------------------------------------------------- #


class TestPoolSize:
    """Tests for pool_size property."""

    def test_initial(self, mock_client: AsyncMock) -> None:
        sp = SmartProxy(mock_client)
        assert sp.pool_size == 0

    async def test_after_init(self, mock_client: AsyncMock) -> None:
        mock_client.list_ports.return_value = PortListResponse(
            success=True, message=[_make_port(i) for i in range(3)]
        )
        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=3)
        assert sp.pool_size == 3


# --------------------------------------------------------------------------- #
#  _is_healthy (internal)
# --------------------------------------------------------------------------- #


class TestIsHealthy:
    """Tests for _is_healthy internal method."""

    async def test_healthy_proxy(self, mock_client: AsyncMock) -> None:
        port = _make_port(1)
        sp = SmartProxy(mock_client)

        mock_response = MagicMock()
        mock_response.is_success = True

        with patch("asockslib.smart_proxy.httpx.AsyncClient") as mock_httpx:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_response
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await sp._is_healthy(port)
            assert result is True

    async def test_unhealthy_proxy_connection_error(self, mock_client: AsyncMock) -> None:
        port = _make_port(1)
        sp = SmartProxy(mock_client)

        with patch("asockslib.smart_proxy.httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("fail"))
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await sp._is_healthy(port)
            assert result is False

    async def test_unhealthy_proxy_timeout(self, mock_client: AsyncMock) -> None:
        port = _make_port(1)
        sp = SmartProxy(mock_client)

        with patch("asockslib.smart_proxy.httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__ = AsyncMock(
                side_effect=httpx.TimeoutException("timeout")
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await sp._is_healthy(port)
            assert result is False


# --------------------------------------------------------------------------- #
#  _fetch_matching_ports
# --------------------------------------------------------------------------- #


class TestFetchMatchingPorts:
    """Tests for _fetch_matching_ports internal method."""

    async def test_fetch_uses_filters(self, mock_client: AsyncMock) -> None:
        mock_client.list_ports.return_value = PortListResponse(
            success=True, message=[_make_port(1)]
        )
        sp = SmartProxy(mock_client, country_code="DE")
        result = await sp._fetch_matching_ports()

        assert len(result) == 1
        call_filter = mock_client.list_ports.call_args[0][0]
        assert isinstance(call_filter, PortFilterParams)
        assert call_filter.countryName == "DE"
        assert call_filter.status == PortStatus.ACTIVE

    async def test_fetch_no_country(self, mock_client: AsyncMock) -> None:
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[])
        sp = SmartProxy(mock_client)
        await sp._fetch_matching_ports()

        call_filter = mock_client.list_ports.call_args[0][0]
        assert call_filter.countryName is None


# --------------------------------------------------------------------------- #
#  _create_ports
# --------------------------------------------------------------------------- #


class TestCreatePorts:
    """Tests for _create_ports internal method."""

    async def test_creates_with_criteria(self, mock_client: AsyncMock) -> None:
        mock_client.create_ports.return_value = [_make_port(10)]
        sp = SmartProxy(mock_client, country_code="US", city="NYC")
        result = await sp._create_ports(3)

        assert len(result) == 1
        req = mock_client.create_ports.call_args[0][0]
        assert isinstance(req, CreatePortRequest)
        assert req.country_code == "US"
        assert req.city == "NYC"
        assert req.count == 3


# --------------------------------------------------------------------------- #
#  _replace_proxy
# --------------------------------------------------------------------------- #


class TestReplaceProxy:
    """Tests for _replace_proxy internal method."""

    async def test_replace_success(self, mock_client: AsyncMock) -> None:
        old_port = _make_port(1)
        new_port = _make_port(99)
        mock_client.create_ports.return_value = [new_port]
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[old_port])

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=1)

        replacement = await sp._replace_proxy(old_port)
        assert replacement is not None
        assert replacement.id == 99
        # old port should be removed, new one added
        assert old_port not in sp._pool
        assert new_port in sp._pool

    async def test_replace_failure(self, mock_client: AsyncMock) -> None:
        old_port = _make_port(1)
        mock_client.create_ports.side_effect = Exception("API error")
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[old_port])

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=1)

        replacement = await sp._replace_proxy(old_port)
        assert replacement is None

    async def test_replace_empty_result(self, mock_client: AsyncMock) -> None:
        old_port = _make_port(1)
        mock_client.create_ports.return_value = []
        mock_client.list_ports.return_value = PortListResponse(success=True, message=[old_port])

        sp = SmartProxy(mock_client)
        await sp.initialize(pool_size=1)

        replacement = await sp._replace_proxy(old_port)
        assert replacement is None
