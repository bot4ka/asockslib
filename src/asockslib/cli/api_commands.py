"""Raw API sub-commands (``asocks api ...``).

Low-level CLI wrappers around every ASocks API endpoint.
Intended for advanced users and debugging.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from beartype import beartype
from rich.table import Table

from asockslib._console import console
from asockslib.cli._helpers import ExportFormat, format_output, get_api_key, run_async
from asockslib.client import ASocksClient
from asockslib.models import (
    CityInfo,
    CountryInfo,
    CreatePortRequest,
    CreateTemplateRequest,
    StateInfo,
    WhitelistAddRequest,
)


def register_api_commands(api_app: typer.Typer) -> None:
    """Register all raw API sub-commands on the Typer app."""

    @api_app.command()
    @beartype
    def countries() -> None:
        """List countries (GET /v2/proxy/countries)."""

        async def _countries() -> list[CountryInfo]:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.get_countries()

        items = run_async(_countries())
        table = Table(title=f"Countries ({len(items)})")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Code", style="yellow")
        for c in items:
            table.add_row(str(c.id), c.name, c.code)
        console.print(table)

    @api_app.command()
    @beartype
    def states(
        country_id: int = typer.Option(..., "--country-id", "-c", help="Country ID"),
    ) -> None:
        """List states/regions (GET /v2/proxy/states)."""

        async def _states() -> list[StateInfo]:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.get_states(country_id=country_id)

        items = run_async(_states())
        table = Table(title=f"States ({len(items)})")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        for s in items:
            table.add_row(str(s.id), s.name)
        console.print(table)

    @api_app.command()
    @beartype
    def cities(
        country_id: int = typer.Option(..., "--country-id", "-c", help="Country ID"),
        state_id: int | None = typer.Option(None, "--state-id", "-s", help="State ID"),
    ) -> None:
        """List cities (GET /v2/proxy/cities)."""

        async def _cities() -> list[CityInfo]:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.get_cities(country_id=country_id, state_id=state_id)

        items = run_async(_cities())
        table = Table(title=f"Cities ({len(items)})")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        for c in items:
            table.add_row(str(c.id), c.name)
        console.print(table)

    @api_app.command()
    @beartype
    def asns(
        country_id: int | None = typer.Option(None, "--country-id", "-c", help="Country ID"),
        state_id: int | None = typer.Option(None, "--state-id", "-s", help="State ID"),
        city_id: int | None = typer.Option(None, "--city-id", help="City ID"),
        page: int = typer.Option(1, "--page", "-p", help="Page number"),
    ) -> None:
        """List ASN providers (GET /v2/proxy/asn)."""
        from asockslib.models import ASNListResponse

        async def _asns() -> ASNListResponse:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.get_asns(
                    country_id=country_id,
                    state_id=state_id,
                    city_id=city_id,
                    page=page,
                )

        response = run_async(_asns())
        items = response.items
        table = Table(
            title=(
                f"ASNs (page {response.current_page}/{response.last_page}, total {response.total})"
            )
        )
        table.add_column("ASN", style="cyan")
        table.add_column("Name", style="green")
        for a in items:
            table.add_row(str(a.asn), a.name)
        console.print(table)

    @api_app.command()
    @beartype
    def plan() -> None:
        """Show plan info (GET /v2/plan/info)."""

        async def _plan() -> dict[str, Any]:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.get_plan_info()

        data = run_async(_plan())
        msg = data.get("message", data)
        console.print_json(json.dumps(msg, indent=2, default=str))

    @api_app.command()
    @beartype
    def search(
        limit: int = typer.Argument(10, help="Number of proxies"),
        country: str = typer.Option("", "--country", "-c", help="ISO country code"),
    ) -> None:
        """Search proxies without creating ports (POST /v2/proxy/search)."""

        async def _search() -> list[str]:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.search_proxies(country=country, limit=limit)

        proxies = run_async(_search())
        if not proxies:
            console.print("[yellow]No proxies found.[/yellow]")
            raise typer.Exit()
        table = Table(title=f"Available Proxies ({len(proxies)})")
        table.add_column("#", style="dim")
        table.add_column("Proxy (IP:Port)", style="green")
        for i, p in enumerate(proxies, 1):
            table.add_row(str(i), p)
        console.print(table)

    @api_app.command()
    @beartype
    def generate(
        count: int = typer.Argument(1, help="Number of ports"),
        country: str = typer.Option("US", "--country", "-c", help="ISO country code"),
        city: str = typer.Option("", "--city", help="City name"),
        state: str = typer.Option("", "--state", "-s", help="State name"),
        name: str = typer.Option("", "--name", "-n", help="Port name"),
        ttl: int = typer.Option(1, "--ttl", help="TTL in days"),
        traffic_limit: int = typer.Option(10, "--traffic-limit", help="Traffic limit (GB)"),
        type_id: int = typer.Option(
            1, "--type-id", help="Connection type: 1=keep-proxy, 2=keep-conn, 3=rotate"
        ),
        proxy_type_id: int = typer.Option(
            1, "--proxy-type-id", help="Proxy type: 1=residential, 3=mobile, 4=corporate"
        ),
        server_port_type_id: int = typer.Option(
            0, "--server-port-type-id", help="Port type: 0=shared, 1=dedicated"
        ),
        fmt: ExportFormat = typer.Option(  # noqa: B008 — required Typer CLI pattern
            ExportFormat.txt, "--format", "-f", help="Export format"
        ),
        output: str | None = typer.Option(None, "--output", "-o", help="Output file"),
    ) -> None:
        """Create ports directly (POST /v2/proxy/generate)."""

        async def _create() -> list[str]:
            req = CreatePortRequest(
                country_code=country,
                city=city,
                state=state,
                name=name,
                count=count,
                ttl=ttl,
                type_id=type_id,
                proxy_type_id=proxy_type_id,
                server_port_type_id=server_port_type_id,
                traffic_limit=traffic_limit,
            )
            async with ASocksClient(api_key=get_api_key()) as client:
                ports = await client.create_ports(req)
                return [p.proxy_url for p in ports]

        urls = run_async(_create())
        if not urls:
            console.print("[yellow]No ports created.[/yellow]")
            raise typer.Exit()

        content = format_output(urls, fmt)
        if output:
            with open(output, "w") as f:
                f.write(content)
            console.print(f"[green]Saved {len(urls)} proxies to {output}[/green]")
        else:
            console.print(content)

    @api_app.command()
    @beartype
    def archive(
        port_id: int = typer.Argument(..., help="Port ID"),
    ) -> None:
        """Archive port (POST /v2/proxy/archive)."""

        async def _archive() -> bool:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.archive_port(port_id)

        ok = run_async(_archive())
        console.print(f"[green]Port {port_id} archived.[/green]" if ok else "[red]Failed.[/red]")

    @api_app.command()
    @beartype
    def unarchive(
        port_id: int = typer.Argument(..., help="Port ID"),
    ) -> None:
        """Unarchive port (POST /v2/proxy/unarchive)."""

        async def _unarchive() -> bool:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.unarchive_port(port_id)

        ok = run_async(_unarchive())
        console.print(f"[green]Port {port_id} unarchived.[/green]" if ok else "[red]Failed.[/red]")

    @api_app.command(name="refresh-ip")
    @beartype
    def refresh_ip(
        port_id: int = typer.Argument(..., help="Port ID"),
    ) -> None:
        """Refresh port IP (GET /v2/proxy/refresh-ip)."""

        async def _refresh() -> bool:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.refresh_ip(port_id)

        ok = run_async(_refresh())
        console.print(
            f"[green]IP refreshed for port {port_id}.[/green]" if ok else "[red]Failed.[/red]"
        )

    @api_app.command()
    @beartype
    def rename(
        port_id: int = typer.Argument(..., help="Port ID"),
        name: str = typer.Argument(..., help="New name"),
    ) -> None:
        """Rename port (POST /v2/proxy/change-name)."""

        async def _rename() -> bool:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.change_port_name(port_id, name)

        ok = run_async(_rename())
        console.print(f"[green]Renamed to '{name}'.[/green]" if ok else "[red]Failed.[/red]")

    @api_app.command()
    @beartype
    def traffic() -> None:
        """Total spent traffic (GET /v2/proxy/total-spent-traffic)."""

        async def _traffic() -> dict[str, Any]:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.get_total_spent_traffic()

        data = run_async(_traffic())
        total = data.get("total_spent_traffic", "N/A")
        console.print(f"Total spent traffic: [cyan]{total}[/cyan]")

    @api_app.command(name="change-credentials")
    @beartype
    def change_credentials() -> None:
        """Change credentials for all proxies (GET /v2/proxy/change-credentials)."""

        async def _change() -> bool:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.change_credentials()

        ok = run_async(_change())
        console.print("[green]Credentials changed.[/green]" if ok else "[red]Failed.[/red]")

    @api_app.command()
    @beartype
    def templates(
        page: int = typer.Option(1, "--page", "-p", help="Page number"),
    ) -> None:
        """List templates (GET /v2/proxy-template)."""

        async def _templates() -> dict[str, Any]:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.list_templates(page=page)

        data = run_async(_templates())
        console.print_json(json.dumps(data, indent=2, default=str))

    @api_app.command(name="template-create")
    @beartype
    def template_create(
        label: str = typer.Option(..., "--label", "-l", help="Template name"),
        template: str = typer.Option(..., "--template", "-t", help="Template string"),
    ) -> None:
        """Create template (POST /v2/proxy-template/create-template)."""

        async def _create() -> dict[str, Any]:
            async with ASocksClient(api_key=get_api_key()) as client:
                req = CreateTemplateRequest(label=label, template=template)
                return await client.create_template(req)

        data = run_async(_create())
        if data.get("success"):
            console.print("[green]Template created.[/green]")
        console.print_json(json.dumps(data, indent=2, default=str))

    @api_app.command(name="template-delete")
    @beartype
    def template_delete(
        template_id: int = typer.Argument(..., help="Template ID"),
    ) -> None:
        """Delete template (DELETE /v2/proxy-template/delete-template)."""

        async def _delete() -> bool:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.delete_template(template_id)

        ok = run_async(_delete())
        console.print(
            f"[green]Template {template_id} deleted.[/green]" if ok else "[red]Failed.[/red]"
        )

    @api_app.command(name="whitelist-add")
    @beartype
    def whitelist_add(
        ip: str = typer.Argument(..., help="IP address"),
        description: str = typer.Option("", "--desc", "-d", help="Description"),
    ) -> None:
        """Add IP to whitelist (POST /v2/whitelist/add)."""

        async def _add() -> dict[str, Any]:
            async with ASocksClient(api_key=get_api_key()) as client:
                req = WhitelistAddRequest(ip=ip, description=description)
                return await client.add_whitelist_ip(req)

        data = run_async(_add())
        if data.get("success"):
            console.print(f"[green]IP {ip} added to whitelist.[/green]")
        else:
            console.print(f"[red]Failed to add {ip}.[/red]")

    @api_app.command(name="whitelist-remove")
    @beartype
    def whitelist_remove(
        ip: str = typer.Argument(..., help="IP address"),
    ) -> None:
        """Remove IP from whitelist (DELETE /v2/whitelist/delete)."""

        async def _remove() -> bool:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.delete_whitelist_ip(ip)

        ok = run_async(_remove())
        console.print(f"[green]IP {ip} removed.[/green]" if ok else "[red]Failed.[/red]")
