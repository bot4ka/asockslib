"""Pydantic models for ASocks API v2 requests and responses.

Covers all 25 endpoints documented at https://docs.asocks.com/en/.

Modules:
    - :mod:`.enums` — port statuses and connection/proxy type identifiers.
    - :mod:`.directory` — countries, states, cities, ASN entries.
    - :mod:`.port` — proxy port models and list responses.
    - :mod:`.requests` — bodies and query parameters for mutations.
    - :mod:`.responses` — typed wrappers for API responses.

Every model uses ``extra="allow"`` so that new fields added by the API
are accepted without breaking existing code.
"""

from __future__ import annotations

from asockslib.models.directory import (
    ASNInfo,
    ASNListResponse,
    CityInfo,
    CountryInfo,
    StateInfo,
)
from asockslib.models.enums import (
    AuthType,
    ConnectionType,
    ConnectionTypeId,
    PortStatus,
    ProxyType,
    ProxyTypeId,
    ServerPortType,
)
from asockslib.models.port import (
    PortInfo,
    PortListResponse,
)
from asockslib.models.requests import (
    CreatePortRequest,
    CreateTemplateRequest,
    PortFilterParams,
    UpdatePortRequest,
    UpdateTemplateRequest,
    WhitelistAddRequest,
)
from asockslib.models.responses import (
    BalanceResponse,
)

__all__ = [
    "ASNInfo",
    "ASNListResponse",
    "AuthType",
    "BalanceResponse",
    "CityInfo",
    "ConnectionType",
    "ConnectionTypeId",
    "CountryInfo",
    "CreatePortRequest",
    "CreateTemplateRequest",
    "PortFilterParams",
    "PortInfo",
    "PortListResponse",
    "PortStatus",
    "ProxyType",
    "ProxyTypeId",
    "ServerPortType",
    "StateInfo",
    "UpdatePortRequest",
    "UpdateTemplateRequest",
    "WhitelistAddRequest",
]
