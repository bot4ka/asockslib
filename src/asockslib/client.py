"""Async HTTP client for the ASocks REST API v2.

Covers all 25 endpoints at https://docs.asocks.com/en/.

Features:
    - Automatic retry with configurable exponential back-off on rate-limit
      (HTTP 429), server errors (HTTP 5xx) and transient network failures.
    - Non-idempotent requests (POST) are never retried on network/5xx errors
      so that a create-port call can never be silently duplicated.
    - Typed exceptions for every error HTTP status; network failures are
      wrapped in :class:`APIConnectionError`.
    - Authentication via ``apiKey`` query parameter.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from types import TracebackType

import httpx
from beartype import beartype
from pydantic import ValidationError

from asockslib.exceptions import (
    APIConnectionError,
    ASocksError,
    AuthenticationError,
    InsufficientBalanceError,
    PortNotFoundError,
    RateLimitError,
)
from asockslib.models import (
    ASNInfo,
    ASNListResponse,
    BalanceResponse,
    CityInfo,
    CountryInfo,
    CreatePortRequest,
    CreateTemplateRequest,
    PortFilterParams,
    PortInfo,
    PortListResponse,
    StateInfo,
    UpdatePortRequest,
    UpdateTemplateRequest,
    WhitelistAddRequest,
)

logger = logging.getLogger("asockslib")

_BASE_URL = "https://api.asocks.com"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_RETRIES = 5
_DEFAULT_BACKOFF_BASE = 1.0
_DEFAULT_BACKOFF_MAX = 30.0


class ASocksClient:
    """Async client for the ASocks Proxy API v2.

    Use as an async context manager so the HTTP session is
    closed automatically::

        async with ASocksClient(api_key="key") as client:
            balance = await client.get_balance()

    Args:
        api_key: ASocks API key.
        base_url: API base URL (default ``https://api.asocks.com``).
        timeout: HTTP request timeout in seconds.
        max_retries: Maximum number of attempts for a retryable request
            (HTTP 429, HTTP 5xx and transient network errors). ``1`` disables
            retrying. Applies per request.
        retry_backoff_base: Base delay in seconds for exponential back-off
            (attempt *n* waits ``base * 2**(n-1)`` seconds, capped at
            *retry_backoff_max*). Set to ``0`` to retry with no delay.
        retry_backoff_max: Upper bound on the back-off delay in seconds.
    """

    @beartype
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_backoff_base: float = _DEFAULT_BACKOFF_BASE,
        retry_backoff_max: float = _DEFAULT_BACKOFF_MAX,
    ) -> None:
        if not api_key:
            raise ValueError(
                "api_key is required. Get one at https://my.asocks.com and pass it "
                "as ASocksClient(api_key=...), or set the ASOCKS_API_KEY env var."
            )
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._retry_backoff_base = max(0.0, retry_backoff_base)
        self._retry_backoff_max = max(0.0, retry_backoff_max)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    async def __aenter__(self) -> ASocksClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── Internal helpers ──────────────────────────────────────────────── #

    def _handle_error(self, response: httpx.Response) -> None:
        """Map a non-2xx response to a typed exception."""
        status = response.status_code
        try:
            body: dict[str, Any] = response.json()
        except Exception:
            body = {}
        # response.json() can legitimately return a non-dict (e.g. a JSON
        # array) at runtime — the annotation above doesn't enforce that, so
        # this guard is load-bearing even though it looks redundant to pyright.
        if not isinstance(body, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            body = {}

        message = str(
            body.get("message", "") or body.get("error", "") or response.text or f"HTTP {status}"
        )

        if status in (401, 403):
            raise AuthenticationError(message, status_code=status)
        if status == 404:
            raise PortNotFoundError(message, status_code=status)
        if status == 402:
            raise InsufficientBalanceError(message, status_code=status)
        if status == 429:
            raise RateLimitError(message, status_code=status)
        raise ASocksError(message, status_code=status)

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential back-off delay (seconds) for the given 1-based attempt."""
        return min(self._retry_backoff_base * (2 ** (attempt - 1)), self._retry_backoff_max)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:  # noqa: ANN401 — raw, not-yet-validated JSON response body
        """Send an HTTP request to the API with automatic retry.

        Retries on HTTP 429, HTTP 5xx and transient network errors with
        exponential back-off. To avoid duplicating side effects, 5xx and
        network errors are **not** retried for non-idempotent (POST)
        requests — only 429 (which means the request was rejected, not
        processed) is retried in that case.

        Raises:
            APIConnectionError: Network/transport failure after all retries.
            RateLimitError / ASocksError: Mapped from the final HTTP response.
        """
        merged_params: dict[str, Any] = {"apiKey": self._api_key}
        if params:
            merged_params.update(params)

        # POST is not idempotent: a network timeout or 5xx might mean the
        # server already processed the request, so retrying could create
        # duplicate ports. Only 429 (guaranteed-not-processed) is retried.
        idempotent = method.upper() != "POST"

        for attempt in range(1, self._max_retries + 1):
            last_attempt = attempt >= self._max_retries
            logger.debug("%s %s params=%s body=%s", method, path, merged_params, json_body)
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=merged_params,
                    json=json_body,
                )
            except httpx.TransportError as exc:
                if idempotent and not last_attempt:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        "Network error on %s %s (attempt %d/%d): %s; retrying in %.1fs",
                        method,
                        path,
                        attempt,
                        self._max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise APIConnectionError(
                    f"Network error contacting the ASocks API "
                    f"({method} {path}) after {attempt} attempt(s): {exc}"
                ) from exc

            if response.is_success:
                return response.json()

            status = response.status_code
            retryable = status == 429 or (500 <= status < 600 and idempotent)
            if retryable and not last_attempt:
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "HTTP %d on %s %s (attempt %d/%d); retrying in %.1fs",
                    status,
                    method,
                    path,
                    attempt,
                    self._max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            self._handle_error(response)  # raises a typed ASocksError

        # Unreachable: the loop either returns or raises on the last attempt.
        raise ASocksError("Request failed after exhausting all retries")

    @staticmethod
    def _as_dict(data: Any) -> dict[str, Any]:  # noqa: ANN401 — raw, pre-validation JSON
        """Narrow a raw JSON response to a dict; ``{}`` if it wasn't one.

        ``_request()`` returns whatever the API sent (dict, list, ...); this
        gives every call site a properly-typed ``dict[str, Any]`` to call
        ``.get()`` on instead of re-deriving an ``isinstance`` guard each time.
        """
        return cast("dict[str, Any]", data) if isinstance(data, dict) else {}

    @staticmethod
    def _flatten_port(item: Any) -> Any:  # noqa: ANN401 — raw, pre-validation JSON
        """Flatten nested ``{proxy: ..., info: ...}`` to a flat dict.

        The API sometimes returns port data in a nested structure.
        This normalises it for ``PortInfo.model_validate()``.
        """
        if not isinstance(item, dict):
            return item
        item = cast("dict[str, Any]", item)
        if "proxy" in item and "info" in item:
            proxy: dict[str, Any] = item["proxy"]
            info_block: dict[str, Any] = item["info"]
            geo: dict[str, Any] = info_block.get("geo", {}) or {}
            traffic: dict[str, Any] = info_block.get("traffic", {}) or {}
            auth: dict[str, Any] = proxy.get("auth") or {}
            return {
                "id": info_block.get("id"),
                "host": proxy.get("host", ""),
                "port": proxy.get("port", 0),
                "login": auth.get("login", ""),
                "password": auth.get("password", ""),
                "protocol": proxy.get("protocol", "socks5"),
                "name": info_block.get("name", ""),
                "status": info_block.get("status", 0),
                "proxy_type_id": info_block.get("proxy_type_id"),
                "created_at": info_block.get("created_at"),
                "expires_at": info_block.get("expires_at"),
                "country": geo.get("country_name", ""),
                "country_code": geo.get("country_code", ""),
                "state": geo.get("state_name", ""),
                "city": geo.get("city_name", ""),
                "asn": geo.get("asn"),
                "external_ip": info_block.get("external_ip", ""),
                "traffic_used": traffic.get("spent"),
                "traffic_limit": traffic.get("limit"),
                "ttl": info_block.get("ttl"),
                "type_id": info_block.get("type_id"),
                "server_port_type_id": info_block.get("server_port_type_id"),
            }
        return item

    # ── User ──────────────────────────────────────────────────────────── #

    @beartype
    async def get_balance(self) -> BalanceResponse:
        """Get account balance.  ``GET /v2/user/balance``"""
        data = await self._request("GET", "/v2/user/balance")
        return BalanceResponse.model_validate(data)

    # ── Directory (geo) ───────────────────────────────────────────────── #

    @beartype
    async def get_countries(self) -> list[CountryInfo]:
        """List available countries.  ``GET /v2/dir/countries``"""
        data = await self._request("GET", "/v2/dir/countries")
        raw = self._as_dict(data).get("countries", [])
        return [CountryInfo.model_validate(item) for item in raw]

    @beartype
    async def get_states(self, country_id: int | None = None) -> list[StateInfo]:
        """List states/regions.  ``GET /v2/dir/states``

        Args:
            country_id: Filter by country ID.
        """
        params: dict[str, Any] = {}
        if country_id is not None:
            params["countryId"] = country_id
        data = await self._request("GET", "/v2/dir/states", params=params)
        raw = self._as_dict(data).get("states", [])
        return [StateInfo.model_validate(item) for item in raw]

    @beartype
    async def get_cities(
        self,
        country_id: int | None = None,
        state_id: int | None = None,
    ) -> list[CityInfo]:
        """List cities.  ``GET /v2/dir/cities``

        Args:
            country_id: Filter by country ID.
            state_id: Filter by state ID.
        """
        params: dict[str, Any] = {}
        if country_id is not None:
            params["countryId"] = country_id
        if state_id is not None:
            params["stateId"] = state_id
        data = await self._request("GET", "/v2/dir/cities", params=params)
        raw = self._as_dict(data).get("cities", [])
        return [CityInfo.model_validate(item) for item in raw]

    @beartype
    async def get_asns(
        self,
        country_id: int | None = None,
        state_id: int | None = None,
        city_id: int | None = None,
        page: int | None = None,
    ) -> ASNListResponse:
        """List ASN entries.  ``GET /v2/dir/asns``

        Args:
            country_id: Filter by country.
            state_id: Filter by state.
            city_id: Filter by city.
            page: Pagination page number.
        """
        params: dict[str, Any] = {}
        if country_id is not None:
            params["countryId"] = country_id
        if state_id is not None:
            params["stateId"] = state_id
        if city_id is not None:
            params["cityId"] = city_id
        if page is not None:
            params["page"] = page
        result = await self._request("GET", "/v2/dir/asns", params=params)
        raw_asns = self._as_dict(result).get("asns", result)
        if isinstance(raw_asns, list):
            raw_asns = cast("list[Any]", raw_asns)
            return ASNListResponse(data=[ASNInfo.model_validate(a) for a in raw_asns])
        return ASNListResponse.model_validate(raw_asns)

    # ── Plan ──────────────────────────────────────────────────────────── #

    @beartype
    async def get_plan_info(self, show_proxies: str = "") -> dict[str, Any]:
        """Get subscription plan info.  ``GET /v2/plan/info``

        Args:
            show_proxies: Optional proxy type filter
                (``"all"``, ``"mobile"``, ``"residential"``, ``"corporate"``).
        """
        params: dict[str, Any] = {}
        if show_proxies:
            params["showProxies"] = show_proxies
        result: dict[str, Any] = await self._request("GET", "/v2/plan/info", params=params)
        return result

    # ── Proxy — Search ────────────────────────────────────────────────── #

    @beartype
    async def search_proxies(
        self,
        country: str = "",
        limit: int = 1,
        types: list[str] | None = None,
    ) -> list[str]:
        """Search available proxies.  ``GET /v2/proxy/search``

        Returns:
            List of ``"IP:port"`` strings.
        """
        params: dict[str, Any] = {"limit": limit}
        if country:
            params["country"] = country
        if types:
            params["types"] = ",".join(types)
        data = await self._request("GET", "/v2/proxy/search", params=params)

        proxies: list[str] = []
        if isinstance(data, dict):
            for key, value in cast("dict[str, Any]", data).items():
                if key == "success":
                    continue
                if isinstance(value, str):
                    proxies.append(value)
        elif isinstance(data, list):
            for item in cast("list[Any]", data):
                if isinstance(item, str):
                    proxies.append(item)
        return proxies

    # ── Proxy — CRUD ──────────────────────────────────────────────────── #

    @beartype
    async def list_ports(
        self,
        filters: PortFilterParams | None = None,
    ) -> PortListResponse:
        """List proxy ports.  ``GET /v2/proxy/ports``

        Args:
            filters: Optional query filters.
        """
        params: dict[str, Any] = {}
        if filters:
            params = {k: v for k, v in filters.model_dump().items() if v is not None}
        data = await self._request("GET", "/v2/proxy/ports", params=params)

        if isinstance(data, dict):
            data = cast("dict[str, Any]", data)
            msg = data.get("message", data)
            if isinstance(msg, dict):
                msg = cast("dict[str, Any]", msg)
                raw_items = msg.get("data", [])
                if isinstance(raw_items, list):
                    raw_items = cast("list[Any]", raw_items)
                    flattened = [self._flatten_port(item) for item in raw_items]
                    msg["data"] = flattened
                    data["message"] = msg
            elif isinstance(msg, list):
                data["message"] = [self._flatten_port(item) for item in cast("list[Any]", msg)]

        return PortListResponse.model_validate(data)

    @beartype
    async def get_port(self, port_id: int) -> PortInfo:
        """Get detailed port info.  ``GET /v2/proxy/port-info``

        Raises:
            PortNotFoundError: Port does not exist.
        """
        data = await self._request("GET", "/v2/proxy/port-info", params={"id": port_id})
        msg = self._as_dict(data).get("message", data)
        flat = self._flatten_port(msg)
        return PortInfo.model_validate(flat)

    @beartype
    async def create_ports(self, request: CreatePortRequest) -> list[PortInfo]:
        """Create proxy ports.  ``POST /v2/proxy/create-port``

        Raises:
            InsufficientBalanceError: Not enough funds.
        """
        body = {k: v for k, v in request.model_dump().items() if v not in (None, "")}
        data = await self._request("POST", "/v2/proxy/create-port", json_body=body)
        items: Any = (
            cast("dict[str, Any]", data).get("data", []) if isinstance(data, dict) else data
        )
        if not isinstance(items, list):
            items = [items]
        result: list[PortInfo] = []
        for item in cast("list[Any]", items):
            try:
                result.append(PortInfo.model_validate(item))
            except ValidationError as exc:
                logger.warning("Skipping invalid port data: %s", exc)
        return result

    @beartype
    async def delete_port(self, port_id: int) -> bool:
        """Delete a proxy port.  ``DELETE /v2/proxy/delete-port``"""
        data = await self._request("DELETE", "/v2/proxy/delete-port", params={"id": port_id})
        return bool(self._as_dict(data).get("success", False))

    @beartype
    async def archive_port(self, port_id: int) -> bool:
        """Archive a proxy port.  ``PATCH /v2/proxy/archive-port``"""
        data = await self._request("PATCH", "/v2/proxy/archive-port", params={"id": port_id})
        return bool(self._as_dict(data).get("success", False))

    @beartype
    async def unarchive_port(self, port_id: int) -> bool:
        """Restore a port from the archive.  ``PATCH /v2/proxy/unarchive``"""
        data = await self._request("PATCH", "/v2/proxy/unarchive", params={"id": port_id})
        return bool(self._as_dict(data).get("success", False))

    @beartype
    async def refresh_ip(self, port_id: int) -> bool:
        """Refresh the external IP of a port.  ``GET /v2/proxy/refresh/{portId}``"""
        data = await self._request("GET", f"/v2/proxy/refresh/{port_id}")
        return bool(self._as_dict(data).get("success", False))

    @beartype
    async def change_port_name(self, port_id: int, name: str) -> bool:
        """Rename a proxy port.  ``PATCH /v2/proxy/change-name``"""
        data = await self._request(
            "PATCH",
            "/v2/proxy/change-name",
            params={"id": port_id},
            json_body={"name": name},
        )
        return bool(self._as_dict(data).get("success", False))

    @beartype
    async def get_total_spent_traffic(self) -> dict[str, Any]:
        """Get total spent traffic.  ``GET /v2/proxy/total-spent-traffic``"""
        result: dict[str, Any] = await self._request("GET", "/v2/proxy/total-spent-traffic")
        return result

    @beartype
    async def change_credentials(self) -> bool:
        """Regenerate credentials for all ports.  ``GET /v2/proxy/change-credentials``"""
        data = await self._request("GET", "/v2/proxy/change-credentials")
        return bool(self._as_dict(data).get("success", False))

    @beartype
    async def update_port(self, port_id: int, request: UpdatePortRequest) -> dict[str, Any]:
        """Update port parameters.  ``PATCH /v2/proxy/update-port/{id}``"""
        body = {k: v for k, v in request.model_dump().items() if v is not None}
        result: dict[str, Any] = await self._request(
            "PATCH",
            f"/v2/proxy/update-port/{port_id}",
            json_body=body,
        )
        return result

    @beartype
    async def update_port_credentials(self, port_id: int, password: str) -> dict[str, Any]:
        """Update credentials for a single port.  ``PUT /v2/proxy/{id}/update-credentials``"""
        result: dict[str, Any] = await self._request(
            "PUT",
            f"/v2/proxy/{port_id}/update-credentials",
            json_body={"password": password},
        )
        return result

    # ── Templates ─────────────────────────────────────────────────────── #

    @beartype
    async def list_templates(self, page: int = 1) -> dict[str, Any]:
        """List proxy templates.  ``GET /v2/proxy-template``"""
        result: dict[str, Any] = await self._request(
            "GET",
            "/v2/proxy-template",
            params={"page": page},
        )
        return result

    @beartype
    async def create_template(self, request: CreateTemplateRequest) -> dict[str, Any]:
        """Create a proxy template.  ``POST /v2/proxy-template/create-template``"""
        result: dict[str, Any] = await self._request(
            "POST",
            "/v2/proxy-template/create-template",
            json_body=request.model_dump(),
        )
        return result

    @beartype
    async def update_template(
        self,
        template_id: int,
        request: UpdateTemplateRequest,
    ) -> dict[str, Any]:
        """Update a proxy template.  ``PATCH /v2/proxy-template/update-template``"""
        body = {k: v for k, v in request.model_dump().items() if v is not None}
        result: dict[str, Any] = await self._request(
            "PATCH",
            "/v2/proxy-template/update-template",
            params={"id": template_id},
            json_body=body,
        )
        return result

    @beartype
    async def delete_template(self, template_id: int) -> bool:
        """Delete a proxy template.  ``DELETE /v2/proxy-template/delete-template``"""
        data = await self._request(
            "DELETE",
            "/v2/proxy-template/delete-template",
            params={"id": template_id},
        )
        return bool(self._as_dict(data).get("success", False))

    # ── Whitelist ─────────────────────────────────────────────────────── #

    @beartype
    async def add_whitelist_ip(self, request: WhitelistAddRequest) -> dict[str, Any]:
        """Add an IP to the whitelist.  ``POST /v2/whitelist/add``"""
        result: dict[str, Any] = await self._request(
            "POST",
            "/v2/whitelist/add",
            json_body=request.model_dump(),
        )
        return result

    @beartype
    async def delete_whitelist_ip(self, ip: str) -> bool:
        """Remove an IP from the whitelist.  ``DELETE /v2/whitelist/delete``"""
        data = await self._request(
            "DELETE",
            "/v2/whitelist/delete",
            params={"ip": ip},
        )
        return bool(self._as_dict(data).get("success", False))
