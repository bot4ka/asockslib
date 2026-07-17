"""Centralized Rich Console singleton.

Every module that needs to print to the terminal should import
``console`` from here instead of creating its own instance.

Usage::

    from asockslib._console import console

    console.print("[green]OK[/green]")
"""

from __future__ import annotations

from rich.console import Console

console: Console = Console()
"""Module-level singleton :class:`~rich.console.Console` instance."""
