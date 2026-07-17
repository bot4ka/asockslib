"""Tests for the benchmark / ping module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from asockslib.benchmark import (
    CountryPingResult,
    ProxyBenchmarkResult,
    benchmark_proxies,
    ping_proxy,
    select_best_proxies,
)


class TestProxyBenchmarkResult:
    """Tests for ProxyBenchmarkResult dataclass."""

    def test_defaults(self) -> None:
        r = ProxyBenchmarkResult(proxy_url="socks5://u:p@1.2.3.4:1000")
        assert r.proxy_url == "socks5://u:p@1.2.3.4:1000"
        assert r.port_id == 0
        assert r.latency_ms is None
        assert r.external_ip == ""
        assert r.is_alive is False
        assert r.country == ""
        assert r.city == ""
        assert r.error == ""

    def test_with_data(self) -> None:
        r = ProxyBenchmarkResult(
            proxy_url="socks5://u:p@1.2.3.4:1000",
            port_id=42,
            latency_ms=123.4,
            external_ip="5.6.7.8",
            is_alive=True,
            country="US",
            city="New York",
        )
        assert r.port_id == 42
        assert r.latency_ms == 123.4
        assert r.is_alive is True


class TestCountryPingResult:
    """Tests for CountryPingResult dataclass."""

    def test_defaults(self) -> None:
        r = CountryPingResult()
        assert r.country_name == ""
        assert r.avg_latency_ms == 0.0
        assert r.samples == []

    def test_with_samples(self) -> None:
        samples = [
            ProxyBenchmarkResult(proxy_url="socks5://a:b@1.2.3.4:1", latency_ms=100, is_alive=True),
            ProxyBenchmarkResult(proxy_url="socks5://a:b@5.6.7.8:2", latency_ms=200, is_alive=True),
        ]
        r = CountryPingResult(
            country_name="United States",
            country_code="US",
            avg_latency_ms=150.0,
            min_latency_ms=100.0,
            max_latency_ms=200.0,
            alive_count=2,
            total_count=2,
            availability="Много",
            samples=samples,
        )
        assert len(r.samples) == 2
        assert r.availability == "Много"


class TestPingProxy:
    """Tests for ping_proxy — uses unreachable proxy so it fails fast."""

    @pytest.mark.asyncio
    async def test_ping_unreachable_proxy(self) -> None:
        """Pinging an unreachable proxy returns is_alive=False."""
        result = await ping_proxy(
            "socks5://fake:fake@127.0.0.1:1",
            timeout=1.0,
        )
        assert result.is_alive is False
        assert result.latency_ms is None
        assert result.error != ""

    @pytest.mark.asyncio
    async def test_ping_returns_correct_url(self) -> None:
        url = "socks5://test:test@127.0.0.1:1"
        result = await ping_proxy(url, timeout=1.0)
        assert result.proxy_url == url

    @pytest.mark.asyncio
    async def test_ping_success_mock(self) -> None:
        """Ping succeeds when proxy is reachable (mocked)."""
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ip": "5.6.7.8"}

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("asockslib.benchmark.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await ping_proxy("socks5://u:p@1.2.3.4:1000", timeout=5.0)
            assert result.is_alive is True
            assert result.latency_ms is not None
            assert result.latency_ms >= 0
            assert result.external_ip == "5.6.7.8"
            assert result.error == ""

    @pytest.mark.asyncio
    async def test_ping_http_error_status(self) -> None:
        """Ping records error when all endpoints return non-success status."""
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 403

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("asockslib.benchmark.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await ping_proxy(
                "socks5://u:p@1.2.3.4:1000",
                timeout=5.0,
                ping_urls=["https://api.ipify.org?format=json"],
            )
            assert result.is_alive is False
            assert result.error == "All ping endpoints failed"

    @pytest.mark.asyncio
    async def test_ping_custom_url(self) -> None:
        """Ping uses custom ping_urls."""
        result = await ping_proxy(
            "socks5://u:p@127.0.0.1:1",
            timeout=1.0,
            ping_urls=["https://example.com/health"],
        )
        assert result.is_alive is False  # unreachable, but no crash


class TestBenchmarkProxies:
    """Tests for benchmark_proxies batch function."""

    @pytest.mark.asyncio
    async def test_benchmark_empty_list(self) -> None:
        results = await benchmark_proxies([])
        assert results == []

    @pytest.mark.asyncio
    async def test_benchmark_dead_proxies(self) -> None:
        urls = [
            "socks5://a:b@127.0.0.1:1",
            "socks5://a:b@127.0.0.1:2",
        ]
        results = await benchmark_proxies(urls, timeout=1.0)
        assert len(results) == 2
        assert all(not r.is_alive for r in results)

    @pytest.mark.asyncio
    async def test_benchmark_sorted_dead_last(self) -> None:
        """Dead proxies only — all should be in results."""
        urls = ["socks5://x:x@127.0.0.1:1"]
        results = await benchmark_proxies(urls, timeout=1.0)
        assert len(results) == 1
        assert not results[0].is_alive

    @pytest.mark.asyncio
    async def test_benchmark_alive_sorted_by_latency(self) -> None:
        """Alive proxies are sorted by latency (best first)."""

        async def _mock_ping(
            url: str,
            *,
            timeout: float = 10.0,
            ping_urls: list[str] | None = None,
        ) -> ProxyBenchmarkResult:
            # Assign latency based on port number in URL
            if "1000" in url:
                return ProxyBenchmarkResult(proxy_url=url, latency_ms=200.0, is_alive=True)
            if "2000" in url:
                return ProxyBenchmarkResult(proxy_url=url, latency_ms=50.0, is_alive=True)
            return ProxyBenchmarkResult(proxy_url=url, is_alive=False, error="dead")

        with patch("asockslib.benchmark.ping_proxy", side_effect=_mock_ping):
            urls = [
                "socks5://u:p@1.2.3.4:1000",
                "socks5://u:p@5.6.7.8:2000",
                "socks5://u:p@9.9.9.9:3000",
            ]
            results = await benchmark_proxies(urls, timeout=1.0)
            assert len(results) == 3
            # Best latency first
            assert results[0].latency_ms == 50.0
            assert results[1].latency_ms == 200.0
            # Dead last
            assert results[2].is_alive is False

    @pytest.mark.asyncio
    async def test_benchmark_concurrency_param(self) -> None:
        """benchmark_proxies respects concurrency parameter."""
        urls = ["socks5://a:b@127.0.0.1:1"]
        results = await benchmark_proxies(urls, timeout=1.0, concurrency=1)
        assert len(results) == 1


class TestSelectBestProxies:
    """Tests for select_best_proxies."""

    @pytest.mark.asyncio
    async def test_select_best_empty(self) -> None:
        best, discard = await select_best_proxies([], keep=5)
        assert best == []
        assert discard == []

    @pytest.mark.asyncio
    async def test_select_best_all_dead(self) -> None:
        urls = [
            "socks5://a:b@127.0.0.1:1",
            "socks5://a:b@127.0.0.1:2",
            "socks5://a:b@127.0.0.1:3",
        ]
        best, discard = await select_best_proxies(urls, keep=2, timeout=1.0)
        # All dead → first 2 in best, rest in discard
        assert len(best) == 2
        assert len(discard) == 1

    @pytest.mark.asyncio
    async def test_select_best_mixed(self) -> None:
        """select_best_proxies with a mix of alive and dead proxies."""

        async def _mock_ping(
            url: str,
            *,
            timeout: float = 10.0,
            ping_urls: list[str] | None = None,
        ) -> ProxyBenchmarkResult:
            if "1000" in url:
                return ProxyBenchmarkResult(proxy_url=url, latency_ms=100.0, is_alive=True)
            if "2000" in url:
                return ProxyBenchmarkResult(proxy_url=url, latency_ms=50.0, is_alive=True)
            return ProxyBenchmarkResult(proxy_url=url, is_alive=False, error="dead")

        with patch("asockslib.benchmark.ping_proxy", side_effect=_mock_ping):
            urls = [
                "socks5://u:p@1.2.3.4:1000",
                "socks5://u:p@5.6.7.8:2000",
                "socks5://u:p@9.9.9.9:3000",
            ]
            best, discard = await select_best_proxies(urls, keep=1, timeout=1.0)
            assert len(best) == 1
            # Best proxy has lowest latency
            assert best[0].latency_ms == 50.0
            assert len(discard) == 2

    @pytest.mark.asyncio
    async def test_select_best_keep_more_than_available(self) -> None:
        """keep > total results → all in best, none in discard."""
        urls = ["socks5://a:b@127.0.0.1:1"]
        best, discard = await select_best_proxies(urls, keep=10, timeout=1.0)
        assert len(best) == 1
        assert discard == []
