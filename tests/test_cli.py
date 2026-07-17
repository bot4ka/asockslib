"""Comprehensive tests for CLI commands.

Uses typer.testing.CliRunner with mocked ASocksClient
so no real API calls are made.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from asockslib.cli import ExportFormat, _apply_proxy_template, _format_output, app
from asockslib.exceptions import (
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
    PortInfo,
    PortListResponse,
    StateInfo,
)

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

# Reusable port data
SAMPLE_PORT = PortInfo(
    id=42,
    host="1.2.3.4",
    port=8080,
    login="user",
    password="pass",
    protocol="socks5",
    country="US",
    country_code="US",
    city="New York",
    state="NY",
    status=1,
    name="test-port",
)

SAMPLE_PORT_LIST_RESPONSE = PortListResponse(
    success=True,
    message=[SAMPLE_PORT],
)


# --------------------------------------------------------------------------- #
#  Helper function tests
# --------------------------------------------------------------------------- #


class TestFormatOutput:
    """Tests for _format_output helper."""

    def test_txt_format(self) -> None:
        result = _format_output(["a:1", "b:2"], ExportFormat.txt)
        assert result == "a:1\nb:2"

    def test_json_format(self) -> None:
        result = _format_output(["a:1"], ExportFormat.json)
        parsed = json.loads(result)
        assert parsed == ["a:1"]

    def test_csv_format(self) -> None:
        result = _format_output(["a:1", "b:2"], ExportFormat.csv)
        assert "proxy_url" in result
        assert "a:1" in result
        assert "b:2" in result

    def test_empty_list(self) -> None:
        assert _format_output([], ExportFormat.txt) == ""

    def test_json_empty(self) -> None:
        result = _format_output([], ExportFormat.json)
        assert json.loads(result) == []


class TestGetApiKey:
    """Tests for _get_api_key helper."""

    def test_no_key_exits(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = runner.invoke(app, ["balance"])
            assert result.exit_code != 0


class TestApplyProxyTemplate:
    """Tests for _apply_proxy_template helper."""

    def test_standard_url(self) -> None:
        url = "socks5://user:pass@1.2.3.4:8080"
        tpl = "{protocol}://{login}:{password}@{ip}:{port}"
        assert _apply_proxy_template(url, tpl) == url

    def test_ip_port_login_password(self) -> None:
        url = "socks5://user:pass@1.2.3.4:8080"
        result = _apply_proxy_template(url, "{ip}:{port}:{login}:{password}")
        assert result == "1.2.3.4:8080:user:pass"

    def test_http_template(self) -> None:
        url = "socks5://user:pass@1.2.3.4:8080"
        result = _apply_proxy_template(url, "http://{login}:{password}@{ip}:{port}")
        assert result == "http://user:pass@1.2.3.4:8080"

    def test_with_port_id(self) -> None:
        url = "socks5://user:pass@1.2.3.4:8080"
        result = _apply_proxy_template(url, "{id}:{ip}:{port}", port_id=42)
        assert result == "42:1.2.3.4:8080"

    def test_with_refresh_link(self) -> None:
        url = "socks5://user:pass@1.2.3.4:8080"
        result = _apply_proxy_template(url, "{ip}:{port}[{refresh_link}]", port_id=99)
        assert result == "1.2.3.4:8080[https://api.asocks.com/v2/proxy/refresh-ip/99]"

    def test_with_name(self) -> None:
        url = "socks5://user:pass@1.2.3.4:8080"
        result = _apply_proxy_template(url, "{ip}:{port}:{name}", name="proxy-1")
        assert result == "1.2.3.4:8080:proxy-1"

    def test_curl_template(self) -> None:
        url = "http://u:p@h:80"
        result = _apply_proxy_template(
            url, "curl -x http://{login}:{password}@{ip}:{port} https://i.pn"
        )
        assert result == "curl -x http://u:p@h:80 https://i.pn"

    def test_pipe_separated(self) -> None:
        url = "socks5://user:pass@1.2.3.4:8080"
        result = _apply_proxy_template(url, "HTTP|{ip}|{port}|{login}|{password}")
        assert result == "HTTP|1.2.3.4|8080|user|pass"

    def test_key_from_env(self) -> None:
        # If the key is set, the command should proceed (and fail at API call)
        # We just verify it doesn't exit with "not set" message
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "test-key"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_balance = AsyncMock(return_value=BalanceResponse(balance=10.0))
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["balance"])
            assert "Error" not in (result.output or "")


# --------------------------------------------------------------------------- #
#  No-args-is-help
# --------------------------------------------------------------------------- #


class TestAppHelp:
    """Test that CLI shows help correctly."""

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # Typer may return 0 or 2 for no-args depending on config
        assert "Usage" in result.output or "asocks" in result.output or result.exit_code in (0, 2)

    def test_help_flag(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "balance" in result.output


# --------------------------------------------------------------------------- #
#  balance command
# --------------------------------------------------------------------------- #


class TestBalanceCommand:
    """Tests for 'asocks balance'."""

    def test_balance_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_balance = AsyncMock(
                return_value=BalanceResponse(
                    balance=42.5,
                    balance_traffic=10.0,
                    all_available_traffic=50.0,
                )
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["balance"])
            assert result.exit_code == 0
            assert "42.5" in result.output


# --------------------------------------------------------------------------- #
#  countries command
# --------------------------------------------------------------------------- #


class TestCountriesCommand:
    """Tests for 'asocks countries'."""

    def test_countries_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_countries = AsyncMock(
                return_value=[
                    CountryInfo(id=1, name="United States", code="US"),
                    CountryInfo(id=2, name="Germany", code="DE"),
                ]
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "countries"])
            assert result.exit_code == 0
            assert "United States" in result.output
            assert "Germany" in result.output

    def test_countries_empty(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_countries = AsyncMock(return_value=[])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "countries"])
            assert result.exit_code == 0


# --------------------------------------------------------------------------- #
#  states command
# --------------------------------------------------------------------------- #


class TestStatesCommand:
    """Tests for 'asocks states'."""

    def test_states_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_states = AsyncMock(return_value=[StateInfo(id=10, name="California")])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "states", "--country-id", "1"])
            assert result.exit_code == 0
            assert "California" in result.output


# --------------------------------------------------------------------------- #
#  cities command
# --------------------------------------------------------------------------- #


class TestCitiesCommand:
    """Tests for 'asocks cities'."""

    def test_cities_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_cities = AsyncMock(return_value=[CityInfo(id=100, name="Los Angeles")])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "cities", "--country-id", "1"])
            assert result.exit_code == 0
            assert "Los Angeles" in result.output

    def test_cities_with_state(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_cities = AsyncMock(
                return_value=[CityInfo(id=101, name="San Francisco")]
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "cities", "--country-id", "1", "--state-id", "10"])
            assert result.exit_code == 0
            assert "San Francisco" in result.output


# --------------------------------------------------------------------------- #
#  asns command
# --------------------------------------------------------------------------- #


class TestAsnsCommand:
    """Tests for 'asocks asns'."""

    def test_asns_dict_response(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_asns = AsyncMock(
                return_value=ASNListResponse(
                    data=[ASNInfo(asn=13335, name="Cloudflare")],
                    current_page=1,
                    per_page=1000,
                    total=1,
                    last_page=1,
                )
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "asns", "--country-id", "1"])
            assert result.exit_code == 0
            assert "Cloudflare" in result.output

    def test_asns_list_response(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_asns = AsyncMock(
                return_value=ASNListResponse(
                    data=[ASNInfo(asn=100, name="TestASN")],
                    current_page=1,
                    per_page=1000,
                    total=1,
                    last_page=1,
                )
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "asns"])
            assert result.exit_code == 0
            assert "TestASN" in result.output


# --------------------------------------------------------------------------- #
#  plan command
# --------------------------------------------------------------------------- #


class TestPlanCommand:
    """Tests for 'asocks plan'."""

    def test_plan_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_plan_info = AsyncMock(
                return_value={
                    "success": True,
                    "message": {"plan": "premium", "traffic_left": 50},
                }
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "plan"])
            assert result.exit_code == 0
            assert "premium" in result.output


# --------------------------------------------------------------------------- #
#  search command
# --------------------------------------------------------------------------- #


class TestSearchCommand:
    """Tests for 'asocks search'."""

    def test_search_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.search_proxies = AsyncMock(return_value=["1.2.3.4:1000", "5.6.7.8:2000"])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "search", "5", "--country", "US"])
            assert result.exit_code == 0
            assert "1.2.3.4:1000" in result.output

    def test_search_empty(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.search_proxies = AsyncMock(return_value=[])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "search"])
            assert "No proxies found" in result.output


# --------------------------------------------------------------------------- #
#  list command
# --------------------------------------------------------------------------- #


class TestListCommand:
    """Tests for 'asocks list'."""

    def test_list_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.list_ports = AsyncMock(return_value=SAMPLE_PORT_LIST_RESPONSE)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["list"])
            assert result.exit_code == 0
            assert "42" in result.output

    def test_list_with_filters(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.list_ports = AsyncMock(
                return_value=PortListResponse(success=True, message=[])
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app,
                ["list", "--country", "US", "--status", "1", "--page", "2"],
            )
            assert result.exit_code == 0


# --------------------------------------------------------------------------- #
#  info command
# --------------------------------------------------------------------------- #


class TestInfoCommand:
    """Tests for 'asocks info'."""

    def test_info_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_port = AsyncMock(return_value=SAMPLE_PORT)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["info", "42"])
            assert result.exit_code == 0
            assert "42" in result.output


# --------------------------------------------------------------------------- #
#  generate command
# --------------------------------------------------------------------------- #


class TestGenerateCommand:
    """Tests for 'asocks generate'."""

    def test_generate_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_ports = AsyncMock(return_value=[SAMPLE_PORT])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "generate", "1", "--country", "US"])
            assert result.exit_code == 0
            assert "socks5://" in result.output

    def test_generate_no_ports(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_ports = AsyncMock(return_value=[])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "generate", "1"])
            assert "No ports" in result.output

    def test_generate_to_file(self, tmp_path: Path) -> None:
        outfile = str(tmp_path / "proxies.txt")
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_ports = AsyncMock(return_value=[SAMPLE_PORT])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app, ["api", "generate", "1", "--output", outfile, "--format", "txt"]
            )
            assert result.exit_code == 0
            assert "Saved" in result.output
            with open(outfile) as f:
                content = f.read()
            assert "socks5://" in content

    def test_generate_json_format(self, tmp_path: Path) -> None:
        outfile = str(tmp_path / "proxies.json")
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_ports = AsyncMock(return_value=[SAMPLE_PORT])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app, ["api", "generate", "1", "--output", outfile, "--format", "json"]
            )
            assert result.exit_code == 0
            with open(outfile) as f:
                data: list[object] = json.load(f)
            assert isinstance(data, list)
            assert len(data) == 1

    def test_generate_csv_format(self, tmp_path: Path) -> None:
        outfile = str(tmp_path / "proxies.csv")
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_ports = AsyncMock(return_value=[SAMPLE_PORT])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app, ["api", "generate", "1", "--output", outfile, "--format", "csv"]
            )
            assert result.exit_code == 0
            with open(outfile) as f:
                content = f.read()
            assert "proxy_url" in content


# --------------------------------------------------------------------------- #
#  delete command
# --------------------------------------------------------------------------- #


class TestDeleteCommand:
    """Tests for 'asocks delete'."""

    def test_delete_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.delete_port = AsyncMock(return_value=True)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["delete", "42"])
            assert result.exit_code == 0
            assert "deleted" in result.output

    def test_delete_failure(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.delete_port = AsyncMock(return_value=False)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["delete", "42"])
            assert "Failed" in result.output


# --------------------------------------------------------------------------- #
#  archive / unarchive commands
# --------------------------------------------------------------------------- #


class TestArchiveCommands:
    """Tests for archive and unarchive commands."""

    def test_archive_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.archive_port = AsyncMock(return_value=True)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "archive", "42"])
            assert "archived" in result.output

    def test_archive_failure(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.archive_port = AsyncMock(return_value=False)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "archive", "42"])
            assert "Failed" in result.output

    def test_unarchive_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.unarchive_port = AsyncMock(return_value=True)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "unarchive", "42"])
            assert "unarchived" in result.output

    def test_unarchive_failure(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.unarchive_port = AsyncMock(return_value=False)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "unarchive", "42"])
            assert "Failed" in result.output


# --------------------------------------------------------------------------- #
#  refresh-ip command
# --------------------------------------------------------------------------- #


class TestRefreshIpCommand:
    """Tests for 'asocks refresh-ip'."""

    def test_refresh_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.refresh_ip = AsyncMock(return_value=True)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "refresh-ip", "42"])
            assert "refreshed" in result.output

    def test_refresh_failure(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.refresh_ip = AsyncMock(return_value=False)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "refresh-ip", "42"])
            assert "Failed" in result.output


# --------------------------------------------------------------------------- #
#  rename command
# --------------------------------------------------------------------------- #


class TestRenameCommand:
    """Tests for 'asocks rename'."""

    def test_rename_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.change_port_name = AsyncMock(return_value=True)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "rename", "42", "new-name"])
            assert "Renamed" in result.output or "renamed" in result.output

    def test_rename_failure(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.change_port_name = AsyncMock(return_value=False)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "rename", "42", "x"])
            assert "Failed" in result.output


# --------------------------------------------------------------------------- #
#  traffic command
# --------------------------------------------------------------------------- #


class TestTrafficCommand:
    """Tests for 'asocks traffic'."""

    def test_traffic_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_total_spent_traffic = AsyncMock(
                return_value={"total_spent_traffic": 12.5}
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "traffic"])
            assert result.exit_code == 0
            assert "12.5" in result.output


# --------------------------------------------------------------------------- #
#  change-credentials command
# --------------------------------------------------------------------------- #


class TestChangeCredentialsCommand:
    """Tests for 'asocks change-credentials'."""

    def test_change_credentials_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.change_credentials = AsyncMock(return_value=True)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "change-credentials"])
            assert "changed" in result.output

    def test_change_credentials_failure(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.change_credentials = AsyncMock(return_value=False)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "change-credentials"])
            assert "Failed" in result.output


# --------------------------------------------------------------------------- #
#  templates command
# --------------------------------------------------------------------------- #


class TestTemplatesCommand:
    """Tests for 'asocks templates'."""

    def test_templates_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.list_templates = AsyncMock(
                return_value={"success": True, "message": {"data": []}}
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "templates"])
            assert result.exit_code == 0


# --------------------------------------------------------------------------- #
#  template-create command
# --------------------------------------------------------------------------- #


class TestTemplateCreateCommand:
    """Tests for 'asocks template-create'."""

    def test_template_create_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_template = AsyncMock(
                return_value={"success": True, "template": {"id": 1}}
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app,
                [
                    "api",
                    "template-create",
                    "--label",
                    "tpl1",
                    "--template",
                    "{ip}:{port}",
                ],
            )
            assert result.exit_code == 0
            assert "created" in result.output


# --------------------------------------------------------------------------- #
#  template-delete command
# --------------------------------------------------------------------------- #


class TestTemplateDeleteCommand:
    """Tests for 'asocks template-delete'."""

    def test_template_delete_success(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.delete_template = AsyncMock(return_value=True)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "template-delete", "1"])
            assert "deleted" in result.output

    def test_template_delete_failure(self) -> None:
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.delete_template = AsyncMock(return_value=False)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "template-delete", "1"])
            assert "Failed" in result.output


# --------------------------------------------------------------------------- #
#  CLI Error Propagation — API exceptions raised inside CLI commands
# --------------------------------------------------------------------------- #


class TestCLIErrorPropagation:
    """Tests that API errors propagate through CLI commands."""

    def test_info_port_not_found(self) -> None:
        """`asocks info 12345` when port doesn't exist."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_port = AsyncMock(
                side_effect=PortNotFoundError("Not found", status_code=404)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["info", "12345"])
            assert result.exit_code == 1
            assert "Error" in result.output
            assert "Not found" in result.output

    def test_balance_auth_error(self) -> None:
        """Balance command with invalid API key."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "bad-key"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_balance = AsyncMock(
                side_effect=AuthenticationError("Unauthorized", status_code=401)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["balance"])
            assert result.exit_code == 1
            assert "Error" in result.output
            assert "Unauthorized" in result.output

    def test_generate_insufficient_balance(self) -> None:
        """Generate command when user has no balance."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_ports = AsyncMock(
                side_effect=InsufficientBalanceError("Low balance", status_code=402)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "generate", "10", "--country", "US"])
            assert result.exit_code == 1
            assert "Error" in result.output
            assert "Low balance" in result.output

    def test_delete_port_not_found(self) -> None:
        """Delete command when port doesn't exist."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.delete_port = AsyncMock(
                side_effect=PortNotFoundError("No such port", status_code=404)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["delete", "99999"])
            assert result.exit_code == 1
            assert "Error" in result.output
            assert "No such port" in result.output

    def test_search_rate_limited(self) -> None:
        """Search command when rate-limited."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.search_proxies = AsyncMock(
                side_effect=RateLimitError("Too many requests", status_code=429)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "search", "5"])
            assert result.exit_code == 1
            assert "Error" in result.output

    def test_list_generic_api_error(self) -> None:
        """List command with a generic API error."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.list_ports = AsyncMock(
                side_effect=ASocksError("Server error", status_code=500)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["list"])
            assert result.exit_code == 1
            assert "Error" in result.output
            assert "Server error" in result.output

    def test_archive_auth_error(self) -> None:
        """Archive command with auth error."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.archive_port = AsyncMock(
                side_effect=AuthenticationError("Forbidden", status_code=403)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "archive", "42"])
            assert result.exit_code == 1
            assert "Error" in result.output

    def test_refresh_ip_error(self) -> None:
        """Refresh-ip command with API error."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.refresh_ip = AsyncMock(
                side_effect=ASocksError("Server error", status_code=500)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "refresh-ip", "42"])
            assert result.exit_code == 1
            assert "Error" in result.output

    def test_rename_error(self) -> None:
        """Rename command with API error."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.change_port_name = AsyncMock(
                side_effect=ASocksError("fail", status_code=500)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "rename", "42", "x"])
            assert result.exit_code == 1
            assert "Error" in result.output

    def test_traffic_error(self) -> None:
        """Traffic command with auth error."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_total_spent_traffic = AsyncMock(
                side_effect=AuthenticationError("bad key", status_code=401)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "traffic"])
            assert result.exit_code == 1
            assert "Error" in result.output

    def test_template_create_error(self) -> None:
        """Template create with API error."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_template = AsyncMock(
                side_effect=ASocksError("fail", status_code=500)
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app, ["api", "template-create", "--label", "t", "--template", "{ip}"]
            )
            assert result.exit_code == 1
            assert "Error" in result.output


# --------------------------------------------------------------------------- #
#  CLI edge cases
# --------------------------------------------------------------------------- #


class TestCLIEdgeCases:
    """Edge case tests for CLI commands."""

    def test_templates_with_page(self) -> None:
        """Templates command with --page parameter."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.list_templates = AsyncMock(
                return_value={"success": True, "message": {"data": []}}
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "templates", "--page", "3"])
            assert result.exit_code == 0

    def test_list_with_all_filters(self) -> None:
        """List command with all filter options."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.list_ports = AsyncMock(
                return_value=PortListResponse(success=True, message=[])
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app,
                [
                    "list",
                    "--country",
                    "US",
                    "--status",
                    "1",
                    "--page",
                    "2",
                    "--per-page",
                    "25",
                ],
            )
            assert result.exit_code == 0

    def test_search_default_limit(self) -> None:
        """Search without specifying limit uses default."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.search_proxies = AsyncMock(return_value=["1.2.3.4:80"])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "search"])
            assert result.exit_code == 0
            assert "1.2.3.4:80" in result.output

    def test_generate_with_all_options(self) -> None:
        """Generate command with all options."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.create_ports = AsyncMock(return_value=[SAMPLE_PORT])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app,
                [
                    "api",
                    "generate",
                    "5",
                    "--country",
                    "DE",
                    "--city",
                    "Berlin",
                    "--state",
                    "Berlin",
                    "--name",
                    "test",
                    "--ttl",
                    "7",
                    "--traffic-limit",
                    "50",
                ],
            )
            assert result.exit_code == 0

    def test_asns_with_all_options(self) -> None:
        """ASNs command with all filter options."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_asns = AsyncMock(return_value=ASNListResponse())
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(
                app,
                [
                    "api",
                    "asns",
                    "--country-id",
                    "1",
                    "--state-id",
                    "10",
                    "--city-id",
                    "100",
                    "--page",
                    "2",
                ],
            )
            assert result.exit_code == 0

    def test_plan_command(self) -> None:
        """Plan command with nested data."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_plan_info = AsyncMock(
                return_value={
                    "success": True,
                    "message": {
                        "plan": "pro",
                        "max_ports": 100,
                        "traffic_left": 500.0,
                    },
                }
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "plan"])
            assert result.exit_code == 0
            assert "pro" in result.output

    def test_info_detailed_output(self) -> None:
        """Info command shows full port details."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_port = AsyncMock(return_value=SAMPLE_PORT)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["info", "42"])
            assert result.exit_code == 0
            assert "1.2.3.4" in result.output
            assert "8080" in result.output
            assert "socks5" in result.output

    def test_countries_empty_response(self) -> None:
        """Countries command with empty response."""
        with (
            patch.dict(os.environ, {"ASOCKS_API_KEY": "k"}),
            patch("asockslib.cli.api_commands.ASocksClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get_countries = AsyncMock(return_value=[])
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = runner.invoke(app, ["api", "countries"])
            assert result.exit_code == 0
            assert "Countries (0)" in result.output

    def test_each_help_flag(self) -> None:
        """Each command supports --help."""
        # Top-level commands
        top_commands = ["balance", "list", "info", "delete", "wizard", "get"]
        for cmd in top_commands:
            result = runner.invoke(app, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} --help failed"
            assert "Usage" in result.output or "Options" in result.output

        # API subcommands
        api_commands = [
            "countries",
            "states",
            "cities",
            "asns",
            "plan",
            "search",
            "generate",
            "archive",
            "unarchive",
            "refresh-ip",
            "rename",
            "traffic",
            "change-credentials",
            "templates",
            "template-create",
            "template-delete",
        ]
        for cmd in api_commands:
            result = runner.invoke(app, ["api", cmd, "--help"])
            assert result.exit_code == 0, f"api {cmd} --help failed"
            assert "Usage" in result.output or "Options" in result.output
