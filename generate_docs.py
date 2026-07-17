"""Auto-generate Astro Starlight documentation (English).

Introspects the ``asockslib`` package, extracts docstrings and writes
MDX files into ``docs/src/content/docs/`` — reference pages are
auto-generated from code; guide and index pages are rendered from
embedded templates.

The script **wipes** the output directories on every run so the docs
always reflect the current state of the codebase.

Usage::

    uv run generate_docs_new.py       # run standalone
    # or hooked into npm scripts:
    npm run dev                       # generates docs, then starts Astro
"""

from __future__ import annotations

import importlib
import inspect
import re
import shutil
import textwrap
from enum import Enum
from pathlib import Path

# Runtime import (not TYPE_CHECKING): @beartype resolves the ModuleType
# annotation on _extract() at call time, so the name must exist at runtime.
from types import ModuleType  # noqa: TC003

from beartype import beartype

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PACKAGE_NAME = "asockslib"
MODULES = [
    "models",
    "client",
    "smart_proxy",
    "proxy_pool",
    "benchmark",
    "exceptions",
    "cli",
    "geo_picker",
]

DOCS_ROOT = Path(__file__).resolve().parent / "docs" / "src" / "content" / "docs"

SIDEBAR_ORDER: dict[str, int] = {
    "client": 1,
    "smart_proxy": 2,
    "proxy_pool": 3,
    "models": 4,
    "exceptions": 5,
    "cli": 6,
    "benchmark": 7,
    "geo_picker": 8,
}

# Per-module metadata for reference pages
MODULE_META: dict[str, dict[str, str]] = {
    "client": {"title": "API Client", "description": "Async HTTP client for ASocks API v2."},
    "smart_proxy": {
        "title": "Smart Proxy Manager",
        "description": "Automatic health checking, rotation, and self-healing.",
    },
    "models": {
        "title": "Data Models",
        "description": "Pydantic models for API requests and responses.",
    },
    "exceptions": {
        "title": "Exceptions",
        "description": "Custom exception classes for the ASocks library.",
    },
    "cli": {
        "title": "CLI Reference",
        "description": "Command-line interface for ASocks Proxy API.",
    },
    "benchmark": {"title": "Benchmark", "description": "Proxy latency benchmarking utilities."},
    "proxy_pool": {
        "title": "ProxyPool Manager",
        "description": "Zero-traffic intelligent proxy pool for massive account management.",
    },
    "geo_picker": {
        "title": "GeoPicker",
        "description": "Interactive geo-data selection with fuzzy search for CLI.",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@beartype
def _clean(doc: str | None) -> str:
    if not doc:
        return ""
    return textwrap.dedent(doc).strip()


@beartype
def _escape_mdx(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}")


@beartype
def _is_public(name: str) -> bool:
    return not name.startswith("_")


@beartype
def _sig(obj: object, name: str) -> str:
    try:
        s = inspect.signature(obj)  # type: ignore[arg-type]
        return f"`{name}{s}`"
    except (ValueError, TypeError):
        return f"`{name}(...)`"


@beartype
def _field_table(cls: type) -> str:
    from pydantic import BaseModel  # noqa: PLC0415

    if not issubclass(cls, BaseModel):
        return ""
    fields = cls.model_fields
    if not fields:
        return ""

    lines = [
        "",
        "| Field | Type | Default | Description |",
        "|-------|------|---------|-------------|",
    ]
    for fname, finfo in fields.items():
        ftype = finfo.annotation
        type_str = re.sub(r"<class '(.+?)'>", r"\1", str(ftype))
        type_str = re.sub(r"<enum '(.+?)'>", r"\1", type_str)
        type_str = type_str.replace("typing.", "").replace("asockslib.models.", "")
        raw_default = finfo.default
        default: str
        if raw_default is None:
            default = "—"
        elif str(raw_default) == "PydanticUndefined":
            default = "*required*"
        elif isinstance(raw_default, Enum):
            default = f'`"{raw_default.value}"`'
        else:
            default = f"`{raw_default!r}`"
        desc = finfo.description or ""
        lines.append(f"| `{fname}` | `{type_str}` | {default} | {desc} |")
    lines.append("")
    return "\n".join(lines)


@beartype
def _enum_table(cls: type) -> str:
    from enum import StrEnum  # noqa: PLC0415

    if not issubclass(cls, StrEnum):
        return ""
    lines = ["", "| Name | Value |", "|------|-------|"]
    for member in cls:
        lines.append(f"| `{member.name}` | `{member.value}` |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Docstring extraction
# ---------------------------------------------------------------------------

_SKIP_PROPS = {
    "model_extra",
    "model_fields_set",
    "model_computed_fields",
    "model_config",
    "model_fields",
}


@beartype
def _extract(module: ModuleType) -> str:
    parts: list[str] = []

    mod_doc = _clean(module.__doc__)
    if mod_doc:
        parts += [mod_doc, ""]

    members = inspect.getmembers(module)
    classes = [
        (n, o)
        for n, o in members
        if inspect.isclass(o) and o.__module__ == module.__name__ and _is_public(n)
    ]
    functions = [
        (n, o)
        for n, o in members
        if inspect.isfunction(o) and o.__module__ == module.__name__ and _is_public(n)
    ]

    for cls_name, cls_obj in sorted(classes, key=lambda x: x[0]):
        parts += [f"## `{cls_name}`", ""]
        cls_doc = _clean(cls_obj.__doc__)
        if cls_doc:
            parts += [cls_doc, ""]

        et = _enum_table(cls_obj)
        if et:
            parts += ["### Values", et]
        ft = _field_table(cls_obj)
        if ft:
            parts += ["### Fields", ft]

        for mname, mobj in sorted(inspect.getmembers(cls_obj), key=lambda x: x[0]):
            if not _is_public(mname) or mname in _SKIP_PROPS:
                continue
            prop = getattr(cls_obj, mname, None)
            if isinstance(prop, property):
                for klass in type.mro(cls_obj):
                    if mname in klass.__dict__:
                        if klass is not cls_obj:
                            break
                        parts += [f"### `{mname}` (property)", ""]
                        pd = _clean(prop.fget.__doc__) if prop.fget else ""
                        if pd:
                            parts += [pd, ""]
                        break
                continue
            if not callable(mobj) or mname.startswith("_"):
                continue
            if hasattr(mobj, "__qualname__") and cls_name not in mobj.__qualname__:
                continue
            parts += [f"### {_sig(mobj, mname)}", ""]
            md = _clean(mobj.__doc__)
            if md:
                parts += [md, ""]

    if functions:
        parts += ["## Functions", ""]
        for fn, fo in sorted(functions, key=lambda x: x[0]):
            parts += [f"### {_sig(fo, fn)}", ""]
            fd = _clean(fo.__doc__)
            if fd:
                parts += [fd, ""]

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Static page templates
# ---------------------------------------------------------------------------

INDEX_EN = """\
---
title: ASocks Python Library
description: Premium Python library and CLI for the ASocks Proxy API.
template: splash
hero:
  tagline: Fully typed async client, smart proxy manager, and powerful CLI — all in one package.
  image:
    file: ../../assets/houston.webp
  actions:
    - text: Quick Start
      link: /guides/quickstart/
      icon: right-arrow
    - text: API Reference
      link: /reference/client/
      icon: external
      variant: minimal
---

import { Card, CardGrid } from "@astrojs/starlight/components";

## Features

<CardGrid stagger>
  <Card title="Async API Client" icon="rocket">
    Fully typed async HTTP client built on `httpx` with automatic retries,
    rate-limit handling, and Pydantic models.
  </Card>
  <Card title="Smart Proxy Manager" icon="random">
    Automatic health-checking, proxy rotation, and self-healing — failed proxies
    are seamlessly replaced.
  </Card>
  <Card title="ProxyPool — Zero Traffic" icon="star">
    Intelligent proxy pool for 10,000+ accounts. Auto-detects dead proxies via API
    (zero traffic waste) and replaces them transparently.
  </Card>
  <Card title="Powerful CLI" icon="laptop">
    Generate, list, and manage proxies from the terminal. Export to `.txt`,
    `.json`, or `.csv`. Interactive wizard for quick setup.
  </Card>
  <Card title="100% Type Safe" icon="approve-check">
    Strict `mypy` and `pyright` compliance with `beartype` runtime checks on
    every public API.
  </Card>
</CardGrid>
"""

QUICKSTART_EN = """\
---
title: Quick Start
description: Install asocks and make your first API call in under 2 minutes.
sidebar:
  order: 1
---

## Installation

```bash
pip install asocks
```

Or with **uv**:

```bash
uv add asocks
```

## Set your API key

```bash
export ASOCKS_API_KEY="sk-your-api-key"
```

## Python — async usage

```python
import asyncio
from asocks import ASocksClient

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        # Check balance
        balance = await client.get_balance()
        print(f"Balance: ${balance.balance}")

        # List existing proxy ports
        ports = await client.list_ports()
        for p in ports.items:
            print(p.proxy_url)

asyncio.run(main())
```

## CLI — quick commands

```bash
# Generate 10 US SOCKS5 proxies
asocks generate 10 --country US --format txt

# Interactive wizard
asocks wizard

# List all your ports
asocks list

# Check account balance
asocks balance

# See all available countries
asocks countries
```

## Next steps

- [Smart Proxy Manager](/guides/smart-proxy/) — automatic rotation & healing
- [CLI Reference](/guides/cli/) — full command details
- [API Reference](/reference/client/) — all client methods
"""

CLI_GUIDE_EN = """\
---
title: CLI Usage
description: Complete guide to the asocks command-line interface.
sidebar:
  order: 2
---

The `asocks` CLI lets you generate, list, and manage proxies directly from your terminal.

## Authentication

Set your API key as an environment variable:

```bash
export ASOCKS_API_KEY="sk-your-api-key"
```

Or pass it directly with `--api-key`:

```bash
asocks balance --api-key sk-your-api-key
```

## Commands

### `wizard` — Interactive Wizard

Step-by-step country → state → city selection via fuzzy search:

```bash
asocks wizard 10
asocks wizard 5 --format json --output proxies.json
```

### `generate`

Create new proxy ports and export them.

```bash
# Generate 100 US proxies → file
asocks generate 100 --country US --format txt --output proxies.txt

# Generate with CSV output
asocks generate 25 --format csv --output proxies.csv
```

**Options:**

| Flag        | Short | Description          | Default    |
| ----------- | ----- | -------------------- | ---------- |
| `--country` | `-c`  | ISO country code     | _(any)_    |
| `--format`  | `-f`  | `txt`, `json`, `csv` | `txt`      |
| `--output`  | `-o`  | Output file path     | _(stdout)_ |

### `list`

List your existing proxy ports.

```bash
asocks list
asocks list --country US
```

### `search`

Search available proxies without creating ports.

```bash
asocks search 20 --country US
asocks search 10
```

### `balance`

Show your current account balance.

```bash
asocks balance
```

### `countries`

List all available proxy countries.

```bash
asocks countries
```

## Export Formats

### TXT (default)

One proxy URL per line:

```
socks5://user:pass@host:10001
socks5://user:pass@host:10002
```

### JSON

Structured array:

```json
[
  {"id": 1001, "host": "proxy.asocks.com", "port": 10001, "protocol": "socks5", "country": "US"}
]
```

### CSV

Tabular format with headers:

```
id,host,port,login,password,protocol,country,url
1001,proxy.asocks.com,10001,user,pass,socks5,US,socks5://user:pass@proxy.asocks.com:10001
```
"""

SMART_PROXY_GUIDE_EN = """\
---
title: Smart Proxy Manager
description: Automatic proxy rotation, health-checking, and self-healing.
sidebar:
  order: 3
---

The `SmartProxy` class wraps `ASocksClient` to provide a high-level proxy pool with **automatic rotation**, **health checking**, and **self-healing**.

## How it works

1. **Initialize** a pool of proxies matching your criteria (country, protocol, type).
2. **Request a proxy** — `SmartProxy` returns the next healthy proxy URL.
3. **Auto-heal** — if a proxy fails, it is automatically replaced. No fatal errors are raised.

## Basic usage

```python
import asyncio
from asocks import ASocksClient, SmartProxy

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        smart = SmartProxy(client, country_code="US")
        await smart.initialize(pool_size=5)

        proxy_url = await smart.get_proxy()
        print(proxy_url)  # socks5://user:pass@host:port

asyncio.run(main())
```

## Pool management

### Get all proxy URLs

```python
urls = await smart.get_all_proxies()
```

### Health-check the entire pool

```python
results = await smart.health_check_all()
# {1001: True, 1002: False, 1003: True}
```

### Refresh unhealthy proxies

```python
replaced = await smart.refresh_pool()
print(f"{replaced} proxies were replaced")
```

## Configuration

| Parameter          | Type           | Default                             | Description                     |
| ------------------ | -------------- | ----------------------------------- | ------------------------------- |
| `client`           | `ASocksClient` | _required_                          | The API client instance         |
| `country_code`     | `str`          | `""`                                | ISO country code filter         |
| `city`             | `str`          | `""`                                | City filter                     |
| `health_check_url` | `str`          | `https://api.ipify.org?format=json` | URL used for health checks      |
| `health_timeout`   | `float`        | `10.0`                              | Health check timeout in seconds |

## Using with httpx

```python
import httpx
from asocks import ASocksClient, SmartProxy

async def scrape():
    async with ASocksClient(api_key="sk-...") as client:
        smart = SmartProxy(client, country="US")
        await smart.initialize(pool_size=3)

        proxy_url = await smart.get_proxy()
        async with httpx.AsyncClient(proxy=proxy_url) as http:
            resp = await http.get("https://example.com")
            print(resp.status_code)
```

## Error handling

```python
from asocks.exceptions import NoAvailableProxyError

try:
    proxy = await smart.get_proxy()
except NoAvailableProxyError:
    print("All proxies failed — check your account or criteria")
```
"""

PROXY_POOL_GUIDE_EN = """\
---
title: ProxyPool — Zero-Traffic Proxy Manager
description: Intelligent proxy pool that manages thousands of accounts without wasting traffic on health checks.
sidebar:
  order: 4
---

import { Aside } from "@astrojs/starlight/components";

`ProxyPool` is the **killer feature** of asockslib — an intelligent proxy management system designed for developers managing **thousands of accounts** who don't want to deal with proxy failures manually.

<Aside type="tip">
Unlike SmartProxy which uses HTTP requests through proxies for health checking (consuming traffic), ProxyPool checks proxy status via the ASocks REST API — **zero traffic wasted**.
</Aside>

## How it works

1. **Initialize** — ProxyPool creates a pool of proxy ports via the ASocks API.
2. **Assign** — Each account gets a stable proxy URL (`STICKY` strategy by default).
3. **Report failure** — When a connection fails, you call `report_failure()`.
4. **Auto-replace** — ProxyPool checks the port status via API (not through the proxy!) and, if dead, automatically creates a replacement with identical parameters.
5. **Transparent** — The account gets a new proxy URL on the next `get_proxy()` call.

## Quick start

```python
import asyncio
from asockslib import ASocksClient, ProxyPool

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        pool = ProxyPool(
            client,
            country_code="US",
            pool_size=50,           # 50 proxy slots
            type_id=1,              # keep-proxy (highest trust)
            proxy_type_id=1,        # residential
            server_port_type_id=1,  # dedicated
            traffic_limit=10,       # 10 GB per port
        )
        await pool.initialize()

        # Get proxy for an account
        url = await pool.get_proxy("account_42")
        print(url)  # socks5://user:pass@proxy.asocks.com:10042

        # On connection failure
        try:
            await do_request(url)
        except ConnectionError:
            await pool.report_failure("account_42")
            url = await pool.get_proxy("account_42")  # new proxy!

        await pool.shutdown()

asyncio.run(main())
```

## Assignment strategies

### STICKY (default)

Each account is assigned to one proxy. The proxy is only replaced when it fails.

```python
pool = ProxyPool(client, strategy=PoolStrategy.STICKY)
```

**Best for:** Account farming, social media automation, any scenario where each account must have a consistent IP.

### ROUND_ROBIN

Each `get_proxy()` call returns the next proxy in the pool.

```python
from asockslib import PoolStrategy

pool = ProxyPool(client, strategy=PoolStrategy.ROUND_ROBIN)
```

**Best for:** Web scraping, data collection — distributes load evenly.

### RANDOM

Each call returns a random alive proxy.

```python
pool = ProxyPool(client, strategy=PoolStrategy.RANDOM)
```

**Best for:** One-off requests, high anonymity needs.

## Failure handling

ProxyPool uses a **threshold-based** approach:

1. Each `report_failure()` increments a counter.
2. When the counter reaches `failure_threshold` (default: 3), the pool checks the port status via API.
3. If the API confirms the port is dead → replacement is created automatically.
4. If the API says the port is alive → the counter is reset (maybe it was a temporary issue).

```python
pool = ProxyPool(
    client,
    failure_threshold=3,  # number of failures before checking
)

# Typical usage pattern
for attempt in range(5):
    url = await pool.get_proxy("account_1")
    try:
        result = await do_request(url)
        break
    except ConnectionError:
        replaced = await pool.report_failure("account_1")
        if replaced:
            print("Proxy was replaced, retrying...")
```

## Bulk operations

```python
# Get proxies for multiple accounts at once
mapping = await pool.get_proxies(["acc1", "acc2", "acc3", "acc4"])
# \\{"acc1": "socks5://...", "acc2": "socks5://...", ...\\}

# Report multiple failures
results = await pool.report_failures(["acc1", "acc3"])
# \\{"acc1": True, "acc3": False\\}  (True = proxy was replaced)
```

## Force replacement

Skip the threshold — immediately replace a proxy:

```python
new_url = await pool.force_replace("account_42")
if new_url:
    print(f"New proxy: \\{new_url\\}")
```

## Pool health monitoring

Check all proxies via the API (zero traffic):

```python
stats = await pool.check_pool_health()
print(f"Alive: \\{stats.alive\\}/\\{stats.total\\}")
print(f"Dead: \\{stats.dead\\}")
print(f"Total replacements: \\{stats.replaced\\}")
print(f"API checks: \\{stats.api_checks\\}")
```

Replace all dead proxies in one call:

```python
replaced = await pool.replace_dead_proxies()
print(f"Replaced \\{replaced\\} proxies")
```

## Background monitoring

Enable automatic periodic checks via the API:

```python
pool = ProxyPool(
    client,
    monitor_interval=300,  # check every 5 minutes
)
await pool.initialize()
# Background task is now running
# ...
await pool.shutdown()  # stops the monitor
```

## Persistence across restarts

The `account_id → port_id` mapping lives in memory. To survive a process
restart (essential when pinning 100,000+ accounts to dedicated proxies),
supply a `ProxyStore` — any object with async `load`, `save`, and `delete`
methods. Bindings are saved on assignment/replacement, removed on release,
and restored during `initialize()`. Store errors are logged, never fatal.

```python
class RedisStore:  # back it with Redis, SQL, a file — your choice
    async def load(self) -> dict[str, int]: ...
    async def save(self, account_id: str, port_id: int) -> None: ...
    async def delete(self, account_id: str) -> None: ...

pool = ProxyPool(client, country_code="US", pool_size=1000, store=RedisStore())
await pool.initialize()  # restores previously persisted bindings
```

<Aside type="note">
Bindings persist the ASocks **port id**, not the URL. After a proxy is
replaced the port id changes, and the store is updated automatically — so a
restart always reconnects each account to its current live proxy.
</Aside>

## Best-by-ping selection (benchmark on init)

By default `initialize()` is zero-traffic. Set `benchmark_on_init=True` to
over-provision, ping every candidate, and keep only the fastest `pool_size`.
Ports the pool created but discarded are deleted; pre-existing ports are kept.

```python
pool = ProxyPool(
    client, country_code="US", pool_size=100,
    benchmark_on_init=True,
    benchmark_oversample=2.0,   # create/test ~200, keep fastest 100
    benchmark_timeout=5.0,
)
await pool.initialize()
```

## Configuration reference

| Parameter              | Type           | Default   | Description                                    |
| ---------------------- | -------------- | --------- | ---------------------------------------------- |
| `client`               | `ASocksClient` | required  | API client instance                            |
| `country_code`         | `str`          | `""`      | ISO country code                               |
| `city`                 | `str`          | `""`      | City filter                                    |
| `state`                | `str`          | `""`      | State filter                                   |
| `pool_size`            | `int`          | `10`      | Number of proxy slots                          |
| `type_id`              | `int`          | `1`       | Connection type (1=keep, 2=keep-conn, 3=rotate)|
| `proxy_type_id`        | `int`          | `1`       | Proxy type (1=residential, 3=mobile, etc.)     |
| `server_port_type_id`  | `int`          | `1`       | Port type (0=shared, 1=dedicated)              |
| `ttl`                  | `int`          | `1`       | Time-to-live in days                           |
| `traffic_limit`        | `int`          | `10`      | Traffic limit in GB                            |
| `strategy`             | `PoolStrategy` | `STICKY`  | Assignment strategy                            |
| `failure_threshold`    | `int`          | `3`       | Failures before API check                      |
| `monitor_interval`     | `float`        | `0`       | Background check interval (0=disabled)         |
| `store`                | `ProxyStore?`  | `None`    | Persist bindings across restarts     |
| `benchmark_on_init`    | `bool`         | `False`   | Ping candidates on init, keep fastest|
| `benchmark_oversample` | `float`        | `2.0`     | Candidate multiplier when benchmarking|
| `benchmark_timeout`    | `float`        | `5.0`     | Per-proxy ping timeout (benchmark)   |

## SmartProxy vs ProxyPool

| Feature                | SmartProxy          | ProxyPool                      |
| ---------------------- | ------------------- | ------------------------------ |
| Health checking        | HTTP through proxy  | ASocks API (zero traffic)      |
| Traffic consumption    | High                | Zero for health checks         |
| Account mapping        | No                  | Yes (STICKY + persistence)     |
| Scale                  | 5-20 proxies        | 100,000+ accounts              |
| Failure detection      | Proactive (polling) | Reactive (on report_failure)   |
| Use case               | Simple rotation     | Mass account management        |
"""

CONCEPTS_EN = """\
---
title: Proxy Concepts
description: Understanding proxies, ports, connection types, and proxy types — a beginner-friendly guide.
sidebar:
  order: 0
---

import { Aside, Card, CardGrid } from "@astrojs/starlight/components";

This guide explains the fundamental concepts you need to understand before working with proxies and the ASocks API.

## What is a proxy?

A **proxy server** is a computer that acts as an intermediary between your device and the internet. When you use a proxy, your web requests go through the proxy server first, which then forwards them to the target website. The website sees the proxy's IP address instead of yours.

**Why use proxies?**

- **Anonymity** — hide your real IP address
- **Geo-targeting** — access content from different countries
- **Web scraping** — avoid IP bans and rate limiting
- **Account management** — each account gets a unique IP

## What is a port?

In the context of ASocks, a **port** is your personal proxy connection endpoint. When you create a port, ASocks allocates:

- A **host** address (e.g. `proxy.asocks.com`)
- A **port number** (e.g. `10001`)
- **Login** and **password** for authentication

Together they form a proxy URL: `socks5://login:password@proxy.asocks.com:10001`

<Aside type="note">
One port = one proxy connection. If you need 100 proxies for 100 accounts, you create 100 ports.
</Aside>

## Proxy types

ASocks offers different types of proxies based on the source of IP addresses:

<CardGrid>
  <Card title="Residential" icon="home">
    IP addresses from real home internet connections (ISPs). Highest trust level — websites see them as regular users. Best for account management and social media.
  </Card>
  <Card title="Mobile" icon="phone">
    IP addresses from mobile operators (4G/5G). Very high trust — mobile IPs are shared among many users naturally. Great for social media automation.
  </Card>
  <Card title="Corporate" icon="building">
    IP addresses from corporate networks. Medium trust level. Suitable for business applications and B2B scenarios.
  </Card>
</CardGrid>

| proxy_type_id | Name        | Trust Level | Best For                     |
| ------------- | ----------- | ----------- | ---------------------------- |
| 1             | Residential | Highest     | Social media, account farming|
| 2             | All         | Mixed       | General use                  |
| 3             | Mobile      | Very High   | Social media, high anonymity |
| 4             | Corporate   | Medium      | Business, B2B                |

## Connection types

The **connection type** determines how your proxy handles IP rotation:

### Keep Proxy (type_id=1) — Highest Trust

You get a **fixed proxy** that maintains the same IP for the entire lifetime of the port. The IP never changes unless you explicitly refresh it.

**Use when:** You need a stable IP for an account (e.g., one proxy per social media account).

### Keep Connection (type_id=2) — High Trust

The proxy IP may change between connections, but ASocks selects a new IP from the **same subnet or ASN** — so the target website sees a "similar" IP.

**Use when:** You need reasonable IP consistency but can tolerate occasional changes.

### Rotate Connection (type_id=3) — Maximum Anonymity

A **new IP** is assigned for every connection. Maximum anonymity but lowest trust.

**Use when:** Web scraping, data collection — each request from a different IP.

| type_id | Name              | IP Behavior           | Trust   | Best For          |
| ------- | ----------------- | --------------------- | ------- | ----------------- |
| 1       | Keep Proxy        | Fixed IP              | Highest | Account farming   |
| 2       | Keep Connection   | Same subnet/ASN       | High    | Browsing, general |
| 3       | Rotate Connection | New IP per connection  | Low     | Scraping          |

## Server port types

### Shared (server_port_type_id=0)

A **free** port that shares server resources with other users. No traffic limit configuration needed.

**Best for:** Testing, low-volume use, getting started.

### Dedicated (server_port_type_id=1)

A **paid** port with dedicated resources and a configurable **traffic limit** (in GB). You pay for the traffic you allocate.

**Best for:** Production use, high-volume traffic, guaranteed performance.

<Aside type="caution">
Dedicated ports require a `traffic_limit` parameter (minimum 1 GB). This is the amount of traffic you purchase for this port.
</Aside>

| server_port_type_id | Name      | Cost | Traffic Limit | Best For     |
| ------------------- | --------- | ---- | ------------- | ------------ |
| 0                   | Shared    | Free | N/A           | Testing      |
| 1                   | Dedicated | Paid | Required (GB) | Production   |

## ASN (Autonomous System Number)

An **ASN** identifies a specific internet provider. For example:

- AS13335 — Cloudflare
- AS15169 — Google
- AS32934 — Facebook

When creating a proxy, you can optionally specify an ASN to get an IP from a specific provider. This is useful for:

- Getting IPs that look like they belong to a particular ISP
- Ensuring IP consistency for "Keep Connection" mode

## Putting it all together

When you create a proxy port, you choose:

1. **Country** (and optionally state, city) — *where* the proxy is located
2. **Connection type** — *how* the IP behaves
3. **Proxy type** — *what kind* of IP (residential, mobile, corporate)
4. **Server port type** — *shared* (free) or *dedicated* (paid)
5. **Traffic limit** — how much traffic (only for dedicated)
6. **TTL** — how long the port lives (in days)

```python
from asockslib import ASocksClient, CreatePortRequest

async with ASocksClient(api_key="sk-...") as client:
    req = CreatePortRequest(
        country_code="US",          # United States
        city="New York",            # New York City
        type_id=1,                  # Keep Proxy (fixed IP)
        proxy_type_id=1,            # Residential
        server_port_type_id=1,      # Dedicated
        traffic_limit=10,           # 10 GB
        ttl=30,                     # 30 days
        count=5,                    # create 5 ports
    )
    ports = await client.create_ports(req)
    for p in ports:
        print(p.proxy_url)
```

## Next steps

- [Quick Start](/guides/quickstart/) — install and make your first call
- [ProxyPool Guide](/guides/proxy-pool/) — automatic proxy management for thousands of accounts
- [Smart Proxy Guide](/guides/smart-proxy/) — health checking and rotation
"""

TEMPLATES_EN = """\
---
title: Proxy Templates
description: Customize proxy output format using templates with placeholders.
sidebar:
  order: 6
---

import { Aside, Code, Tabs, TabItem } from '@astrojs/starlight/components';

Proxy templates let you control **how proxy credentials are formatted** —
whether you need a simple URL, an `ip:port:login:pass` string, or a
custom format for a tool like AdsPower, Dolphin Anty, or GoLogin.

## What is a proxy template?

A **template** is a string with placeholders that get replaced with actual
proxy data when you call `format_with_template()` on a `PortInfo` object.

### Available placeholders

| Placeholder | Description |
|------------|-------------|
| `\\{protocol\\}` | Proxy protocol (`socks5`, `http`, …) |
| `\\{ip\\}` | Proxy host address |
| `\\{port\\}` | Proxy port number |
| `\\{login\\}` | Authentication login |
| `\\{password\\}` | Authentication password |
| `\\{id\\}` | Port ID |
| `\\{name\\}` | Port name |
| `\\{external_ip\\}` | External IP address |
| `\\{refresh_link\\}` | Refresh IP link |

## Built-in templates

The library ships with **18 ready-to-use templates** accessible through
the interactive wizard or the `GeoPicker`:

| # | Format | Example |
|---|--------|---------|
| 1 | Standard URL | `socks5://user:pass@1.2.3.4:8080` |
| 2 | HTTP URL | `http://user:pass@1.2.3.4:8080` |
| 3 | SOCKS5 URL | `socks5://user:pass@1.2.3.4:8080` |
| 4 | ip:port:login:password | `1.2.3.4:8080:user:pass` |
| 5 | protocol://ip:port:login:password | `socks5://1.2.3.4:8080:user:pass` |
| 6 | URL with refresh link | `socks5://user:pass@host:port[refresh_url]` |
| 7 | Full URL with name | `socks5://user:pass@host:port:name[refresh_url]` |

## Usage in Python

```python
from asockslib import ASocksClient

async with ASocksClient(api_key="sk-...") as client:
    ports = await client.list_ports()
    for port in ports.items:
        # Standard URL
        print(port.proxy_url)

        # Custom format
        print(port.format_with_template("\\{ip\\}:\\{port\\}:\\{login\\}:\\{password\\}"))

        # With protocol prefix
        print(port.format_with_template("\\{protocol\\}://\\{login\\}:\\{password\\}@\\{ip\\}:\\{port\\}"))
```

## Usage in CLI

### Interactive wizard

```bash
# The wizard prompts you to select a template
asocks wizard
```

### Direct command

```bash
# Default format (standard URL)
asocks get --country US --count 5

# Custom template
asocks get --country US --count 5 --proxy-template "\\{ip\\}:\\{port\\}:\\{login\\}:\\{password\\}"

# Export with template
asocks get --country US --count 10 --proxy-template "\\{ip\\}:\\{port\\}:\\{login\\}:\\{password\\}" --output proxies.txt
```

## Server-side templates (API)

You can also create and manage templates on the ASocks server:

```python
from asockslib import ASocksClient, CreateTemplateRequest

async with ASocksClient(api_key="sk-...") as client:
    # Create a template
    req = CreateTemplateRequest(
        label="My Custom Format",
        template="socks5://\\{login\\}:\\{password\\}@\\{ip\\}:\\{port\\}",
    )
    result = await client.create_template(req)

    # List templates
    data = await client.list_templates()

    # Delete template
    await client.delete_template(template_id=123)
```

## Next steps

- [Quick Start](/guides/quickstart/) — installation and first call
- [CLI Usage](/guides/cli/) — all CLI commands
- [API Client Reference](/reference/client/) — full client API
"""

WHITELIST_EN = """\
---
title: IP Whitelist
description: Authenticate to proxies by IP address instead of login/password.
sidebar:
  order: 7
---

import { Aside, Code } from '@astrojs/starlight/components';

The **IP Whitelist** feature allows you to authenticate to ASocks proxies
using your IP address instead of username/password. This is useful when
your tool or framework doesn't support proxy authentication.

## How it works

1. You add your server/machine IP to the whitelist via API or CLI
2. ASocks recognizes your IP and grants access without credentials
3. You connect to proxies without `login:password` in the URL

<Aside type="caution">
Only add IPs you control. Anyone with a whitelisted IP can use your proxies.
</Aside>

## Usage in Python

```python
from asockslib import ASocksClient, WhitelistAddRequest

async with ASocksClient(api_key="sk-...") as client:
    # Add IP to whitelist
    req = WhitelistAddRequest(ip="203.0.113.42", description="My server")
    result = await client.add_whitelist_ip(req)
    print(result)

    # Delete IP from whitelist
    await client.delete_whitelist_ip("203.0.113.42")
```

## Usage in CLI

```bash
# Add your current IP to whitelist
asocks api whitelist-add --ip 203.0.113.42 --description "My server"

# Remove IP from whitelist
asocks api whitelist-delete --ip 203.0.113.42
```

## When to use whitelist

| Scenario | Use whitelist? |
|----------|---------------|
| Tools without proxy auth support | Yes |
| Static server with fixed IP | Yes |
| Dynamic/home IP | No (use login/password) |
| Shared hosting | No (IP may change) |

## Next steps

- [Quick Start](/guides/quickstart/) — installation and first call
- [Proxy Templates](/guides/templates/) — customize proxy output format
- [Smart Proxy](/guides/smart-proxy/) — auto-rotation and health checking
"""

EXAMPLES_EN = """\
---
title: Usage Examples
description: Copy-paste examples — one-liner, client, SmartProxy, ProxyPool, persistence, failover, error handling.
sidebar:
  order: 2
---

Practical, copy-paste examples for every layer of the library.

## Install & authenticate

```bash
pip install asockslib          # or: uv add asockslib
export ASOCKS_API_KEY="sk-your-api-key"
```

## 1. One-liner — just give me proxies

```python
import asyncio
from asockslib import get_proxies, get_proxies_sync

# async
urls = asyncio.run(get_proxies("US", count=10))

# sync (scripts / notebooks)
urls = get_proxies_sync("US", count=5, verify=True)  # verify=True pings & keeps alive
print(urls[0])  # socks5://user:pass@host:port
```

## 2. Full API client

```python
import asyncio
from asockslib import ASocksClient, CreatePortRequest, PortFilterParams

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        balance = await client.get_balance()
        print(f"Balance: ${balance.balance:.2f}")

        ports = await client.create_ports(
            CreatePortRequest(country_code="US", city="New York", count=5)
        )
        for p in ports:
            print(p.proxy_url)

        existing = await client.list_ports(PortFilterParams(countryName="US"))
        print(f"{existing.total} ports total")

asyncio.run(main())
```

## 3. Use a proxy with httpx

```python
import httpx
from asockslib import get_proxies

urls = await get_proxies("DE", count=1)
async with httpx.AsyncClient(proxy=urls[0]) as http:
    resp = await http.get("https://api.ipify.org?format=json")
    print(resp.json())  # IP seen through the proxy
```

## 4. SmartProxy — auto-rotation & self-healing

```python
from asockslib import ASocksClient, SmartProxy

async with ASocksClient(api_key="sk-...") as client:
    smart = SmartProxy(client, country_code="US")
    await smart.initialize(pool_size=5)

    url = await smart.get_proxy()   # health-checked; dead proxies auto-replaced
```

## 5. ProxyPool — 100,000+ accounts, sticky + failover + geo

```python
from asockslib import ASocksClient, ProxyPool, PoolStrategy

async with ASocksClient(api_key="sk-...") as client:
    pool = ProxyPool(
        client,
        country_code="US", city="New York",   # geo-targeting: country + city
        pool_size=500,
        strategy=PoolStrategy.STICKY,          # each account pinned to its own proxy
    )
    await pool.initialize()

    url = await pool.get_proxy("account_42")   # stable per-account assignment
    try:
        ...  # use url
    except ConnectionError:
        await pool.report_failure("account_42")     # checks port via API (zero traffic)
        url = await pool.get_proxy("account_42")     # same account, new same-geo proxy
    await pool.shutdown()
```

## 6. Persistence across restarts

```python
class RedisStore:  # back it with Redis / SQL / a file — your choice
    async def load(self) -> dict[str, int]: ...
    async def save(self, account_id: str, port_id: int) -> None: ...
    async def delete(self, account_id: str) -> None: ...

pool = ProxyPool(client, country_code="US", pool_size=1000, store=RedisStore())
await pool.initialize()   # restores account -> port bindings from the store
```

## 7. Ping-ranked pool (benchmark on init)

```python
pool = ProxyPool(
    client, country_code="US", pool_size=100,
    benchmark_on_init=True, benchmark_oversample=2.0,  # test ~200, keep fastest 100
)
await pool.initialize()
```

## 8. Configurable retries & typed errors

```python
from asockslib import ASocksClient, APIConnectionError, RateLimitError, ASocksError

client = ASocksClient(
    api_key="sk-...",
    max_retries=5,          # retries 429 / 5xx / network with exponential back-off
    retry_backoff_base=1.0,
    retry_backoff_max=30.0,
)
try:
    await client.get_balance()
except APIConnectionError:   # network unreachable after all retries
    ...
except RateLimitError:       # 429 after all retries
    ...
except ASocksError as e:     # any library error — has .status_code / .message
    print(e.status_code, e.message)
```

## 9. Benchmark & pick the fastest

```python
from asockslib import ASocksClient, find_best_proxies

async with ASocksClient(api_key="sk-...") as client:
    result = await find_best_proxies(client, country_code="US", total=100, keep=10)
    print(result.best[0].proxy_url, result.best[0].latency_ms, "ms")
```
"""

EXAMPLES_RU = """\
---
title: Примеры использования
description: Готовые примеры — one-liner, клиент, SmartProxy, ProxyPool, персистентность, отказоустойчивость, обработка ошибок.
sidebar:
  order: 2
---

Практические примеры для каждого уровня библиотеки — копируй и запускай.

## Установка и ключ

```bash
pip install asockslib          # или: uv add asockslib
export ASOCKS_API_KEY="sk-ваш-ключ"
```

## 1. One-liner — просто дай прокси

```python
import asyncio
from asockslib import get_proxies, get_proxies_sync

# async
urls = asyncio.run(get_proxies("US", count=10))

# sync (скрипты / notebooks)
urls = get_proxies_sync("US", count=5, verify=True)  # verify=True пингует и оставляет живые
print(urls[0])  # socks5://user:pass@host:port
```

## 2. Полный API-клиент

```python
import asyncio
from asockslib import ASocksClient, CreatePortRequest, PortFilterParams

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        balance = await client.get_balance()
        print(f"Баланс: ${balance.balance:.2f}")

        ports = await client.create_ports(
            CreatePortRequest(country_code="US", city="New York", count=5)
        )
        for p in ports:
            print(p.proxy_url)

        existing = await client.list_ports(PortFilterParams(countryName="US"))
        print(f"всего портов: {existing.total}")

asyncio.run(main())
```

## 3. Прокси с httpx

```python
import httpx
from asockslib import get_proxies

urls = await get_proxies("DE", count=1)
async with httpx.AsyncClient(proxy=urls[0]) as http:
    resp = await http.get("https://api.ipify.org?format=json")
    print(resp.json())  # IP, который видно через прокси
```

## 4. SmartProxy — авто-ротация и самовосстановление

```python
from asockslib import ASocksClient, SmartProxy

async with ASocksClient(api_key="sk-...") as client:
    smart = SmartProxy(client, country_code="US")
    await smart.initialize(pool_size=5)

    url = await smart.get_proxy()   # проверка здоровья; мёртвые прокси меняются сами
```

## 5. ProxyPool — 100 000+ аккаунтов, sticky + отказоустойчивость + гео

```python
from asockslib import ASocksClient, ProxyPool, PoolStrategy

async with ASocksClient(api_key="sk-...") as client:
    pool = ProxyPool(
        client,
        country_code="US", city="New York",   # гео-таргетинг: страна + город
        pool_size=500,
        strategy=PoolStrategy.STICKY,          # каждый аккаунт закреплён за своим прокси
    )
    await pool.initialize()

    url = await pool.get_proxy("account_42")   # стабильная привязка на аккаунт
    try:
        ...  # используем url
    except ConnectionError:
        await pool.report_failure("account_42")     # проверка порта через API (без трафика)
        url = await pool.get_proxy("account_42")     # тот же аккаунт, новый прокси того же гео
    await pool.shutdown()
```

## 6. Персистентность между перезапусками

```python
class RedisStore:  # храни в Redis / SQL / файле — на твой выбор
    async def load(self) -> dict[str, int]: ...
    async def save(self, account_id: str, port_id: int) -> None: ...
    async def delete(self, account_id: str) -> None: ...

pool = ProxyPool(client, country_code="US", pool_size=1000, store=RedisStore())
await pool.initialize()   # восстанавливает привязки аккаунт -> порт из хранилища
```

## 7. Пул по пингу (benchmark on init)

```python
pool = ProxyPool(
    client, country_code="US", pool_size=100,
    benchmark_on_init=True, benchmark_oversample=2.0,  # тестируем ~200, оставляем 100 быстрейших
)
await pool.initialize()
```

## 8. Настраиваемые ретраи и типизированные ошибки

```python
from asockslib import ASocksClient, APIConnectionError, RateLimitError, ASocksError

client = ASocksClient(
    api_key="sk-...",
    max_retries=5,          # ретраит 429 / 5xx / сеть с экспоненциальной задержкой
    retry_backoff_base=1.0,
    retry_backoff_max=30.0,
)
try:
    await client.get_balance()
except APIConnectionError:   # сеть недоступна после всех попыток
    ...
except RateLimitError:       # 429 после всех попыток
    ...
except ASocksError as e:     # любая ошибка библиотеки — есть .status_code / .message
    print(e.status_code, e.message)
```

## 9. Бенчмарк и выбор самых быстрых

```python
from asockslib import ASocksClient, find_best_proxies

async with ASocksClient(api_key="sk-...") as client:
    result = await find_best_proxies(client, country_code="US", total=100, keep=10)
    print(result.best[0].proxy_url, result.best[0].latency_ms, "мс")
```
"""

INDEX_RU = """\
---
title: ASocks Python Library
description: Премиум Python-библиотека и CLI для ASocks Proxy API.
template: splash
hero:
  tagline: Полностью типизированный async-клиент, умный менеджер прокси и мощный CLI — в одном пакете.
  image:
    file: ../../../assets/houston.webp
  actions:
    - text: Быстрый старт
      link: /asockslib/ru/guides/quickstart/
      icon: right-arrow
    - text: Примеры
      link: /asockslib/ru/guides/examples/
      icon: external
      variant: minimal
---

import { Card, CardGrid } from "@astrojs/starlight/components";

## Возможности

<CardGrid stagger>
  <Card title="Async API-клиент" icon="rocket">
    Типизированный async HTTP-клиент на `httpx` с настраиваемыми ретраями,
    обработкой rate-limit и моделями Pydantic.
  </Card>
  <Card title="Smart Proxy" icon="random">
    Авто-проверка здоровья, ротация и самовосстановление — упавшие прокси
    заменяются прозрачно.
  </Card>
  <Card title="ProxyPool — без трафика" icon="star">
    Умный пул для 100 000+ аккаунтов. Определяет мёртвые прокси через API
    (без траты трафика) и меняет их. Персистентность привязок и выбор по пингу.
  </Card>
  <Card title="Мощный CLI" icon="laptop">
    Генерация, список и управление прокси из терминала. Экспорт в `.txt`,
    `.json`, `.csv`. Интерактивный мастер.
  </Card>
</CardGrid>
"""

QUICKSTART_RU = """\
---
title: Быстрый старт
description: Установи asockslib и сделай первый вызов API меньше чем за 2 минуты.
sidebar:
  order: 1
---

## Установка

```bash
pip install asockslib
```

Или через **uv**:

```bash
uv add asockslib
```

## Задай API-ключ

```bash
export ASOCKS_API_KEY="sk-ваш-ключ"
```

## Python — async

```python
import asyncio
from asockslib import ASocksClient

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        balance = await client.get_balance()
        print(f"Баланс: ${balance.balance}")

        ports = await client.list_ports()
        for p in ports.items:
            print(p.proxy_url)

asyncio.run(main())
```

## CLI — быстрые команды

```bash
asocks get US -n 10        # 10 прокси для US
asocks wizard              # интерактивный мастер
asocks list                # список твоих портов
asocks balance             # баланс
```

## Дальше

- [Примеры использования](/asockslib/ru/guides/examples/) — готовые сниппеты
- [Smart Proxy](/asockslib/ru/guides/smart-proxy/) — авто-ротация и хилинг
- [Proxy Pool](/asockslib/ru/guides/proxy-pool/) — тысячи аккаунтов
"""

SMART_PROXY_GUIDE_RU = """\
---
title: Smart Proxy Manager
description: Автоматическая ротация, проверка здоровья и самовосстановление прокси.
sidebar:
  order: 3
---

Класс `SmartProxy` оборачивает `ASocksClient` и даёт высокоуровневый пул с
**авто-ротацией**, **проверкой здоровья** и **самовосстановлением**.

## Как работает

1. **Инициализация** пула прокси по критериям (страна, тип).
2. **Запрос прокси** — `SmartProxy` возвращает следующий здоровый URL.
3. **Самохилинг** — упавший прокси автоматически заменяется, без фатальных ошибок.

## Базовое использование

```python
import asyncio
from asockslib import ASocksClient, SmartProxy

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        smart = SmartProxy(client, country_code="US")
        await smart.initialize(pool_size=5)

        url = await smart.get_proxy()
        print(url)  # socks5://user:pass@host:port

asyncio.run(main())
```

## Управление пулом

```python
urls = await smart.get_all_proxies()      # все URL пула
results = await smart.health_check_all()  # {1001: True, 1002: False}
replaced = await smart.refresh_pool()     # заменить нездоровые
```

## Обработка ошибок

```python
from asockslib import NoAvailableProxyError

try:
    proxy = await smart.get_proxy()
except NoAvailableProxyError:
    print("Все прокси упали — проверь аккаунт или критерии")
```

## SmartProxy или ProxyPool?

| Свойство            | SmartProxy         | ProxyPool                    |
| ------------------- | ------------------ | ---------------------------- |
| Проверка здоровья   | HTTP через прокси  | ASocks API (без трафика)     |
| Расход трафика      | Высокий            | Нулевой на проверки          |
| Привязка аккаунтов  | Нет                | Да (STICKY + персистентность)|
| Масштаб             | 5–20 прокси        | 100 000+ аккаунтов           |
| Сценарий            | Простая ротация    | Массовые аккаунты            |
"""

PROXY_POOL_GUIDE_RU = """\
---
title: ProxyPool — пул прокси без трафика
description: Умный пул прокси для тысяч аккаунтов без траты трафика на проверки.
sidebar:
  order: 4
---

`ProxyPool` — ключевая фича asockslib: умный менеджер прокси для разработчиков,
управляющих **тысячами аккаунтов**, которым не нужно вручную возиться со сбоями.

В отличие от SmartProxy (проверяет здоровье HTTP-запросами через прокси и тратит
трафик), ProxyPool проверяет статус порта через REST API ASocks — **без трафика**.

## Как работает

1. **Инициализация** — пул создаёт порты через API ASocks.
2. **Привязка** — каждый аккаунт получает стабильный URL (стратегия `STICKY`).
3. **Сообщение о сбое** — при ошибке вызываешь `report_failure()`.
4. **Авто-замена** — пул проверяет статус порта через API (не через прокси!) и,
   если порт мёртв, создаёт замену с теми же параметрами.
5. **Прозрачно** — аккаунт получает новый URL на следующем `get_proxy()`.

## Быстрый старт

```python
import asyncio
from asockslib import ASocksClient, ProxyPool, PoolStrategy

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        pool = ProxyPool(
            client,
            country_code="US", city="New York",   # гео: страна + город
            pool_size=50,
            strategy=PoolStrategy.STICKY,
        )
        await pool.initialize()

        url = await pool.get_proxy("account_42")
        try:
            ...  # используем url
        except ConnectionError:
            await pool.report_failure("account_42")
            url = await pool.get_proxy("account_42")  # новый прокси того же гео

        await pool.shutdown()

asyncio.run(main())
```

## Стратегии привязки

- **STICKY** (по умолчанию) — аккаунт закреплён за одним прокси; замена только при сбое.
  Для аккаунт-фарминга и соцсетей, где нужен стабильный IP.
- **ROUND_ROBIN** — каждый вызов возвращает следующий прокси. Для скрапинга.
- **RANDOM** — случайный живой прокси. Для разовых запросов.

```python
from asockslib import PoolStrategy
pool = ProxyPool(client, strategy=PoolStrategy.ROUND_ROBIN)
```

## Обработка сбоев

Пороговый подход: каждый `report_failure()` увеличивает счётчик; при достижении
`failure_threshold` (по умолчанию 3) пул проверяет порт через API. Если мёртв —
замена; если жив — счётчик сбрасывается.

```python
for attempt in range(5):
    url = await pool.get_proxy("account_1")
    try:
        result = await do_request(url)
        break
    except ConnectionError:
        replaced = await pool.report_failure("account_1")
```

## Массовые операции

```python
mapping = await pool.get_proxies(["acc1", "acc2", "acc3"])
results = await pool.report_failures(["acc1", "acc3"])
new_url = await pool.force_replace("account_42")  # заменить немедленно
```

## Персистентность между перезапусками

Привязка `account_id → port_id` хранится в памяти. Чтобы пережить перезапуск
процесса (важно при 100 000+ аккаунтов на выделенных прокси), передай `ProxyStore`
— объект с async-методами `load`, `save`, `delete`. Привязки сохраняются при
назначении/замене, удаляются при освобождении и восстанавливаются в `initialize()`.

```python
class RedisStore:
    async def load(self) -> dict[str, int]: ...
    async def save(self, account_id: str, port_id: int) -> None: ...
    async def delete(self, account_id: str) -> None: ...

pool = ProxyPool(client, country_code="US", pool_size=1000, store=RedisStore())
await pool.initialize()  # восстанавливает ранее сохранённые привязки
```

## Выбор по пингу (benchmark on init)

По умолчанию `initialize()` не тратит трафик. С `benchmark_on_init=True` пул
создаёт с запасом, пингует всех кандидатов и оставляет самых быстрых `pool_size`.
Созданные, но отброшенные порты удаляются; существующие порты не трогаются.

```python
pool = ProxyPool(
    client, country_code="US", pool_size=100,
    benchmark_on_init=True, benchmark_oversample=2.0,
)
await pool.initialize()
```

## Фоновый мониторинг

```python
pool = ProxyPool(client, monitor_interval=300)  # проверка каждые 5 минут
await pool.initialize()
await pool.shutdown()  # останавливает монитор
```

## Справочник параметров

| Параметр               | Тип            | По умолч. | Описание                          |
| ---------------------- | -------------- | --------- | --------------------------------- |
| `client`               | `ASocksClient` | required  | Экземпляр клиента API             |
| `country_code`         | `str`          | `""`      | ISO-код страны                    |
| `city` / `state`       | `str`          | `""`      | Фильтр по городу / региону         |
| `pool_size`            | `int`          | `10`      | Число слотов                      |
| `strategy`             | `PoolStrategy` | `STICKY`  | Стратегия привязки                |
| `failure_threshold`    | `int`          | `3`       | Сбоев до проверки через API       |
| `monitor_interval`     | `float`        | `0`       | Интервал фонового монитора (0=off)|
| `store`                | `ProxyStore?`  | `None`    | Персистентность привязок          |
| `benchmark_on_init`    | `bool`         | `False`   | Пинг кандидатов, оставить быстрых |
"""

CLI_GUIDE_RU = """\
---
title: Использование CLI
description: Полное руководство по командной строке asocks.
sidebar:
  order: 2
---

CLI `asocks` генерирует, показывает и управляет прокси прямо из терминала.

## Аутентификация

```bash
export ASOCKS_API_KEY="sk-ваш-ключ"
# или флагом:
asocks balance --api-key sk-ваш-ключ
```

## Команды

```bash
# Интерактивный мастер (страна → регион → город)
asocks wizard
asocks wizard 5 --format json --output proxies.json

# Генерация портов и экспорт
asocks get US -n 10
asocks get US -n 50 -f csv -o proxies.csv

# Аккаунт
asocks balance
asocks list
asocks info 12345
asocks delete 12345

# Сырой API
asocks api countries
asocks api generate 5 --country DE
asocks api whitelist-add 203.0.113.42
```

## Форматы экспорта

- **TXT** (по умолчанию) — по одному URL на строку.
- **JSON** — структурированный массив.
- **CSV** — таблица с заголовками.

## Дальше

- [Быстрый старт](/asockslib/ru/guides/quickstart/)
- [Примеры использования](/asockslib/ru/guides/examples/)
"""

# Per-module reference metadata (Russian)
MODULE_META_RU: dict[str, dict[str, str]] = {
    "client": {"title": "API-клиент", "description": "Async HTTP-клиент для ASocks API v2."},
    "smart_proxy": {
        "title": "Smart Proxy Manager",
        "description": "Авто-проверка здоровья, ротация и самовосстановление.",
    },
    "models": {
        "title": "Модели данных",
        "description": "Модели Pydantic для запросов и ответов API.",
    },
    "exceptions": {
        "title": "Исключения",
        "description": "Классы исключений библиотеки ASocks.",
    },
    "cli": {"title": "Справочник CLI", "description": "Командный интерфейс ASocks Proxy API."},
    "benchmark": {"title": "Бенчмарк", "description": "Утилиты замера задержки прокси."},
    "proxy_pool": {
        "title": "ProxyPool Manager",
        "description": "Пул прокси без трафика для массового управления аккаунтами.",
    },
    "geo_picker": {
        "title": "GeoPicker",
        "description": "Интерактивный выбор гео-данных с нечётким поиском для CLI.",
    },
}

# Static pages per locale. English is the default (root); Russian lives under ru/.
# Pages absent from a locale fall back to the default locale automatically.
STATIC_PAGES_EN: dict[str, str] = {
    "index.mdx": INDEX_EN,
    "guides/quickstart.mdx": QUICKSTART_EN,
    "guides/examples.mdx": EXAMPLES_EN,
    "guides/cli.mdx": CLI_GUIDE_EN,
    "guides/smart-proxy.mdx": SMART_PROXY_GUIDE_EN,
    "guides/proxy-pool.mdx": PROXY_POOL_GUIDE_EN,
    "guides/concepts.mdx": CONCEPTS_EN,
    "guides/templates.mdx": TEMPLATES_EN,
    "guides/whitelist.mdx": WHITELIST_EN,
}

STATIC_PAGES_RU: dict[str, str] = {
    "index.mdx": INDEX_RU,
    "guides/quickstart.mdx": QUICKSTART_RU,
    "guides/examples.mdx": EXAMPLES_RU,
    "guides/cli.mdx": CLI_GUIDE_RU,
    "guides/smart-proxy.mdx": SMART_PROXY_GUIDE_RU,
    "guides/proxy-pool.mdx": PROXY_POOL_GUIDE_RU,
}

# locale key -> (output subdir, static pages, reference metadata)
LOCALES: dict[str, dict[str, object]] = {
    "en": {"subdir": "", "pages": STATIC_PAGES_EN, "meta": MODULE_META},
    "ru": {"subdir": "ru", "pages": STATIC_PAGES_RU, "meta": MODULE_META_RU},
}


# ---------------------------------------------------------------------------
# MDX generation
# ---------------------------------------------------------------------------


@beartype
def _frontmatter(title: str, description: str, order: int) -> str:
    return f"---\ntitle: {title}\ndescription: {description}\nsidebar:\n  order: {order}\n---\n"


# GitHub Pages serves this project under /asockslib. Astro rewrites asset URLs
# and slug-based sidebar links for the base automatically, but NOT root-absolute
# links written inside content. Prefix those so navigation works on Pages.
_BASE = "/asockslib"


@beartype
def _fix_links(text: str) -> str:
    """Prefix the Pages base onto bare ``/guides/`` and ``/reference/`` links.

    Idempotent: links already containing the base (e.g. the Russian pages'
    ``/asockslib/ru/...``) are left untouched.
    """
    text = re.sub(r"\]\(/(guides/|reference/)", rf"]({_BASE}/\1", text)
    return re.sub(r"(link:\s*)/(guides/|reference/)", rf"\g<1>{_BASE}/\2", text)


@beartype
def _write_reference(subdir: str, meta_map: dict[str, dict[str, str]]) -> int:
    """Generate reference docs for one locale. Returns file count."""
    out_dir = DOCS_ROOT / subdir / "reference" if subdir else DOCS_ROOT / "reference"
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for mod_name in MODULES:
        full_name = f"{PACKAGE_NAME}.{mod_name}"
        module = importlib.import_module(full_name)
        body = _extract(module)

        meta = meta_map.get(mod_name, {})
        title = meta.get("title", mod_name.replace("_", " ").title())
        desc = meta.get("description", "")
        if not desc:
            raw = _clean(module.__doc__)
            desc = raw.split("\n")[0] if raw else f"Reference for {title}"
        order = SIDEBAR_ORDER.get(mod_name, 99)

        fm = _frontmatter(title, desc, order)
        content = fm + "\n" + _fix_links(_escape_mdx(body)) + "\n"

        (out_dir / f"{mod_name}.mdx").write_text(content, encoding="utf-8")
        count += 1

    return count


@beartype
def _write_static_pages(subdir: str, pages: dict[str, str]) -> int:
    """Write static (guide + index) pages for one locale. Returns file count."""
    base = DOCS_ROOT / subdir if subdir else DOCS_ROOT
    count = 0
    for rel_path, content in pages.items():
        out = base / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_fix_links(content), encoding="utf-8")
        count += 1
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


@beartype
def generate_docs() -> None:
    """Wipe and regenerate all documentation pages for every locale."""
    print("🗑  Cleaning docs output directories …")
    for name in ("guides", "reference", "index.mdx", "ru", "en"):
        target = DOCS_ROOT / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()

    static_count = 0
    ref_count = 0
    for locale, cfg in LOCALES.items():
        subdir = str(cfg["subdir"])
        pages: dict[str, str] = cfg["pages"]  # type: ignore[assignment]
        meta: dict[str, dict[str, str]] = cfg["meta"]  # type: ignore[assignment]
        label = subdir or "root (en)"
        print(f"📝 [{locale}] writing static pages → {label} …")
        static_count += _write_static_pages(subdir, pages)
        print(f"📄 [{locale}] generating reference → {label} …")
        ref_count += _write_reference(subdir, meta)

    total = static_count + ref_count
    print(
        f"\n🎉 Done! {len(LOCALES)} locales, {static_count} static pages + "
        f"{ref_count} reference pages = {total} files total."
    )


if __name__ == "__main__":
    generate_docs()
