"""Shared test fixtures."""

from __future__ import annotations

import pytest

from asockslib.models import PortInfo


@pytest.fixture
def sample_port_data() -> dict[str, object]:
    """Raw port data as returned by the ASocks v2 API."""
    return {
        "id": 1001,
        "host": "proxy.asocks.com",
        "port": 10001,
        "login": "user1",
        "password": "pass1",
        "protocol": "socks5",
        "proxy_type": "residential",
        "country": "US",
        "country_code": "US",
        "city": "New York",
        "state": "",
        "status": 1,
        "name": "my-port",
        "asn": None,
        "expires_at": "2026-12-31T23:59:59Z",
    }


@pytest.fixture
def sample_port(sample_port_data: dict[str, object]) -> PortInfo:
    """A validated PortInfo instance."""
    return PortInfo.model_validate(sample_port_data)
