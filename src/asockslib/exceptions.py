"""Custom exceptions for the ASocks library.

Exception hierarchy::

    ASocksError (base)
    ├── AuthenticationError      # HTTP 401/403
    ├── RateLimitError           # HTTP 429
    ├── PortNotFoundError        # HTTP 404
    ├── InsufficientBalanceError # HTTP 402
    ├── APIConnectionError       # network/transport failure (timeout, refused)
    ├── ProxyHealthError         # proxy health-check failure
    └── NoAvailableProxyError    # proxy pool exhausted

All exceptions inherit from :class:`ASocksError`, allowing a single
``except`` block to catch every library error.
"""

from __future__ import annotations


class ASocksError(Exception):
    """Base exception for all ASocks errors.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code returned by the API, if applicable.

    Example::

        try:
            await client.get_balance()
        except ASocksError as e:
            print(f"Error [{e.status_code}]: {e.message}")
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class AuthenticationError(ASocksError):
    """Invalid or missing API key (HTTP 401/403)."""


class RateLimitError(ASocksError):
    """API rate limit exceeded (HTTP 429).

    The client retries automatically with exponential back-off
    (up to 5 attempts). This exception is raised only after all
    retries are exhausted.
    """


class PortNotFoundError(ASocksError):
    """Requested port does not exist (HTTP 404)."""


class InsufficientBalanceError(ASocksError):
    """Insufficient account balance (HTTP 402).

    Top up your balance at https://my.asocks.com.
    """


class APIConnectionError(ASocksError):
    """Network/transport failure talking to the ASocks API.

    Raised when the HTTP request cannot complete — connection refused,
    connection reset, DNS failure, or timeout — after all retries are
    exhausted. Wraps the underlying ``httpx.TransportError`` (available
    via ``__cause__``) so callers get a single typed error to catch.
    """


class ProxyHealthError(ASocksError):
    """Proxy failed a health check.

    Raised by :class:`SmartProxy` when a proxy is unreachable,
    times out, or returns an unexpected response.
    """


class NoAvailableProxyError(ASocksError):
    """No proxies matching the requested criteria are available.

    Raised by :class:`SmartProxy` / :class:`ProxyPool` when the
    pool is empty or all proxies have failed health checks.
    """
