"""Request models for the ASocks API v2.

Bodies and query parameters for mutations: port creation, updates,
and template management.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreatePortRequest(BaseModel):
    """Body for ``POST /v2/proxy/create-port``.

    Example::

        req = CreatePortRequest(country_code="US", count=5, ttl=7)
    """

    country_code: str = Field(default="", description="ISO country code (e.g. US)")
    state: str = Field(default="", description="State name")
    city: str = Field(default="", description="City name")
    asn: int | None = Field(default=None, description="Autonomous System Number")
    type_id: int = Field(default=1, description="Connection type ID")
    proxy_type_id: int = Field(default=1, description="Proxy type ID")
    name: str = Field(default="", description="Port display name")
    server_port_type_id: int = Field(
        default=0,
        description="Server port type (0=shared, 1=dedicated)",
    )
    count: int = Field(default=1, ge=1, le=1000, description="Number of ports to create")
    ttl: int = Field(default=1, ge=1, description="Time-to-live in days")
    traffic_limit: int = Field(default=10, ge=1, description="Traffic limit in GB")


class PortFilterParams(BaseModel):
    """Query parameters for ``GET /v2/proxy/ports``.

    All fields are optional; omitted filters return all ports.
    """

    id: int | None = Field(default=None, description="Filter by port ID")
    proxy: str | None = Field(default=None, description="Filter by proxy address")
    # Field names mirror the ASocks API's camelCase query params exactly
    # (sent verbatim by ASocksClient.list_ports) — not a style violation.
    countryName: str | None = Field(default=None, description="Filter by country name")  # noqa: N815
    stateName: str | None = Field(default=None, description="Filter by state name")  # noqa: N815
    cityName: str | None = Field(default=None, description="Filter by city name")  # noqa: N815
    asn: int | None = Field(default=None, description="Filter by ASN")
    status: int | None = Field(default=None, description="Filter by status")
    template_id: int | None = Field(default=None, description="Filter by template ID")
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=200)


class UpdatePortRequest(BaseModel):
    """Body for ``PATCH /v2/proxy/update-port/{id}``.

    All fields are declared optional to mirror the official docs, but the
    live API rejects bodies missing ``geo_country_ids``, ``connection_type``
    or ``proxy_types`` — :meth:`asockslib.client.ASocksClient.update_port`
    validates this before sending. Pass the port's current values for
    fields you don't want to change.
    """

    geo_country_ids: list[int] | None = Field(default=None, description="Country IDs")
    geo_state_id: int | None = Field(default=None, description="State ID")
    geo_city_id: int | None = Field(default=None, description="City ID")
    asns: list[int] | None = Field(default=None, description="ASN list")
    connection_type: str | None = Field(default=None, description="Connection type")
    auth_type: str | None = Field(default=None, description="Auth type")
    proxy_types: list[str] | None = Field(default=None, description="Proxy type list")
    name: str | None = Field(default=None, description="Port name")
    ttl: int | None = Field(default=None, description="TTL in days")
    traffic_limit: int | None = Field(default=None, description="Traffic limit in GB")


class CreateTemplateRequest(BaseModel):
    """Body for ``POST /v2/proxy-template/create-template``."""

    label: str = Field(description="Template label")
    template: str = Field(description="Template pattern, e.g. {ip}:{port}")


class UpdateTemplateRequest(BaseModel):
    """Body for ``PATCH /v2/proxy-template/update-template``."""

    label: str | None = Field(default=None, description="Template label")
    template: str | None = Field(default=None, description="Template pattern")
