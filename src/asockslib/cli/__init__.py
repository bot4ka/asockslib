"""CLI for ASocks Proxy API.

Two-level interface:

- **Main commands** (user-facing):
  ``wizard``, ``get``, ``balance``, ``list``, ``delete``, ``info``
- **Raw API** (``asocks api ...``):
  low-level ASocks API wrappers for advanced users.

Requires ``ASOCKS_API_KEY`` environment variable.

Examples::

    asocks wizard
    asocks get US
    asocks get DE -n 20
    asocks balance
    asocks list
    asocks delete 12345
    asocks api countries
"""

from __future__ import annotations

import typer

from asockslib.cli._helpers import (
    ExportFormat,
    apply_proxy_template,
    format_output,
    get_api_key,
    run_async,
)
from asockslib.cli.api_commands import register_api_commands
from asockslib.cli.commands import register_commands

# ── App setup ─────────────────────────────────────────────────────────────── #

app = typer.Typer(
    name="asocks",
    help="ASocks Proxy — powerful CLI for proxy management.",
    no_args_is_help=True,
)

api_app = typer.Typer(
    name="api",
    help="Raw ASocks API — low-level methods for advanced users.",
    no_args_is_help=True,
)
app.add_typer(api_app, name="api")

# Register commands from submodules
register_commands(app)
register_api_commands(api_app)

# Backward-compatible aliases used in tests
_get_api_key = get_api_key
_run = run_async
_format_output = format_output
_apply_proxy_template = apply_proxy_template
_copy_to_clipboard = None  # Removed; use cli._helpers.copy_to_clipboard

__all__ = [
    "ExportFormat",
    "api_app",
    "app",
]

# ── Entry point ───────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    app()
