"""Main CLI commands: wizard, get, balance, list, delete, info.

User-facing commands that form the primary CLI experience.
"""

from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any

import typer
from beartype import beartype
from rich.table import Table

from asockslib._console import console
from asockslib.cli._helpers import (
    ExportFormat,
    apply_proxy_template,
    format_output,
    get_api_key,
    run_async,
)
from asockslib.cli._output import print_copy_result, print_proxy_table
from asockslib.client import ASocksClient
from asockslib.geo_picker import GeoPicker
from asockslib.models import CreatePortRequest, PortFilterParams


def register_commands(app: typer.Typer) -> None:
    """Register all main commands on the Typer app."""

    @app.command()
    @beartype
    def wizard() -> None:
        """Interactive wizard — create proxies or find the fastest ones.

        Step-by-step interactive assistant:

        1. Action: create proxies / find best
        2. Proxy type, connection type, port type
        3. Country -> state -> city (fuzzy search)
        4. Count, TTL, name
        5. Export format and output file
        6. Benchmark settings (for find-best mode)

        Example::

            asocks wizard
        """
        picker = GeoPicker()
        params = picker.pick_wizard()

        action = params.get("action", "create")
        country = str(params["country_code"]) if params["country_code"] else "US"
        state = str(params["state"]) if params["state"] else ""
        city = str(params["city"]) if params["city"] else ""
        count = int(params.get("count") or 10)
        ttl = int(params.get("ttl") or 1)
        name = str(params.get("name") or "")
        type_id = int(params.get("type_id") or 1)
        proxy_type_id = int(params.get("proxy_type_id") or 1)
        server_port_type_id = int(params.get("server_port_type_id") or 0)
        traffic_limit = int(params.get("traffic_limit") or 10)
        fmt_str = str(params.get("format") or "txt")
        fmt = ExportFormat(fmt_str) if fmt_str in ("txt", "json", "csv") else ExportFormat.txt
        output = str(params.get("output") or "")
        timeout = float(params.get("timeout") or 15.0)
        concurrency = int(params.get("concurrency") or 50)
        proxy_template = str(
            params.get("proxy_template") or "{protocol}://{login}:{password}@{ip}:{port}"
        )

        action_label = "Find best" if action == "best" else "Create"
        summary = Table(title="📋 Parameters")
        summary.add_column("", style="cyan")
        summary.add_column("", style="green")
        summary.add_row("Action", action_label)
        summary.add_row("Country", country)
        if state:
            summary.add_row("State", state)
        if city:
            summary.add_row("City", city)
        summary.add_row("Count", str(count))
        if action == "best":
            keep = int(params.get("keep") or 10)
            summary.add_row("Keep best", str(keep))
        summary.add_row("TTL", f"{ttl} days")
        summary.add_row("Format", fmt_str)
        if output:
            summary.add_row("Output", output)
        console.print(summary)
        console.print()

        if action == "best":
            _wizard_best_proxies(
                country=country,
                state=state,
                city=city,
                count=count,
                keep=int(params.get("keep") or 10),
                ttl=ttl,
                name=name,
                type_id=type_id,
                proxy_type_id=proxy_type_id,
                server_port_type_id=server_port_type_id,
                traffic_limit=traffic_limit,
                fmt=fmt,
                output=output,
                timeout=timeout,
                concurrency=concurrency,
                proxy_template=proxy_template,
            )
        else:
            _wizard_create_proxies(
                country=country,
                state=state,
                city=city,
                count=count,
                ttl=ttl,
                name=name,
                type_id=type_id,
                proxy_type_id=proxy_type_id,
                server_port_type_id=server_port_type_id,
                traffic_limit=traffic_limit,
                fmt=fmt,
                output=output,
                proxy_template=proxy_template,
            )

    @app.command()
    @beartype
    def get(
        country: str = typer.Argument(..., help="Country code (US, DE, GB, ...)"),
        count: int = typer.Option(10, "--count", "-n", help="Number of proxies"),
        verify: bool = typer.Option(
            False, "--verify", "-v", help="Verify proxies before returning"
        ),
        fmt: ExportFormat = typer.Option(  # noqa: B008 — required Typer CLI pattern
            ExportFormat.txt,
            "--format",
            "-f",
            help="Export format: txt/json/csv",
        ),
        output: str | None = typer.Option(None, "--output", "-o", help="Output file"),
        timeout: float = typer.Option(3.0, "--timeout", "-t", help="Verify timeout (sec)"),
    ) -> None:
        """Get proxies quickly — one command, one country code.

        Examples::

            asocks get US
            asocks get DE -n 20
            asocks get GB -n 5 --verify
            asocks get US -n 100 -f json -o proxies.json
        """
        from asockslib.quick import get_proxies

        async def _get() -> list[str]:
            return await get_proxies(
                country.upper(),
                count=count,
                api_key=get_api_key(),
                verify=verify,
                timeout=timeout,
            )

        with console.status(f"[bold]Getting {count} proxies for {country.upper()}...[/bold]"):
            urls = run_async(_get())

        if not urls:
            console.print("[yellow]No proxies created.[/yellow]")
            raise typer.Exit()

        content = format_output(urls, fmt)
        if output:
            with open(output, "w") as f:
                f.write(content)
            console.print(f"[green]✅ Saved {len(urls)} proxies to {output}[/green]")
        else:
            print_proxy_table(urls, title=f"Proxies ({len(urls)})")

    @app.command()
    @beartype
    def balance() -> None:
        """Show account balance."""

        async def _balance() -> tuple[float, float, float]:
            async with ASocksClient(api_key=get_api_key()) as client:
                bal = await client.get_balance()
                return bal.balance, bal.balance_traffic, bal.all_available_traffic

        b, bt, aat = run_async(_balance())
        table = Table(title="💰 Balance")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Balance (USD)", f"${b:.4f}")
        table.add_row("Traffic Balance", f"{bt}")
        table.add_row("Available Traffic", f"{aat}")
        console.print(table)

    @app.command(name="list")
    @beartype
    def list_ports(
        country: str | None = typer.Option(None, "--country", "-c", help="Filter by country code"),
        status: int | None = typer.Option(
            None, "--status", help="Filter: 0=inactive, 1=active, 2=expired"
        ),
        page: int = typer.Option(1, "--page", "-p", help="Page number"),
        per_page: int = typer.Option(50, "--per-page", help="Items per page"),
    ) -> None:
        """List proxy ports.

        Examples::

            asocks list
            asocks list --country US
            asocks list --status 1
        """

        async def _list() -> tuple[list[Any], int]:
            async with ASocksClient(api_key=get_api_key()) as client:
                filters = PortFilterParams(
                    countryName=country,
                    status=status,
                    page=page,
                    per_page=per_page,
                )
                resp = await client.list_ports(filters)
                return resp.items, resp.total

        items, total = run_async(_list())
        table = Table(title=f"Ports (page {page}, total {total})")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Protocol", style="blue")
        table.add_column("Host:Port", style="green")
        table.add_column("Country", style="yellow")
        table.add_column("Status", style="magenta")
        proxy_urls: list[str] = []
        for p in items:
            status_emoji = (
                "🟢" if str(p.status) == "1" else ("🔴" if str(p.status) == "0" else "⏰")
            )
            table.add_row(
                str(p.id),
                p.name or "-",
                p.protocol,
                f"{p.host}:{p.port}",
                p.country_code or p.country,
                f"{status_emoji} {p.status}",
            )
            proxy_urls.append(p.proxy_url)
        console.print(table)

        if proxy_urls:
            print_copy_result(proxy_urls)

    @app.command()
    @beartype
    def info(
        port_id: int = typer.Argument(..., help="Port ID"),
    ) -> None:
        """Show port details."""

        async def _info() -> dict[str, Any]:
            async with ASocksClient(api_key=get_api_key()) as client:
                p = await client.get_port(port_id)
                return p.model_dump()

        data = run_async(_info())
        console.print_json(json.dumps(data, indent=2, default=str))

    @app.command()
    @beartype
    def delete(
        port_id: int = typer.Argument(..., help="Port ID to delete"),
    ) -> None:
        """Delete (release) a proxy port."""

        async def _delete() -> bool:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await client.delete_port(port_id)

        ok = run_async(_delete())
        if ok:
            console.print(f"[green]✅ Port {port_id} deleted.[/green]")
        else:
            console.print(f"[red]❌ Failed to delete port {port_id}.[/red]")


# ── Wizard sub-commands ───────────────────────────────────────────────────── #


@beartype
def _wizard_create_proxies(
    *,
    country: str,
    state: str,
    city: str,
    count: int,
    ttl: int,
    name: str,
    type_id: int,
    proxy_type_id: int,
    server_port_type_id: int,
    traffic_limit: int,
    fmt: ExportFormat,
    output: str,
    proxy_template: str = "{protocol}://{login}:{password}@{ip}:{port}",
) -> None:
    """Create proxies from wizard parameters."""

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
            return [p.format_with_template(proxy_template) for p in ports]

    with console.status("[bold]Creating proxies...[/bold]"):
        urls = run_async(_create())

    if not urls:
        console.print("[yellow]No ports were created.[/yellow]")
        raise typer.Exit()

    content = format_output(urls, fmt)
    if output:
        with open(output, "w") as f:
            f.write(content)
        console.print(f"[green]✅ Saved {len(urls)} proxies to {output}[/green]")
    else:
        print_proxy_table(urls, title=f"✅ Created {len(urls)} proxies")


@beartype
def _wizard_best_proxies(
    *,
    country: str,
    state: str,
    city: str,
    count: int,
    keep: int,
    ttl: int,
    name: str,
    type_id: int,
    proxy_type_id: int,
    server_port_type_id: int,
    traffic_limit: int,
    fmt: ExportFormat,
    output: str,
    timeout: float,
    concurrency: int,
    proxy_template: str = "{protocol}://{login}:{password}@{ip}:{port}",
) -> None:
    """Find best proxies: create -> benchmark -> keep fastest."""
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    from asockslib.benchmark import FindBestResult, find_best_proxies

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task_id = progress.add_task("Initializing...", total=count)

        def _progress_cb(stage: str, current: int, total_n: int) -> None:
            labels = {
                "creating": "🏗️  Creating proxies",
                "benchmarking": "⚡ Benchmarking",
                "deleting": "🗑️  Deleting slow proxies",
            }
            progress.update(
                task_id,
                description=labels.get(stage, stage),
                completed=current,
                total=total_n,
            )

        async def _find() -> FindBestResult:
            async with ASocksClient(api_key=get_api_key()) as client:
                return await find_best_proxies(
                    client,
                    country_code=country,
                    city=city,
                    state=state,
                    total=count,
                    keep=keep,
                    timeout=timeout,
                    concurrency=concurrency,
                    proxy_type_id=proxy_type_id,
                    server_port_type_id=server_port_type_id,
                    progress_callback=_progress_cb,
                )

        result = run_async(_find())

    # Summary table
    console.print()
    summary = Table(title="🏆 Best Proxies Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Created", str(result.total_created))
    summary.add_row("Tested", str(result.total_tested))
    summary.add_row("Alive", str(result.total_alive))
    summary.add_row("Best kept", str(len(result.best)))
    summary.add_row("Deleted", str(result.total_deleted))
    if result.delete_errors:
        summary.add_row("Delete errors", str(len(result.delete_errors)))
    summary.add_row("Avg latency", f"{result.avg_latency_ms:.0f} ms")
    summary.add_row("Min latency", f"{result.min_latency_ms:.0f} ms")
    summary.add_row("Max latency", f"{result.max_latency_ms:.0f} ms")
    console.print(summary)

    # Best proxies table
    proxy_urls = [
        apply_proxy_template(p.proxy_url, proxy_template, port_id=p.port_id) for p in result.best
    ]
    if result.best:
        console.print()
        proxy_table = Table(title=f"Top {len(result.best)} Proxies")
        proxy_table.add_column("#", style="dim")
        proxy_table.add_column("Latency", style="yellow")
        proxy_table.add_column("IP", style="cyan")
        proxy_table.add_column("Port ID", style="dim")
        proxy_table.add_column("Proxy", style="green", overflow="fold")
        for i, (p, formatted) in enumerate(zip(result.best, proxy_urls, strict=True), 1):
            lat = f"{p.latency_ms:.0f} ms" if p.latency_ms else "N/A"
            proxy_table.add_row(str(i), lat, p.external_ip, str(p.port_id), formatted)
        console.print(proxy_table)

        print_copy_result(proxy_urls)

    # Export
    if fmt == ExportFormat.txt:
        export_data = "\n".join(proxy_urls) + "\n"
    elif fmt == ExportFormat.json:
        export_data = json.dumps(
            [
                {
                    "proxy": apply_proxy_template(p.proxy_url, proxy_template, port_id=p.port_id),
                    "port_id": p.port_id,
                    "latency_ms": p.latency_ms,
                    "external_ip": p.external_ip,
                }
                for p in result.best
            ],
            indent=2,
        )
    else:
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["proxy", "port_id", "latency_ms", "external_ip"])
        for p in result.best:
            writer.writerow(
                [
                    apply_proxy_template(p.proxy_url, proxy_template, port_id=p.port_id),
                    p.port_id,
                    p.latency_ms,
                    p.external_ip,
                ]
            )
        export_data = buf.getvalue()

    if output:
        with open(output, "w") as f:
            f.write(export_data)
        console.print(f"\n[green]✅ Saved to {output}[/green]")
    elif not result.best:
        console.print("[yellow]No proxies survived benchmarking.[/yellow]")
