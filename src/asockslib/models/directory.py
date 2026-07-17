"""Directory (geo) models for the ASocks API v2.

Country, state, city, and ASN data structures returned by the
``/v2/dir/*`` endpoints.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field


class CountryInfo(BaseModel, extra="allow"):
    """Country entry from ``GET /v2/dir/countries``."""

    id: int = Field(description="Internal country ID")
    name: str = Field(default="", description="Full country name")
    code: str = Field(
        default="",
        description="ISO country code (e.g. US, DE)",
        validation_alias=AliasChoices("code", "short_name"),
    )

    @property
    def short_name(self) -> str:
        """Alias for :pyattr:`code` (backward-compatible)."""
        return self.code


class StateInfo(BaseModel, extra="allow"):
    """State/region entry from ``GET /v2/dir/states``."""

    id: int = Field(description="Internal state ID")
    name: str = Field(default="", description="State/region name")
    dir_country_id: int | None = Field(default=None, description="Parent country ID")


class CityInfo(BaseModel, extra="allow"):
    """City entry from ``GET /v2/dir/cities``."""

    id: int = Field(description="Internal city ID")
    name: str = Field(default="", description="City name")
    dir_country_id: int | None = Field(default=None, description="Parent country ID")
    dir_state_id: int | None = Field(default=None, description="Parent state ID")


class ASNInfo(BaseModel, extra="allow"):
    """ASN (Autonomous System Number) entry from ``GET /v2/dir/asns``."""

    asn: int = Field(description="Autonomous System Number")
    name: str = Field(default="", description="ISP / provider name")


class ASNListResponse(BaseModel, extra="allow"):
    """Paginated response for ``GET /v2/dir/asns``."""

    data: list[ASNInfo] = Field(default_factory=list[ASNInfo], description="ASN entries")
    current_page: int = Field(default=1, description="Current page number")
    per_page: int = Field(default=1000, description="Items per page")
    total: int = Field(default=0, description="Total number of ASN entries")
    last_page: int = Field(default=1, description="Last page number")

    @property
    def items(self) -> list[ASNInfo]:
        """Alias for ``data``."""
        return self.data
