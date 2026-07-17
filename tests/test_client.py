"""Tests for the ASocksClient (HTTP layer)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx
import pytest

from asockslib.client import ASocksClient
from asockslib.exceptions import (
    APIConnectionError,
    ASocksError,
    AuthenticationError,
    InsufficientBalanceError,
    PortNotFoundError,
    RateLimitError,
)
from asockslib.models import (
    CreatePortRequest,
    CreateTemplateRequest,
    PortFilterParams,
    UpdatePortRequest,
    UpdateTemplateRequest,
)

if TYPE_CHECKING:
    import pytest_httpx

API_KEY = "test-api-key-123"


CLIENT_MAX_RETRIES = 3


@pytest.fixture
def client(httpx_mock: pytest_httpx.HTTPXMock) -> ASocksClient:
    """Create an ASocksClient pointing at the mocked transport.

    Retries use zero back-off so retry-path tests stay fast.
    """
    return ASocksClient(
        api_key=API_KEY,
        base_url="https://api.asocks.com",
        max_retries=CLIENT_MAX_RETRIES,
        retry_backoff_base=0.0,
        retry_backoff_max=0.0,
    )


# -- balance ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_balance(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?apiKey=.*"),
        json={
            "success": True,
            "balance": 42.50,
            "balance_traffic": 0,
            "all_available_traffic": 0,
            "prepared_traffic_balance": 0,
            "balance_hold": 0,
        },
    )
    balance = await client.get_balance()
    assert balance.balance == 42.5


# -- directory -------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_countries(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/dir/countries\?.*"),
        json={
            "success": True,
            "countries": [
                {"id": 1, "name": "United States", "code": "US"},
                {"id": 2, "name": "Germany", "code": "DE"},
            ],
        },
    )
    items = await client.get_countries()
    assert len(items) == 2
    assert items[0].code == "US"
    assert items[0].name == "United States"
    assert items[1].code == "DE"


@pytest.mark.asyncio
async def test_get_states(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/dir/states\?.*"),
        json={"success": True, "states": [{"id": 10, "name": "California"}]},
    )
    items = await client.get_states(country_id=1)
    assert len(items) == 1
    assert items[0].name == "California"
    assert items[0].id == 10


@pytest.mark.asyncio
async def test_get_cities(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/dir/cities\?.*"),
        json={"success": True, "cities": [{"id": 100, "name": "Los Angeles"}]},
    )
    items = await client.get_cities(country_id=1, state_id=10)
    assert items[0].name == "Los Angeles"
    assert items[0].id == 100


@pytest.mark.asyncio
async def test_get_asns(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/dir/asns\?.*"),
        json={"success": True, "asns": {"data": [{"asn": 13335, "name": "Cloudflare"}]}},
    )
    data = await client.get_asns(country_id=1)
    assert len(data.items) == 1
    assert data.items[0].asn == 13335
    assert data.items[0].name == "Cloudflare"


# -- plan ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_plan_info(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/plan/info\?.*"),
        json={"success": True, "message": {"plan": "premium", "traffic_left": 50}},
    )
    data = await client.get_plan_info()
    assert data["message"]["plan"] == "premium"


# -- search proxies --------------------------------------------------------


@pytest.mark.asyncio
async def test_search_proxies_dict_response(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/search\?.*"),
        json={"0": "1.2.3.4:1000", "1": "5.6.7.8:2000", "success": True},
    )
    proxies = await client.search_proxies(country="US", limit=2)
    assert len(proxies) == 2
    assert "1.2.3.4:1000" in proxies


@pytest.mark.asyncio
async def test_search_proxies_list_response(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """Handle case where API returns a list instead of dict."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/search\?.*"),
        json=["1.2.3.4:1000", "5.6.7.8:2000"],
    )
    proxies = await client.search_proxies(country="US", limit=2)
    assert len(proxies) == 2


# -- list ports ------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_ports(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/ports\?.*"),
        json={
            "success": True,
            "message": [
                {
                    "id": 1,
                    "host": "h",
                    "port": 80,
                    "login": "",
                    "password": "",
                    "protocol": "socks5",
                    "country": "US",
                    "country_code": "US",
                    "city": "",
                    "state": "",
                    "status": 1,
                }
            ],
        },
    )
    resp = await client.list_ports()
    assert len(resp.items) == 1
    assert resp.items[0].country == "US"


# -- get port --------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_port(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/port-info\?.*id=42.*"),
        json={
            "success": True,
            "message": {
                "id": 42,
                "host": "1.2.3.4",
                "port": 8080,
                "login": "u",
                "password": "p",
                "protocol": "socks5",
                "country": "DE",
                "country_code": "DE",
                "city": "Berlin",
                "state": "",
                "status": 1,
            },
        },
    )
    port = await client.get_port(42)
    assert port.id == 42
    assert port.country == "DE"


# -- create ports ----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_ports(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/create-port\?.*"),
        json={
            "success": True,
            "data": [
                {
                    "id": 99,
                    "host": "p.asocks.com",
                    "port": 5000,
                    "login": "u",
                    "password": "p",
                    "protocol": "socks5",
                    "country": "US",
                    "country_code": "US",
                    "city": "",
                    "state": "",
                    "status": 1,
                }
            ],
        },
    )
    req = CreatePortRequest(country_code="US", count=1)
    ports = await client.create_ports(req)
    assert len(ports) == 1
    assert ports[0].id == 99


_CREATED_PORT = {
    "id": 99,
    "host": "p.asocks.com",
    "port": 5000,
    "login": "u",
    "password": "p",
    "protocol": "socks5",
    "country": "US",
    "country_code": "US",
    "city": "",
    "state": "",
    "status": 1,
}


@pytest.mark.asyncio
async def test_create_ports_refresh(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """refresh=True triggers a refresh_ip call for each created port."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/create-port\?.*"),
        json={"success": True, "data": [_CREATED_PORT]},
    )
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/refresh/99\?.*"),
        json={"success": True},
    )
    req = CreatePortRequest(country_code="US", count=1)
    ports = await client.create_ports(req, refresh=True)
    assert len(ports) == 1
    refresh_calls = [r for r in httpx_mock.get_requests() if "/v2/proxy/refresh/99" in str(r.url)]
    assert len(refresh_calls) == 1


@pytest.mark.asyncio
async def test_create_ports_refresh_failure_ignored(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """A failing refresh_ip must not break port creation."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/create-port\?.*"),
        json={"success": True, "data": [_CREATED_PORT]},
    )
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/refresh/99\?.*"),
        status_code=404,
        json={"message": "not found"},
        is_reusable=True,
    )
    req = CreatePortRequest(country_code="US", count=1)
    ports = await client.create_ports(req, refresh=True)
    assert len(ports) == 1


# -- delete port -----------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_port(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/delete-port\?.*"),
        json={"success": True},
    )
    ok = await client.delete_port(42)
    assert ok is True


# -- archive / unarchive ---------------------------------------------------


@pytest.mark.asyncio
async def test_archive_port(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/archive-port\?.*"),
        json={"success": True},
    )
    ok = await client.archive_port(42)
    assert ok is True


@pytest.mark.asyncio
async def test_unarchive_port(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/unarchive\?.*"),
        json={"success": True},
    )
    ok = await client.unarchive_port(42)
    assert ok is True


# -- refresh ip ------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_ip(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/refresh/42\?.*"),
        json={"success": True},
    )
    ok = await client.refresh_ip(42)
    assert ok is True


# -- change port name ------------------------------------------------------


@pytest.mark.asyncio
async def test_change_port_name(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/change-name\?.*"),
        json={"success": True},
    )
    ok = await client.change_port_name(42, "new-name")
    assert ok is True


# -- traffic ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_total_spent_traffic(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/total-spent-traffic\?.*"),
        json={"success": True, "total_spent_traffic": 12.5},
    )
    data = await client.get_total_spent_traffic()
    assert data["total_spent_traffic"] == 12.5


# -- templates -------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_templates(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy-template\?.*"),
        json={"success": True, "message": {"data": []}},
    )
    data = await client.list_templates()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_create_template(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy-template/create-template\?.*"),
        json={"success": True, "template": {"id": 1, "label": "test"}},
    )
    req = CreateTemplateRequest(label="test", template="{ip}:{port}")
    data = await client.create_template(req)
    assert data["success"] is True


@pytest.mark.asyncio
async def test_delete_template(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy-template/delete-template\?.*"),
        json={"success": True},
    )
    ok = await client.delete_template(1)
    assert ok is True


# -- error handling --------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_error(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?.*"),
        status_code=401,
        json={"message": "Unauthorized"},
    )
    with pytest.raises(AuthenticationError):
        await client.get_balance()


@pytest.mark.asyncio
async def test_not_found_error(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/port-info\?.*"),
        status_code=404,
        json={"message": "Not found"},
    )
    with pytest.raises(PortNotFoundError):
        await client.get_port(999)


@pytest.mark.asyncio
async def test_rate_limit_error(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    # 429 is retried up to max_retries; the final attempt raises RateLimitError.
    for _ in range(CLIENT_MAX_RETRIES):
        httpx_mock.add_response(
            url=re.compile(r".*/v2/user/balance\?.*"),
            status_code=429,
            json={"message": "Rate limit exceeded"},
        )
    with pytest.raises(RateLimitError):
        await client.get_balance()


@pytest.mark.asyncio
async def test_rate_limit_recovers(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """A 429 followed by a success is retried transparently."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?.*"),
        status_code=429,
        json={"message": "Rate limit exceeded"},
    )
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?.*"),
        json={"balance": 7.0, "balance_traffic": 0, "all_available_traffic": 0},
    )
    balance = await client.get_balance()
    assert balance.balance == 7.0


@pytest.mark.asyncio
async def test_generic_error(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    # GET 5xx is retried; the final attempt raises ASocksError.
    for _ in range(CLIENT_MAX_RETRIES):
        httpx_mock.add_response(
            url=re.compile(r".*/v2/user/balance\?.*"),
            status_code=500,
            json={"message": "Internal server error"},
        )
    with pytest.raises(ASocksError):
        await client.get_balance()


@pytest.mark.asyncio
async def test_server_error_retries_then_succeeds(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """A transient 503 on a GET is retried and then succeeds."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?.*"),
        status_code=503,
        json={"message": "temporarily unavailable"},
    )
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?.*"),
        json={"balance": 11.0, "balance_traffic": 0, "all_available_traffic": 0},
    )
    balance = await client.get_balance()
    assert balance.balance == 11.0


@pytest.mark.asyncio
async def test_post_not_retried_on_server_error(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """POST (create-port) must NOT be retried on 5xx — could double-create."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/create-port\?.*"),
        status_code=500,
        json={"message": "server error"},
    )
    req = CreatePortRequest(country_code="US", count=1)
    with pytest.raises(ASocksError):
        await client.create_ports(req)
    # Exactly one request was made (no retry).
    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.asyncio
async def test_network_error_wrapped(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """Transport errors are retried then wrapped in APIConnectionError."""
    for _ in range(CLIENT_MAX_RETRIES):
        httpx_mock.add_exception(
            httpx.ConnectError("connection refused"),
            url=re.compile(r".*/v2/user/balance\?.*"),
        )
    with pytest.raises(APIConnectionError):
        await client.get_balance()


@pytest.mark.asyncio
async def test_network_error_recovers(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """A single transport error on a GET is retried and then succeeds."""
    httpx_mock.add_exception(
        httpx.ConnectTimeout("timeout"),
        url=re.compile(r".*/v2/user/balance\?.*"),
    )
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?.*"),
        json={"balance": 5.0, "balance_traffic": 0, "all_available_traffic": 0},
    )
    balance = await client.get_balance()
    assert balance.balance == 5.0


@pytest.mark.asyncio
async def test_missing_api_key_raises() -> None:
    """Constructing a client without an API key fails fast."""
    with pytest.raises(ValueError, match="api_key"):
        ASocksClient(api_key="")


# -- additional error codes ------------------------------------------------


@pytest.mark.asyncio
async def test_insufficient_balance_error(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/create-port\?.*"),
        status_code=402,
        json={"message": "Insufficient balance"},
    )
    req = CreatePortRequest(country_code="US", count=1)
    with pytest.raises(InsufficientBalanceError):
        await client.create_ports(req)


@pytest.mark.asyncio
async def test_forbidden_error(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?.*"),
        status_code=403,
        json={"message": "Forbidden"},
    )
    with pytest.raises(AuthenticationError):
        await client.get_balance()


# -- change_credentials ----------------------------------------------------


@pytest.mark.asyncio
async def test_change_credentials(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/change-credentials\?.*"),
        json={"success": True},
    )
    result = await client.change_credentials()
    assert result is True


@pytest.mark.asyncio
async def test_change_credentials_failure(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/change-credentials\?.*"),
        json={"success": False},
    )
    result = await client.change_credentials()
    assert result is False


# -- update_port -----------------------------------------------------------


@pytest.mark.asyncio
async def test_update_port(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/update-port/42\?.*"),
        json={"success": True, "message": {"id": 42}},
    )
    req = UpdatePortRequest(
        name="new-name",
        geo_country_ids=[1],
        connection_type="keep-connection",
        proxy_types=["residential"],
    )
    result = await client.update_port(42, req)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_update_port_rejects_partial_body(client: ASocksClient) -> None:
    """The live API requires geo/connection/proxy-type fields — the client
    must fail fast with a clear error instead of a server-side 422."""
    with pytest.raises(ValueError, match="geo_country_ids, connection_type"):
        await client.update_port(42, UpdatePortRequest(name="new-name"))


# -- update_port_credentials -----------------------------------------------


@pytest.mark.asyncio
async def test_update_port_credentials(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/42/update-credentials\?.*"),
        json={"success": True},
    )
    result = await client.update_port_credentials(42, "new-password")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_update_port_credentials_not_found_hint(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """A 404 from update-credentials is re-raised with a workaround hint."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/42/update-credentials\?.*"),
        status_code=404,
        json={"message": "No query results for model UserPort 42"},
    )
    with pytest.raises(PortNotFoundError, match="change_credentials"):
        await client.update_port_credentials(42, "new-password")


# -- update_template -------------------------------------------------------


@pytest.mark.asyncio
async def test_update_template(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy-template/update-template\?.*"),
        json={"success": True, "message": {"id": 7}},
    )
    req = UpdateTemplateRequest(label="updated-tpl")
    result = await client.update_template(7, req)
    assert result["success"] is True


# -- context manager -------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/user/balance\?.*"),
        json={"balance": 99.0, "balance_traffic": 0.0, "all_available_traffic": 0.0},
    )
    async with ASocksClient(api_key=API_KEY) as client:
        balance = await client.get_balance()
        assert balance.balance == 99.0


# -- close -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_close(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    client = ASocksClient(api_key=API_KEY)
    await client.close()
    # Should not raise even if called multiple times
    await client.close()


# -- parameter variants ----------------------------------------------------


@pytest.mark.asyncio
async def test_get_states_no_country(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """get_states without country_id returns all states."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/dir/states\?.*"),
        json={"success": True, "states": [{"id": 1, "name": "All"}]},
    )
    items = await client.get_states()
    assert len(items) == 1
    assert items[0].name == "All"


@pytest.mark.asyncio
async def test_get_cities_country_only(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """get_cities with country_id only, no state_id."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/dir/cities\?.*"),
        json={"success": True, "cities": [{"id": 50, "name": "City"}]},
    )
    items = await client.get_cities(country_id=1)
    assert len(items) == 1
    assert items[0].name == "City"


@pytest.mark.asyncio
async def test_get_asns_all_params(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """get_asns with all parameter combinations."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/dir/asns\?.*"),
        json={"success": True, "asns": []},
    )
    from asockslib.models import ASNListResponse

    data = await client.get_asns(country_id=1, state_id=10, city_id=100, page=2)
    assert isinstance(data, ASNListResponse)


@pytest.mark.asyncio
async def test_get_asns_no_params(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    """get_asns without any params."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/dir/asns\?.*"),
        json={"success": True, "asns": {"data": []}},
    )
    from asockslib.models import ASNListResponse

    data = await client.get_asns()
    assert isinstance(data, ASNListResponse)
    assert data.items == []


@pytest.mark.asyncio
async def test_get_plan_info_with_show_proxies(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """get_plan_info with show_proxies param."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/plan/info\?.*"),
        json={"success": True, "message": {"plan": "basic"}},
    )
    data = await client.get_plan_info(show_proxies="active")
    assert data["message"]["plan"] == "basic"


@pytest.mark.asyncio
async def test_search_proxies_with_types(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """search_proxies with types filter."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/search\?.*"),
        json={"0": "1.2.3.4:80", "success": True},
    )
    proxies = await client.search_proxies(country="US", limit=1, types=["socks5", "http"])
    assert len(proxies) == 1


@pytest.mark.asyncio
async def test_search_proxies_empty(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """search_proxies with no results."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/search\?.*"),
        json={"success": True},
    )
    proxies = await client.search_proxies()
    assert proxies == []


@pytest.mark.asyncio
async def test_list_ports_with_filters(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """list_ports with PortFilterParams."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/ports\?.*"),
        json={"success": True, "message": []},
    )
    filters = PortFilterParams(countryName="US", status=1, page=2, per_page=10)
    resp = await client.list_ports(filters)
    assert resp.items == []


@pytest.mark.asyncio
async def test_list_ports_no_filters(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """list_ports without any filters."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/ports\?.*"),
        json={"success": True, "message": []},
    )
    resp = await client.list_ports()
    assert resp.items == []


@pytest.mark.asyncio
async def test_create_ports_invalid_item_skipped(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """create_ports skips items that fail Pydantic validation."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/create-port\?.*"),
        json={
            "success": True,
            "data": [
                {"bad": "data"},  # invalid — will be skipped
                {
                    "id": 100,
                    "host": "h",
                    "port": 80,
                    "login": "",
                    "password": "",
                    "protocol": "socks5",
                    "country": "US",
                    "country_code": "US",
                    "city": "",
                    "state": "",
                    "status": 1,
                },
            ],
        },
    )
    req = CreatePortRequest(country_code="US", count=2)
    ports = await client.create_ports(req)
    assert len(ports) == 1
    assert ports[0].id == 100


@pytest.mark.asyncio
async def test_create_ports_non_list_data(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """create_ports when API returns a single dict instead of list."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/create-port\?.*"),
        json={
            "success": True,
            "data": {
                "id": 200,
                "host": "h",
                "port": 80,
                "login": "",
                "password": "",
                "protocol": "socks5",
                "country": "US",
                "country_code": "US",
                "city": "",
                "state": "",
                "status": 1,
            },
        },
    )
    req = CreatePortRequest(country_code="US", count=1)
    ports = await client.create_ports(req)
    assert len(ports) == 1
    assert ports[0].id == 200


@pytest.mark.asyncio
async def test_handle_error_non_json_body(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """_handle_error with non-JSON response body (502 retried on GET)."""
    for _ in range(CLIENT_MAX_RETRIES):
        httpx_mock.add_response(
            url=re.compile(r".*/v2/user/balance\?.*"),
            status_code=502,
            text="Bad Gateway",
        )
    with pytest.raises(ASocksError, match="Bad Gateway"):
        await client.get_balance()


@pytest.mark.asyncio
async def test_delete_port_failure(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    """delete_port returns False when success=False."""
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/delete-port\?.*"),
        json={"success": False},
    )
    ok = await client.delete_port(42)
    assert ok is False


@pytest.mark.asyncio
async def test_archive_port_failure(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/archive-port\?.*"),
        json={"success": False},
    )
    ok = await client.archive_port(42)
    assert ok is False


@pytest.mark.asyncio
async def test_unarchive_port_failure(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/unarchive\?.*"),
        json={"success": False},
    )
    ok = await client.unarchive_port(42)
    assert ok is False


@pytest.mark.asyncio
async def test_refresh_ip_failure(httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/refresh/42\?.*"),
        json={"success": False},
    )
    ok = await client.refresh_ip(42)
    assert ok is False


@pytest.mark.asyncio
async def test_change_port_name_failure(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy/change-name\?.*"),
        json={"success": False},
    )
    ok = await client.change_port_name(42, "x")
    assert ok is False


@pytest.mark.asyncio
async def test_delete_template_failure(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy-template/delete-template\?.*"),
        json={"success": False},
    )
    ok = await client.delete_template(1)
    assert ok is False


@pytest.mark.asyncio
async def test_list_templates_with_page(
    httpx_mock: pytest_httpx.HTTPXMock, client: ASocksClient
) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*/v2/proxy-template\?.*"),
        json={"success": True, "message": {"data": []}},
    )
    data = await client.list_templates(page=3)
    assert data["success"] is True
