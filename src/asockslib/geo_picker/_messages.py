"""UI messages and proxy output templates for the geo-picker."""

from __future__ import annotations

# ── Messages ──────────────────────────────────────────────────────────────── #

MESSAGES: dict[str, str] = {
    "pick_country": "🌍 Select country",
    "pick_state": "📍 Select state/region",
    "pick_city": "🏙  Select city",
    "pick_asn": "🔗 Select ASN provider",
    "skip": "⏭  (skip)",
    "no_states": "No states available for this country.",
    "no_cities": "No cities available.",
    "no_asns": "No ASN providers available for this country.",
    "cities_suffix": "cities",
    "params": "Parameters",
    "invalid_choice": "⚠ Value not in the list. Use arrows or type to filter.",
    "invalid_country_code": "⚠ Invalid country code (must be 2 letters, e.g. US).",
    "invalid_chars": "⚠ Input contains invalid characters.",
    "pick_connection_type": "🔌 Connection type",
    "pick_proxy_type": "🛡  Proxy type",
    "pick_server_port_type": "🖥  Server port type",
    "pick_traffic_limit": "📊 Traffic limit (GB)",
    "pick_action": "🚀 What do you want to do?",
    "action_create": "Create proxies — get working proxies quickly",
    "action_best": "Find best proxies — create, benchmark, keep the fastest",
    "pick_count": "🔢 How many proxies?",
    "pick_keep": "🏆 How many best to keep?",
    "pick_name": "📝 Port name (optional, Enter to skip)",
    "pick_format": "📄 Export format",
    "pick_output": "💾 Output file (optional, Enter to skip)",
    "pick_timeout": "⏱  Benchmark timeout (seconds)",
    "pick_concurrency": "⚡ Benchmark concurrency",
    "pick_proxy_template": "📋 Output template (proxy format)",
}


def get_message(key: str) -> str:
    """Get a message string by key."""
    return MESSAGES.get(key, key)


# ── Proxy output templates ────────────────────────────────────────────────── #

PROXY_TEMPLATES: list[tuple[str, str]] = [
    ("{protocol}://{login}:{password}@{ip}:{port}", "Standard URL — protocol://login:pass@ip:port"),
    ("http://{login}:{password}@{ip}:{port}", "HTTP URL — http://login:pass@ip:port"),
    ("socks5://{login}:{password}@{ip}:{port}", "SOCKS5 URL — socks5://login:pass@ip:port"),
    ("{ip}:{port}:{login}:{password}", "ip:port:login:password"),
    ("{protocol}://{ip}:{port}:{login}:{password}", "protocol://ip:port:login:password"),
    (
        "{protocol}://{login}:{password}@{ip}:{port}[{refresh_link}]",
        "URL with refresh link — protocol://login:pass@ip:port[refresh]",
    ),
    (
        "{protocol}://{login}:{password}@{ip}:{port}:{name}[{refresh_link}]",
        "Full URL — login:pass@ip:port:name[refresh]",
    ),
    (
        "http://{login}:{password}@{ip}:{port}:{name}[{refresh_link}]",
        "HTTP full — http://login:pass@ip:port:name[refresh]",
    ),
    (
        "socks5://{login}:{password}@{ip}:{port}:{name}[{refresh_link}]",
        "SOCKS5 full — socks5://login:pass@ip:port:name[refresh]",
    ),
    ("{ip}:{port}:{login}:{password}:{refresh_link}", "ip:port:login:password:refresh_link"),
    ("{ip}:{port}:{login}:{password}:{name}", "ip:port:login:password:name"),
    ("{name}:{ip}:{port}:{login}:{password}", "name:ip:port:login:password"),
    ("{ip}:{port}:{login}:{password}|{refresh_link}", "ip:port:login:password|refresh_link"),
    ("HTTP|{ip}|{port}|{login}|{password}", "HTTP|ip|port|login|password (pipe separated)"),
    (
        "{protocol}://{ip}:{port}:{login}:{password}:{refresh_link}",
        "protocol://ip:port:login:password:refresh",
    ),
    (
        "{protocol}://{ip}:{port}:{login}:{password}[{refresh_link}]{{name}}",
        "protocol://ip:port:login:password[refresh]{name}",
    ),
    (
        "{protocol}:{ip}:{port}:{login}:{password}",
        "protocol:ip:port:login:password (no slashes)",
    ),
    (
        "curl -x http://{login}:{password}@{ip}:{port} https://i.pn",
        "curl command — ready-to-use curl",
    ),
]
