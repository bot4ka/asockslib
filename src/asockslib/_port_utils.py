"""Shared port management mixin for SmartProxy and ProxyPool.

Extracts the duplicated ``_fetch_matching_ports`` and ``_create_ports``
methods into a reusable mixin, eliminating code duplication.

Both :class:`SmartProxy` and :class:`ProxyPool` store identical sets of
proxy-creation parameters and perform the same operations — this mixin
encapsulates that shared behaviour.
"""

# This mixin's entire purpose is to read the host class's private
# (`_`-prefixed) configuration attributes — that's package-internal sharing
# by design, not an encapsulation leak, so reportPrivateUsage is silenced
# for this file only.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from asockslib.models import (
    CreatePortRequest,
    PortFilterParams,
    PortInfo,
    PortStatus,
)

if TYPE_CHECKING:
    from asockslib.client import ASocksClient

logger = logging.getLogger("asockslib")


@runtime_checkable
class _HasClient(Protocol):
    """Protocol for classes that hold an ASocksClient and proxy params."""

    _client: ASocksClient
    _country_code: str
    _city: str
    _state: str
    _type_id: int
    _proxy_type_id: int
    _server_port_type_id: int
    _ttl: int
    _traffic_limit: int


def _geo_matches(*, city: str, state: str, port: PortInfo) -> bool:
    """Return ``True`` if *port* is consistent with the requested geo.

    Conservative: a port is rejected only when the requested city/state is
    set *and* the port reports a different (non-empty) value. Ports whose
    metadata is missing are kept — the server-side filter is trusted for
    those. This guarantees geo-targeting without discarding otherwise-valid
    ports that simply lack city/state metadata.
    """

    def _mismatch(requested: str, actual: str) -> bool:
        if not (requested and actual):
            return False
        return requested.strip().lower() != actual.strip().lower()

    return not (_mismatch(city, port.city) or _mismatch(state, port.state))


class PortManagerMixin:
    """Mixin providing shared port fetch/create operations.

    Requires the consuming class to define:
        - ``_client``: :class:`ASocksClient` instance
        - ``_country_code``, ``_city``, ``_state``: geo filters
        - ``_type_id``, ``_proxy_type_id``, ``_server_port_type_id``: type IDs
        - ``_ttl``, ``_traffic_limit``: port parameters
    """

    async def _fetch_matching_ports(  # type: ignore[misc]
        self: _HasClient,
        limit: int | None = None,
    ) -> list[PortInfo]:
        """Load existing active ports matching the configured criteria.

        Pages through ``GET /v2/proxy/ports`` (200 per page) until *limit*
        matching ports are collected or the API runs out of pages, then
        applies a client-side geo guard. Passing the full country/state/city
        filter server-side keeps geo-targeting consistent; paginating fixes
        the previous behaviour of only ever seeing the first page.

        Args:
            limit: Stop once this many matching ports are collected
                (``None`` = collect every matching port).
        """
        per_page = 200
        collected: list[PortInfo] = []
        page = 1
        while True:
            filters = PortFilterParams(
                status=PortStatus.ACTIVE,
                countryName=self._country_code or None,
                stateName=self._state or None,
                cityName=self._city or None,
                page=page,
                per_page=per_page,
            )
            response = await self._client.list_ports(filters)
            page_items = list(response.items)
            collected.extend(
                p for p in page_items if _geo_matches(city=self._city, state=self._state, port=p)
            )

            if limit is not None and len(collected) >= limit:
                return collected[:limit]
            # Last page reached when the API returns fewer than a full page.
            if len(page_items) < per_page:
                return collected
            page += 1

    async def _create_ports(self: _HasClient, quantity: int) -> list[PortInfo]:  # type: ignore[misc]
        """Create new ports with the configured parameters."""
        request = CreatePortRequest(
            country_code=self._country_code,
            city=self._city,
            state=self._state,
            count=quantity,
            type_id=self._type_id,
            proxy_type_id=self._proxy_type_id,
            server_port_type_id=self._server_port_type_id,
            ttl=self._ttl,
            traffic_limit=self._traffic_limit,
        )
        return await self._client.create_ports(request)
