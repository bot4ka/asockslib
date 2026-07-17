"""Data types for the geo-picker module.

Frozen dataclasses representing user selections, plus static
choice data for connection types, proxy types, and server port types.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Picked result types ───────────────────────────────────────────────────── #


@dataclass(frozen=True, slots=True)
class PickedCountry:
    """Selected country."""

    code: str
    name: str
    id: int


@dataclass(frozen=True, slots=True)
class PickedState:
    """Selected state/region."""

    name: str
    id: int


@dataclass(frozen=True, slots=True)
class PickedCity:
    """Selected city."""

    name: str
    id: int


@dataclass(frozen=True, slots=True)
class PickedASN:
    """Selected ASN."""

    number: int
    name: str


@dataclass(frozen=True, slots=True)
class PickedConnectionType:
    """Selected connection type."""

    id: int
    label: str


@dataclass(frozen=True, slots=True)
class PickedProxyType:
    """Selected proxy type."""

    id: int
    label: str


@dataclass(frozen=True, slots=True)
class PickedServerPortType:
    """Selected server port type."""

    id: int
    label: str


# ── Static choice data ───────────────────────────────────────────────────── #

CONNECTION_TYPES: list[tuple[int, str]] = [
    (1, "Keep Proxy — fixed proxy, highest trust"),
    (2, "Keep Connection — fixed connection, high trust"),
    (3, "Rotate Connection — rotation on each request"),
]

PROXY_TYPES: list[tuple[int, str]] = [
    (1, "Residential — home IP addresses"),
    (2, "All — all proxy types"),
    (3, "Mobile — mobile operator IPs"),
    (4, "Corporate — corporate network IPs"),
]

SERVER_PORT_TYPES: list[tuple[int, str]] = [
    (0, "Shared — shared port (free)"),
    (1, "Dedicated — dedicated port (paid, traffic limit)"),
]
