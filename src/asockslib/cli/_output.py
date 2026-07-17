"""Rich console output functions for the CLI.

All Rich table printing and clipboard notification logic is
centralized here, keeping command handlers clean.
"""

from __future__ import annotations

from beartype import beartype
from rich.table import Table

from asockslib._console import console
from asockslib.cli._helpers import copy_to_clipboard


@beartype
def print_proxy_table(
    urls: list[str],
    *,
    title: str = "Proxies",
    url_header: str = "Proxy",
) -> None:
    """Print a proxy table and auto-copy to clipboard."""
    table = Table(title=title)
    table.add_column("#", style="dim")
    table.add_column(url_header, style="green", overflow="fold")
    for i, u in enumerate(urls, 1):
        table.add_row(str(i), u)
    console.print(table)

    plain = "\n".join(urls)
    copied = copy_to_clipboard(plain)

    console.print()
    if copied:
        console.print(f"[green]📋 Copied {len(urls)} proxies to clipboard![/green]")
    else:
        console.print("[dim]── Copy-friendly list ──[/dim]")
        console.print(plain)
        console.print("[dim]────────────────────────[/dim]")


@beartype
def print_copy_result(urls: list[str]) -> None:
    """Copy proxy URLs to clipboard and show result."""
    plain = "\n".join(urls)
    if copy_to_clipboard(plain):
        console.print(f"\n[green]📋 Copied {len(urls)} proxies to clipboard![/green]")
    else:
        console.print("\n[dim]── Copy-friendly list ──[/dim]")
        console.print(plain)
        console.print("[dim]────────────────────────[/dim]")
