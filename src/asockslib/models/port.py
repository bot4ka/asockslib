"""Port models for the ASocks API v2.

Defines :class:`PortInfo` (single proxy port) and
:class:`PortListResponse` (paginated port list wrapper).
"""

from __future__ import annotations

from typing import ClassVar, cast

from beartype import beartype
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from asockslib.models.enums import PortStatus


class PortInfo(BaseModel, extra="allow"):
    """A single proxy port returned by the API.

    Produced by ``GET /v2/proxy/ports``, ``GET /v2/proxy/port-info``
    and ``POST /v2/proxy/create-port``.

    Attributes:
        id: Unique port identifier.
        host: Proxy server address.
        port: Port number.
        login: Authentication login.
        password: Authentication password.
        protocol: Proxy protocol (``socks5``, ``http``, …).
        proxy_type: Proxy category.
        country_code: ISO country code.
        status: Port status code (see :class:`PortStatus`).

    Example::

        print(port.proxy_url)   # socks5://user:pass@host:10001
        print(port.is_active)   # True
    """

    id: int = Field(description="Unique port identifier")
    host: str = Field(
        default="",
        description="Proxy host address",
        validation_alias=AliasChoices("host", "server"),
    )
    port: int = Field(default=0, description="Proxy port number")
    login: str = Field(default="", description="Authentication login")
    password: str = Field(default="", description="Authentication password")
    protocol: str = Field(default="socks5", description="Proxy protocol")
    proxy_type: str | None = Field(default=None, description="Proxy type category")
    country: str = Field(default="", description="Country name")
    country_code: str = Field(default="", description="ISO country code")
    city: str = Field(default="", description="City name")
    state: str = Field(default="", description="State name")
    status: int | str = Field(default=1, description="Port status code")
    name: str = Field(default="", description="User-defined port name")
    asn: int | None = Field(default=None, description="Autonomous System Number")
    external_ip: str = Field(default="", description="External IP address")

    @model_validator(mode="before")
    @classmethod
    def _coerce_none_strings(cls, data: dict[str, object] | object) -> dict[str, object] | object:
        """Coerce ``None`` values to empty strings for str fields."""
        if not isinstance(data, dict):
            return data
        data = cast("dict[str, object]", data)
        _str_fields = (
            "host",
            "login",
            "password",
            "protocol",
            "country",
            "country_code",
            "city",
            "state",
            "name",
            "external_ip",
        )
        for fld in _str_fields:
            if fld in data and data[fld] is None:
                data[fld] = ""
        return data

    expires_at: str | None = Field(default=None, description="Expiration timestamp")
    created_at: str | None = Field(default=None, description="Creation timestamp")
    ttl: int | None = Field(default=None, description="Time-to-live in days")
    traffic_limit: float | None = Field(default=None, description="Traffic limit in GB")
    traffic_used: float | None = Field(default=None, description="Traffic used in GB")
    type_id: int | None = Field(default=None, description="Connection type ID")
    proxy_type_id: int | None = Field(default=None, description="Proxy type ID")
    server_port_type_id: int | None = Field(default=None, description="Server port type ID")

    _STATUS_MAP: ClassVar[dict[str, int]] = {
        "active": 1,
        "inactive": 0,
        "expired": 2,
        "stopped": 0,
        "error": 0,
    }

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, v: object) -> int:
        """Accept both int and string status from the API.

        Typed ``object`` (not ``int | str``): a ``mode="before"`` validator
        receives the raw, not-yet-validated JSON value, which may be any type.
        """
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            low = v.strip().lower()
            if low.isdigit():
                return int(low)
            return cls._STATUS_MAP.get(low, 0)
        return int(cast("int", v))

    @property
    def proxy_url(self) -> str:
        """Full proxy URL (``protocol://login:password@host:port``)."""
        auth = f"{self.login}:{self.password}@" if self.login else ""
        proto = self.protocol or "socks5"
        return f"{proto}://{auth}{self.host}:{self.port}"

    @beartype
    def format_with_template(self, template: str) -> str:
        """Format the proxy using a template string.

        Supported placeholders: ``{protocol}``, ``{id}``, ``{login}``,
        ``{password}``, ``{ip}``, ``{port}``, ``{refresh_link}``,
        ``{name}``, ``{external_ip}``.

        Example::

            port.format_with_template("{ip}:{port}:{login}:{password}")
            # "1.2.3.4:8080:u:p"
        """
        refresh = f"https://api.asocks.com/v2/proxy/refresh-ip/{self.id}"
        return (
            template.replace("{protocol}", self.protocol or "socks5")
            .replace("{id}", str(self.id))
            .replace("{login}", self.login)
            .replace("{password}", self.password)
            .replace("{ip}", self.host)
            .replace("{port}", str(self.port))
            .replace("{refresh_link}", refresh)
            .replace("{name}", self.name)
            .replace("{external_ip}", self.external_ip)
        )

    @property
    def is_active(self) -> bool:
        """``True`` when the port status is :attr:`PortStatus.ACTIVE`."""
        return self.status == PortStatus.ACTIVE  # type: ignore[comparison-overlap]


class PortListResponse(BaseModel, extra="allow"):
    """Response wrapper for ``GET /v2/proxy/ports``.

    The API may return either a flat list or a paginated envelope
    (``{data: [...], total: N, ...}``); this model handles both.
    """

    success: bool = Field(default=True)
    message: list[PortInfo] | dict[str, object] = Field(default_factory=list[PortInfo])

    @property
    def items(self) -> list[PortInfo]:
        """Port list regardless of the envelope format."""
        if isinstance(self.message, list):
            return self.message
        data = self.message.get("data", [])
        if isinstance(data, list):
            return [PortInfo.model_validate(d) for d in cast("list[object]", data)]
        return []

    @property
    def total(self) -> int:
        """Total number of ports."""
        if isinstance(self.message, dict):
            raw_total = self.message.get("total", 0)
            if isinstance(raw_total, int):
                return raw_total
            if isinstance(raw_total, str) and raw_total.strip().lstrip("-").isdigit():
                return int(raw_total)
            return 0
        return len(self.message)
