# ASocksLib

Premium Python library and CLI for the [ASocks Proxy API](https://docs.asocks.com/en/).

[![CI](https://github.com/bot4ka/asockslib/actions/workflows/ci.yml/badge.svg)](https://github.com/bot4ka/asockslib/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Features

| Feature | Description |
|---------|-------------|
| **One-liner API** | Get working proxies in a single function call |
| **Async Client** | Fully typed `httpx` client, Pydantic models, configurable retry/back-off on 429/5xx/network, typed errors |
| **Smart Proxy** | Health checking, auto-rotation, and self-healing proxy manager |
| **Proxy Pool** | Zero-traffic pool for 100,000+ accounts — detects dead proxies via API, sticky per-account mapping, pluggable persistence, optional ping-ranked selection |
| **CLI** | Interactive wizard, bulk generation, clipboard auto-copy |
| **18 Templates** | Built-in output formats for AdsPower, Dolphin Anty, GoLogin, etc. |
| **Export** | `.txt`, `.json`, `.csv` |
| **Type Safe** | Strict `mypy` + `pyright` + `beartype` runtime checks |

## Installation

```bash
pip install asockslib
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add asockslib
```

## Quick Start

Set your API key:

```bash
export ASOCKS_API_KEY="sk-your-api-key"
```

### One-liner

```python
import asyncio
from asockslib import get_proxies

urls = asyncio.run(get_proxies("US", count=10))
# → ["socks5://user:pass@host:port", ...]
```

### Full API Client

```python
import asyncio
from asockslib import ASocksClient, CreatePortRequest

async def main():
    async with ASocksClient(api_key="sk-...") as client:
        balance = await client.get_balance()
        print(f"Balance: ${balance.balance:.2f}")

        ports = await client.create_ports(
            CreatePortRequest(country_code="US", count=5)
        )
        for p in ports:
            print(p.proxy_url)

asyncio.run(main())
```

### Smart Proxy (auto-rotation)

```python
from asockslib import ASocksClient, SmartProxy

async with ASocksClient(api_key="sk-...") as client:
    smart = SmartProxy(client, country_code="US")
    await smart.initialize(pool_size=5)

    proxy = await smart.get_proxy()  # auto-heals on failure
```

### Proxy Pool (100,000+ accounts)

```python
from asockslib import ASocksClient, ProxyPool, PoolStrategy

async with ASocksClient(api_key="sk-...") as client:
    pool = ProxyPool(
        client,
        country_code="US",
        city="New York",              # geo-targeting: country + city
        pool_size=100,
        strategy=PoolStrategy.STICKY, # each account pinned to its own proxy
    )
    await pool.initialize()

    url = await pool.get_proxy("account_42")  # sticky assignment
    # On failure — auto-replaces via API (zero traffic waste)
    await pool.report_failure("account_42")
    url = await pool.get_proxy("account_42")  # new same-geo proxy!

    await pool.shutdown()
```

**Persistence across restarts** — supply a `ProxyStore` so `account_id → port_id`
bindings survive a process restart (mapping is otherwise in-memory only):

```python
class RedisStore:  # implement against Redis / SQL / file — your backend
    async def load(self) -> dict[str, int]: ...
    async def save(self, account_id: str, port_id: int) -> None: ...
    async def delete(self, account_id: str) -> None: ...

pool = ProxyPool(client, country_code="US", pool_size=100, store=RedisStore())
await pool.initialize()  # restores bindings from the store
```

**Ping-ranked selection** — over-provision, benchmark, keep the fastest
(default off = zero-traffic startup):

```python
pool = ProxyPool(
    client, country_code="US", pool_size=100,
    benchmark_on_init=True, benchmark_oversample=2.0,  # test 200, keep fastest 100
)
```

### Reliability & errors

The client retries **429, 5xx and transient network errors** with configurable
exponential back-off. Non-idempotent `POST` (create-port) is retried only on 429,
so a timeout can never silently double-create paid ports.

```python
from asockslib import ASocksClient, APIConnectionError, RateLimitError, ASocksError

client = ASocksClient(
    api_key="sk-...",
    max_retries=5,          # attempts per request
    retry_backoff_base=1.0, # attempt n waits base * 2**(n-1), capped at max
    retry_backoff_max=30.0,
)

try:
    await client.get_balance()
except APIConnectionError as e:   # network unreachable after all retries
    ...
except RateLimitError as e:       # 429 after all retries
    ...
except ASocksError as e:          # any library error — has .status_code / .message
    ...
```

## CLI

```bash
# Interactive wizard
asocks wizard

# Quick proxy generation
asocks get US -n 10

# Custom template + export
asocks get US -n 50 -f json -o proxies.json

# Account management
asocks balance
asocks list
asocks info 12345
asocks delete 12345

# Raw API
asocks api countries
asocks api generate 5 --country DE
asocks api whitelist-add 203.0.113.42
```

## Documentation

Full docs: **[bot4ka.github.io/asockslib](https://bot4ka.github.io/asockslib)**

## Development

```bash
uv sync                          # install dependencies
uv run pytest                    # run tests
uv run pyright                   # type checking
uv run ruff check .              # linting
uv run python generate_docs.py   # generate docs
cd docs && npm run dev           # start docs dev server
```

## License

MIT
