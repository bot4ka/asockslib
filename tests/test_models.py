"""Tests for Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from asockslib.models import (
    ASNInfo,
    ASNListResponse,
    AuthType,
    BalanceResponse,
    CityInfo,
    ConnectionType,
    ConnectionTypeId,
    CountryInfo,
    CreatePortRequest,
    CreateTemplateRequest,
    PortFilterParams,
    PortInfo,
    PortListResponse,
    PortStatus,
    ProxyType,
    ProxyTypeId,
    ServerPortType,
    StateInfo,
    UpdatePortRequest,
    UpdateTemplateRequest,
)


class TestPortInfo:
    """Tests for the PortInfo model."""

    def test_parse_valid_data(self, sample_port_data: dict[str, object]) -> None:
        port = PortInfo.model_validate(sample_port_data)
        assert port.id == 1001
        assert port.host == "proxy.asocks.com"
        assert port.port == 10001
        assert port.protocol == "socks5"
        assert port.country == "US"

    def test_proxy_url_with_auth(self, sample_port: PortInfo) -> None:
        assert sample_port.proxy_url == "socks5://user1:pass1@proxy.asocks.com:10001"

    def test_proxy_url_without_auth(self) -> None:
        port = PortInfo(id=1, host="1.2.3.4", port=8080)
        assert port.proxy_url == "socks5://1.2.3.4:8080"

    def test_defaults(self) -> None:
        port = PortInfo(id=1, host="h", port=80)
        assert port.protocol == "socks5"
        assert port.status == 1
        assert port.login == ""
        assert port.password == ""

    def test_is_active(self) -> None:
        port = PortInfo(id=1, host="h", port=80, status=PortStatus.ACTIVE)
        assert port.is_active is True
        port2 = PortInfo(id=2, host="h", port=80, status=PortStatus.EXPIRED)
        assert port2.is_active is False

    def test_extra_fields_allowed(self) -> None:
        # pyright doesn't model pydantic's extra="allow" kwarg acceptance.
        port = PortInfo(
            id=1,
            host="h",
            port=80,
            some_new_field="value",  # pyright: ignore[reportCallIssue]
        )
        assert port.id == 1


class TestPortListResponse:
    """Tests for PortListResponse."""

    def test_empty(self) -> None:
        resp = PortListResponse(success=True, message=[])
        assert resp.items == []

    def test_with_items(self, sample_port_data: dict[str, object]) -> None:
        port = PortInfo.model_validate(sample_port_data)
        resp = PortListResponse(success=True, message=[port])
        assert len(resp.items) == 1
        assert resp.items[0].id == 1001

    def test_paginated_dict(self) -> None:
        resp = PortListResponse(
            success=True,
            message={
                "data": [{"id": 1, "host": "h", "port": 80}],
                "total": 100,
                "current_page": 1,
            },
        )
        assert len(resp.items) == 1
        assert resp.total == 100


class TestBalanceResponse:
    """Tests for BalanceResponse."""

    def test_float_values(self) -> None:
        b = BalanceResponse(
            success=True,
            balance=42.5,
            balance_traffic=10.0,
            all_available_traffic=50.0,
            prepared_traffic_balance=0.0,
            balance_hold=0.0,
        )
        assert b.balance == 42.5

    def test_defaults(self) -> None:
        b = BalanceResponse()
        assert b.balance == 0
        assert b.balance_traffic == 0


class TestCreatePortRequest:
    """Tests for CreatePortRequest."""

    def test_defaults(self) -> None:
        req = CreatePortRequest()
        assert req.count == 1
        assert req.type_id == 1
        assert req.proxy_type_id == 1

    def test_count_validation(self) -> None:
        with pytest.raises(ValidationError):
            CreatePortRequest(count=0)

        with pytest.raises(ValidationError):
            CreatePortRequest(count=1001)

    def test_dump_excludes_empty(self) -> None:
        req = CreatePortRequest(country_code="US", count=5)
        body = {k: v for k, v in req.model_dump().items() if v not in (None, "")}
        assert "country_code" in body
        assert body["count"] == 5


class TestPortFilterParams:
    """Tests for PortFilterParams."""

    def test_defaults(self) -> None:
        p = PortFilterParams()
        assert p.page == 1
        assert p.per_page == 50

    def test_dump_excludes_none(self) -> None:
        p = PortFilterParams(countryName="DE")
        d = {k: v for k, v in p.model_dump().items() if v is not None}
        assert "countryName" in d
        assert "status" not in d


class TestUpdatePortRequest:
    """Tests for UpdatePortRequest."""

    def test_all_none_by_default(self) -> None:
        req = UpdatePortRequest()
        d = {k: v for k, v in req.model_dump().items() if v is not None}
        assert d == {}

    def test_partial_update(self) -> None:
        req = UpdatePortRequest(name="new-name", ttl=7)
        d = {k: v for k, v in req.model_dump().items() if v is not None}
        assert d == {"name": "new-name", "ttl": 7}


class TestCreateTemplateRequest:
    """Tests for CreateTemplateRequest."""

    def test_required_fields(self) -> None:
        req = CreateTemplateRequest(label="my-tpl", template="{ip}:{port}")
        assert req.label == "my-tpl"
        assert req.template == "{ip}:{port}"

    def test_missing_required(self) -> None:
        with pytest.raises(ValidationError):
            CreateTemplateRequest()  # type: ignore[call-arg]


class TestUpdateTemplateRequest:
    """Tests for UpdateTemplateRequest."""

    def test_partial(self) -> None:
        req = UpdateTemplateRequest(label="updated")
        assert req.label == "updated"
        assert req.template is None


# --------------------------------------------------------------------------- #
#  PortStatus enum
# --------------------------------------------------------------------------- #


class TestPortStatus:
    """Tests for PortStatus IntEnum."""

    def test_active_value(self) -> None:
        assert PortStatus.ACTIVE == 1

    def test_inactive_value(self) -> None:
        assert PortStatus.INACTIVE == 0

    def test_expired_value(self) -> None:
        assert PortStatus.EXPIRED == 2

    def test_is_int(self) -> None:
        assert isinstance(PortStatus.ACTIVE, int)

    def test_comparison(self) -> None:
        assert PortStatus.ACTIVE != PortStatus.EXPIRED


# --------------------------------------------------------------------------- #
#  PortInfo edge cases
# --------------------------------------------------------------------------- #


class TestPortInfoEdgeCases:
    """Additional PortInfo edge cases."""

    def test_is_active_inactive(self) -> None:
        port = PortInfo(id=1, host="h", port=80, status=PortStatus.INACTIVE)
        assert port.is_active is False

    def test_proxy_url_http_protocol(self) -> None:
        port = PortInfo(id=1, host="h", port=80, login="u", password="p", protocol="http")
        assert port.proxy_url == "http://u:p@h:80"

    def test_proxy_url_empty_password(self) -> None:
        port = PortInfo(id=1, host="h", port=80, login="u", password="")
        # login is truthy so auth is included even with empty password
        assert port.proxy_url == "socks5://u:@h:80"

    def test_proxy_url_no_login_no_password(self) -> None:
        port = PortInfo(id=1, host="h", port=80, login="", password="")
        assert port.proxy_url == "socks5://h:80"

    def test_model_dump_preserves_extra(self) -> None:
        # pyright doesn't model pydantic's extra="allow" kwarg acceptance.
        port = PortInfo(
            id=1,
            host="h",
            port=80,
            some_custom="val",  # pyright: ignore[reportCallIssue]
        )
        dumped = port.model_dump()
        assert dumped["some_custom"] == "val"


# --------------------------------------------------------------------------- #
#  PortInfo.format_with_template
# --------------------------------------------------------------------------- #


class TestPortInfoFormatWithTemplate:
    """Tests for PortInfo.format_with_template()."""

    def _port(self) -> PortInfo:
        return PortInfo(
            id=42,
            host="proxy.asocks.com",
            port=10001,
            login="user1",
            password="pass1",
            protocol="socks5",
            name="my-port",
            external_ip="203.0.113.42",
        )

    def test_standard_url_template(self) -> None:
        port = self._port()
        result = port.format_with_template("{protocol}://{login}:{password}@{ip}:{port}")
        assert result == "socks5://user1:pass1@proxy.asocks.com:10001"

    def test_ip_port_login_password(self) -> None:
        port = self._port()
        result = port.format_with_template("{ip}:{port}:{login}:{password}")
        assert result == "proxy.asocks.com:10001:user1:pass1"

    def test_http_url_template(self) -> None:
        port = self._port()
        result = port.format_with_template("http://{login}:{password}@{ip}:{port}")
        assert result == "http://user1:pass1@proxy.asocks.com:10001"

    def test_with_name(self) -> None:
        port = self._port()
        result = port.format_with_template("{ip}:{port}:{login}:{password}:{name}")
        assert result == "proxy.asocks.com:10001:user1:pass1:my-port"

    def test_with_refresh_link(self) -> None:
        port = self._port()
        result = port.format_with_template(
            "{protocol}://{login}:{password}@{ip}:{port}[{refresh_link}]"
        )
        assert (
            result
            == "socks5://user1:pass1@proxy.asocks.com:10001[https://api.asocks.com/v2/proxy/refresh-ip/42]"
        )

    def test_with_id(self) -> None:
        port = self._port()
        result = port.format_with_template("{id}:{ip}:{port}")
        assert result == "42:proxy.asocks.com:10001"

    def test_with_external_ip(self) -> None:
        port = self._port()
        result = port.format_with_template("{external_ip} -> {ip}:{port}")
        assert result == "203.0.113.42 -> proxy.asocks.com:10001"

    def test_curl_template(self) -> None:
        port = self._port()
        result = port.format_with_template(
            "curl -x http://{login}:{password}@{ip}:{port} https://i.pn"
        )
        assert result == "curl -x http://user1:pass1@proxy.asocks.com:10001 https://i.pn"

    def test_pipe_separated(self) -> None:
        port = self._port()
        result = port.format_with_template("HTTP|{ip}|{port}|{login}|{password}")
        assert result == "HTTP|proxy.asocks.com|10001|user1|pass1"

    def test_default_protocol_when_empty(self) -> None:
        port = PortInfo(id=1, host="h", port=80, login="u", password="p", protocol="")
        result = port.format_with_template("{protocol}://{login}:{password}@{ip}:{port}")
        assert result == "socks5://u:p@h:80"


# --------------------------------------------------------------------------- #
#  PortListResponse edge cases
# --------------------------------------------------------------------------- #


class TestPortListResponseEdgeCases:
    """Additional PortListResponse edge cases."""

    def test_total_from_list_message(self) -> None:
        """total = len(items) when message is a plain list."""
        resp = PortListResponse(
            success=True,
            message=[
                PortInfo(id=1, host="h", port=80),
                PortInfo(id=2, host="h", port=81),
            ],
        )
        assert resp.total == 2

    def test_total_from_paginated_dict_total_field(self) -> None:
        """total comes from dict['total'] when message is paginated dict."""
        resp = PortListResponse(
            success=True,
            message={"data": [], "total": 500, "current_page": 1},
        )
        assert resp.total == 500

    def test_items_from_empty_paginated_dict(self) -> None:
        resp = PortListResponse(
            success=True,
            message={"data": [], "current_page": 1},
        )
        assert resp.items == []
        assert resp.total == 0


# --------------------------------------------------------------------------- #
#  BalanceResponse edge cases
# --------------------------------------------------------------------------- #


class TestBalanceResponseEdgeCases:
    """Additional BalanceResponse edge cases."""

    def test_all_fields(self) -> None:
        b = BalanceResponse(
            success=True,
            balance=100.5,
            balance_traffic=20.0,
            all_available_traffic=30.0,
            prepared_traffic_balance=5.0,
            balance_hold=2.5,
        )
        assert b.prepared_traffic_balance == 5.0
        assert b.balance_hold == 2.5

    def test_from_dict(self) -> None:
        data = {"balance": 42.0, "balance_traffic": 1.0, "all_available_traffic": 2.0}
        b = BalanceResponse.model_validate(data)
        assert b.balance == 42.0


# --------------------------------------------------------------------------- #
#  Directory Models
# --------------------------------------------------------------------------- #


class TestCountryInfo:
    """Tests for CountryInfo model."""

    def test_parse(self) -> None:
        c = CountryInfo(id=1, name="United States", code="US")
        assert c.id == 1
        assert c.name == "United States"
        assert c.code == "US"

    def test_short_name_alias_from_dict(self) -> None:
        """API may return 'short_name' – alias must still work."""
        data = {"id": 2, "name": "Germany", "short_name": "DE"}
        c = CountryInfo.model_validate(data)
        assert c.code == "DE"

    def test_code_from_dict(self) -> None:
        """Real API returns 'code' key."""
        data = {"id": 3, "name": "France", "code": "FR"}
        c = CountryInfo.model_validate(data)
        assert c.code == "FR"

    def test_short_name_property(self) -> None:
        """Backward compat: .short_name returns .code."""
        c = CountryInfo(id=1, name="United States", code="US")
        assert c.short_name == "US"

    def test_defaults(self) -> None:
        c = CountryInfo(id=1)
        assert c.name == ""
        assert c.code == ""

    def test_extra_fields_allowed(self) -> None:
        # pyright doesn't model pydantic's extra="allow" kwarg acceptance.
        c = CountryInfo(
            id=1,
            name="X",
            code="X",
            extra_field="val",  # pyright: ignore[reportCallIssue]
        )
        assert c.id == 1


class TestStateInfo:
    """Tests for StateInfo model."""

    def test_parse(self) -> None:
        s = StateInfo(id=10, name="California", dir_country_id=1)
        assert s.id == 10
        assert s.name == "California"
        assert s.dir_country_id == 1

    def test_defaults(self) -> None:
        s = StateInfo(id=1)
        assert s.name == ""
        assert s.dir_country_id is None

    def test_extra_fields_allowed(self) -> None:
        # pyright doesn't model pydantic's extra="allow" kwarg acceptance.
        s = StateInfo(id=1, name="X", unknown_field=42)  # pyright: ignore[reportCallIssue]
        assert s.id == 1


class TestCityInfo:
    """Tests for CityInfo model."""

    def test_parse(self) -> None:
        c = CityInfo(id=100, name="Los Angeles", dir_country_id=1, dir_state_id=10)
        assert c.id == 100
        assert c.name == "Los Angeles"
        assert c.dir_country_id == 1
        assert c.dir_state_id == 10

    def test_defaults(self) -> None:
        c = CityInfo(id=1)
        assert c.name == ""
        assert c.dir_country_id is None
        assert c.dir_state_id is None


class TestASNInfo:
    """Tests for ASNInfo model."""

    def test_parse(self) -> None:
        a = ASNInfo(asn=13335, name="Cloudflare, Inc.")
        assert a.asn == 13335
        assert a.name == "Cloudflare, Inc."

    def test_defaults(self) -> None:
        a = ASNInfo(asn=1)
        assert a.name == ""


class TestASNListResponse:
    """Tests for ASNListResponse model."""

    def test_empty(self) -> None:
        resp = ASNListResponse()
        assert resp.items == []
        assert resp.total == 0

    def test_with_data(self) -> None:
        resp = ASNListResponse(
            data=[ASNInfo(asn=13335, name="Cloudflare")],
            current_page=1,
            per_page=1000,
            total=1,
            last_page=1,
        )
        assert len(resp.items) == 1
        assert resp.items[0].asn == 13335
        assert resp.total == 1

    def test_from_dict(self) -> None:
        data = {
            "data": [{"asn": 7922, "name": "Comcast"}],
            "current_page": 2,
            "per_page": 1000,
            "total": 5000,
            "last_page": 5,
        }
        resp = ASNListResponse.model_validate(data)
        assert resp.current_page == 2
        assert resp.last_page == 5
        assert len(resp.items) == 1


# --------------------------------------------------------------------------- #
#  Enums (additional)
# --------------------------------------------------------------------------- #


class TestProxyType:
    """Tests for ProxyType enum."""

    def test_values(self) -> None:
        assert ProxyType.RESIDENTIAL == "residential"
        assert ProxyType.MOBILE == "mobile"
        assert ProxyType.CORPORATE == "corporate"


class TestConnectionType:
    """Tests for ConnectionType enum."""

    def test_values(self) -> None:
        assert ConnectionType.KEEP_PROXY == "keep-proxy"
        assert ConnectionType.KEEP_CONNECTION == "keep-connection"
        assert ConnectionType.ROTATE_CONNECTION == "rotate-connection"
        assert ConnectionType.KEEP_CONNECTION_LOW_TRUST == "keep-connection-low-trust"


class TestAuthType:
    """Tests for AuthType enum."""

    def test_values(self) -> None:
        assert AuthType.LOGIN_PASSWORD == "login-and-password"
        assert AuthType.IP_WHITELIST == "ip-whitelist"


class TestProxyTypeId:
    """Tests for ProxyTypeId enum."""

    def test_values(self) -> None:
        assert ProxyTypeId.RESIDENTIAL == 1
        assert ProxyTypeId.ALL == 2
        assert ProxyTypeId.MOBILE == 3
        assert ProxyTypeId.CORPORATE == 4


class TestConnectionTypeId:
    """Tests for ConnectionTypeId enum."""

    def test_values(self) -> None:
        assert ConnectionTypeId.KEEP_PROXY == 1
        assert ConnectionTypeId.KEEP_CONNECTION == 2
        assert ConnectionTypeId.ROTATE_CONNECTION == 3


class TestServerPortType:
    """Tests for ServerPortType enum."""

    def test_values(self) -> None:
        assert ServerPortType.SHARED == 0
        assert ServerPortType.DEDICATED == 1
