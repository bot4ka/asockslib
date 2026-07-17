"""Response models for the ASocks API v2.

Typed wrappers for API response payloads that don't fit into
the port or directory categories.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BalanceResponse(BaseModel, extra="allow"):
    """Response for ``GET /v2/user/balance``."""

    success: bool = Field(default=True)
    balance: float = Field(default=0, description="Account balance in USD")
    balance_traffic: float = Field(default=0, description="Traffic balance")
    all_available_traffic: float = Field(default=0, description="Total available traffic")
    prepared_traffic_balance: float = Field(default=0, description="Prepared traffic balance")
    balance_hold: float = Field(default=0, description="Held balance")
