"""CLI helper utilities.

Contains non-UI functions: clipboard operations, export formatting,
API key resolution, async runner, and proxy template application.
"""

from __future__ import annotations

import asyncio
import csv
import os
import platform
import shutil
import subprocess
from enum import StrEnum
from io import StringIO
from typing import TYPE_CHECKING

import typer
from beartype import beartype

from asockslib._console import console
from asockslib.exceptions import ASocksError

if TYPE_CHECKING:
    from collections.abc import Coroutine


class ExportFormat(StrEnum):
    """Supported export formats."""

    txt = "txt"
    json = "json"
    csv = "csv"


# ── Clipboard ─────────────────────────────────────────────────────────────── #


@beartype
def copy_to_clipboard(text: str) -> bool:
    """Try to copy text to the system clipboard.

    Supports macOS (pbcopy), Linux (xclip/xsel) and Windows (clip).
    """
    system = platform.system()
    try:
        if system == "Darwin" and shutil.which("pbcopy"):
            subprocess.run(["pbcopy"], input=text.encode(), check=True)  # noqa: S603, S607
            return True
        if system == "Linux":
            for cmd in ("xclip", "xsel"):
                if shutil.which(cmd):
                    args = (
                        [cmd, "-selection", "clipboard"]
                        if cmd == "xclip"
                        else [cmd, "--clipboard", "--input"]
                    )
                    subprocess.run(args, input=text.encode(), check=True)  # noqa: S603
                    return True
        if system == "Windows" and shutil.which("clip"):
            subprocess.run(["clip"], input=text.encode(), check=True)  # noqa: S603, S607
            return True
    except (subprocess.SubprocessError, OSError):
        pass
    return False


# ── API key ───────────────────────────────────────────────────────────────── #


@beartype
def get_api_key() -> str:
    """Read API key from ``ASOCKS_API_KEY`` env var."""
    key = os.environ.get("ASOCKS_API_KEY", "")
    if not key:
        console.print("[red]Error:[/red] ASOCKS_API_KEY environment variable not set.")
        raise typer.Exit(code=1)
    return key


# ── Async runner ──────────────────────────────────────────────────────────── #


def run_async[T](coro: Coroutine[object, object, T]) -> T:
    """Run a coroutine synchronously with error handling."""
    try:
        return asyncio.run(coro)
    except ASocksError as exc:
        console.print(f"[red]Error:[/red] {exc.message}")
        raise typer.Exit(code=1) from None


# ── Export formatting ─────────────────────────────────────────────────────── #


@beartype
def format_output(proxies: list[str], fmt: ExportFormat) -> str:
    """Format proxy list for export."""
    import json

    if fmt == ExportFormat.txt:
        return "\n".join(proxies)
    if fmt == ExportFormat.json:
        return json.dumps(proxies, indent=2)
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["proxy_url"])
    for p in proxies:
        writer.writerow([p])
    return buf.getvalue()


# ── Proxy template application ────────────────────────────────────────────── #


@beartype
def apply_proxy_template(
    proxy_url: str,
    template: str,
    port_id: int = 0,
    name: str = "",
) -> str:
    """Apply a template to a standard proxy URL.

    Parses ``protocol://login:password@host:port`` and substitutes
    values into template placeholders.
    """
    protocol = "socks5"
    login = ""
    password = ""
    host = ""
    port_str = "0"
    try:
        proto_rest = proxy_url.split("://", 1)
        protocol = proto_rest[0]
        rest = proto_rest[1] if len(proto_rest) > 1 else proxy_url
        if "@" in rest:
            auth, hostport = rest.rsplit("@", 1)
            parts = auth.split(":", 1)
            login = parts[0]
            password = parts[1] if len(parts) > 1 else ""
        else:
            hostport = rest
        hp = hostport.rsplit(":", 1)
        host = hp[0]
        port_str = hp[1] if len(hp) > 1 else "0"
    except (IndexError, ValueError):
        pass

    refresh = f"https://api.asocks.com/v2/proxy/refresh-ip/{port_id}"
    return (
        template.replace("{protocol}", protocol)
        .replace("{id}", str(port_id))
        .replace("{login}", login)
        .replace("{password}", password)
        .replace("{ip}", host)
        .replace("{port}", port_str)
        .replace("{refresh_link}", refresh)
        .replace("{name}", name)
        .replace("{external_ip}", "")
    )
