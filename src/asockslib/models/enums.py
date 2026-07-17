"""Enum types for the ASocks API v2.

Centralizes all enumeration types used across the library:
port statuses, proxy types, connection types, and identifiers.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class PortStatus(IntEnum):
    """Port status codes used by the ASocks API."""

    ACTIVE = 1
    INACTIVE = 0
    EXPIRED = 2


class ProxyType(StrEnum):
    """Proxy category."""

    RESIDENTIAL = "residential"
    MOBILE = "mobile"
    CORPORATE = "corporate"


class ConnectionType(StrEnum):
    """Connection mode for a proxy port."""

    KEEP_PROXY = "keep-proxy"
    KEEP_CONNECTION = "keep-connection"
    ROTATE_CONNECTION = "rotate-connection"
    KEEP_CONNECTION_LOW_TRUST = "keep-connection-low-trust"


class AuthType(StrEnum):
    """Authentication method."""

    LOGIN_PASSWORD = "login-and-password"
    IP_WHITELIST = "ip-whitelist"


class ProxyTypeId(IntEnum):
    """Numeric proxy-type identifiers for API requests."""

    RESIDENTIAL = 1
    ALL = 2
    MOBILE = 3
    CORPORATE = 4


class ConnectionTypeId(IntEnum):
    """Numeric connection-type identifiers for API requests."""

    KEEP_PROXY = 1
    KEEP_CONNECTION = 2
    ROTATE_CONNECTION = 3


class ServerPortType(IntEnum):
    """Server port type."""

    SHARED = 0
    DEDICATED = 1
