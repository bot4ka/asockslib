"""Comprehensive tests for the exception hierarchy."""

from __future__ import annotations

import pytest

from asockslib.exceptions import (
    ASocksError,
    AuthenticationError,
    InsufficientBalanceError,
    NoAvailableProxyError,
    PortNotFoundError,
    ProxyHealthError,
    RateLimitError,
)

# --------------------------------------------------------------------------- #
#  ASocksError base
# --------------------------------------------------------------------------- #


class TestASocksError:
    """Tests for the base ASocksError exception."""

    def test_message(self) -> None:
        err = ASocksError("something failed")
        assert err.message == "something failed"
        assert str(err) == "something failed"

    def test_status_code_default(self) -> None:
        err = ASocksError("fail")
        assert err.status_code is None

    def test_status_code_explicit(self) -> None:
        err = ASocksError("fail", status_code=500)
        assert err.status_code == 500

    def test_is_exception(self) -> None:
        assert issubclass(ASocksError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(ASocksError, match="test"):
            raise ASocksError("test")


# --------------------------------------------------------------------------- #
#  AuthenticationError
# --------------------------------------------------------------------------- #


class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_inherits_asocks_error(self) -> None:
        assert issubclass(AuthenticationError, ASocksError)

    def test_message(self) -> None:
        err = AuthenticationError("Invalid API key", status_code=401)
        assert err.message == "Invalid API key"
        assert err.status_code == 401

    def test_catch_as_base(self) -> None:
        with pytest.raises(ASocksError):
            raise AuthenticationError("bad key")


# --------------------------------------------------------------------------- #
#  RateLimitError
# --------------------------------------------------------------------------- #


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_inherits_asocks_error(self) -> None:
        assert issubclass(RateLimitError, ASocksError)

    def test_message(self) -> None:
        err = RateLimitError("Too many requests", status_code=429)
        assert err.message == "Too many requests"
        assert err.status_code == 429

    def test_catch_specific(self) -> None:
        with pytest.raises(RateLimitError):
            raise RateLimitError("rate limit", status_code=429)


# --------------------------------------------------------------------------- #
#  PortNotFoundError
# --------------------------------------------------------------------------- #


class TestPortNotFoundError:
    """Tests for PortNotFoundError."""

    def test_inherits_asocks_error(self) -> None:
        assert issubclass(PortNotFoundError, ASocksError)

    def test_message(self) -> None:
        err = PortNotFoundError("Port 42 not found", status_code=404)
        assert err.message == "Port 42 not found"
        assert err.status_code == 404


# --------------------------------------------------------------------------- #
#  InsufficientBalanceError
# --------------------------------------------------------------------------- #


class TestInsufficientBalanceError:
    """Tests for InsufficientBalanceError."""

    def test_inherits_asocks_error(self) -> None:
        assert issubclass(InsufficientBalanceError, ASocksError)

    def test_message(self) -> None:
        err = InsufficientBalanceError("Low balance", status_code=402)
        assert err.message == "Low balance"
        assert err.status_code == 402


# --------------------------------------------------------------------------- #
#  ProxyHealthError
# --------------------------------------------------------------------------- #


class TestProxyHealthError:
    """Tests for ProxyHealthError."""

    def test_inherits_asocks_error(self) -> None:
        assert issubclass(ProxyHealthError, ASocksError)

    def test_message(self) -> None:
        err = ProxyHealthError("Proxy check failed")
        assert err.message == "Proxy check failed"
        assert err.status_code is None


# --------------------------------------------------------------------------- #
#  NoAvailableProxyError
# --------------------------------------------------------------------------- #


class TestNoAvailableProxyError:
    """Tests for NoAvailableProxyError."""

    def test_inherits_asocks_error(self) -> None:
        assert issubclass(NoAvailableProxyError, ASocksError)

    def test_message(self) -> None:
        err = NoAvailableProxyError("No proxies available")
        assert err.message == "No proxies available"
        assert err.status_code is None

    def test_catch_hierarchy(self) -> None:
        """All errors can be caught as ASocksError."""
        exceptions: list[type[ASocksError]] = [
            AuthenticationError,
            RateLimitError,
            PortNotFoundError,
            InsufficientBalanceError,
            ProxyHealthError,
            NoAvailableProxyError,
        ]
        for exc_cls in exceptions:
            with pytest.raises(ASocksError):
                raise exc_cls(f"test {exc_cls.__name__}")
