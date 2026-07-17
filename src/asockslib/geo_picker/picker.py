"""Interactive geo-data selection via fuzzy search.

Loads data from ``geo.json`` and provides convenient autocomplete
prompts for the CLI: country -> state -> city -> ASN.

Every prompt is **validated** — only values that exist in the
geo-data can be submitted.

Example::

    from asockslib.geo_picker import GeoPicker

    picker = GeoPicker()
    country = picker.pick_country()
    state = picker.pick_state("US")
    city = picker.pick_city("US", "California")
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from beartype import beartype
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML

from asockslib._console import console
from asockslib.geo_picker._completer import (
    FuzzyMatchCompleter,
    make_choice_validator,
    pt_style,
)
from asockslib.geo_picker._messages import PROXY_TEMPLATES, get_message
from asockslib.geo_picker._types import (
    CONNECTION_TYPES,
    PROXY_TYPES,
    SERVER_PORT_TYPES,
    PickedASN,
    PickedCity,
    PickedConnectionType,
    PickedCountry,
    PickedProxyType,
    PickedServerPortType,
    PickedState,
)

_GEO_JSON_PATH = Path(__file__).parent.parent / "geo.json"


class GeoPicker:
    """Interactive geo-data picker from local ``geo.json``.

    Loads the geo file once and caches it in memory.
    All ``pick_*`` methods show a fuzzy-search autocomplete prompt
    that displays **all** options when input is empty.

    Args:
        lang: UI language (only ``"en"`` is supported now).
        geo_json_path: Custom path to ``geo.json``.
    """

    def __init__(
        self,
        lang: str = "en",
        geo_json_path: Path | None = None,
    ) -> None:
        self._lang = "en"
        self._path = geo_json_path or _GEO_JSON_PATH
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        """Lazy-load geo.json."""
        data = self._data
        if data is None:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            self._data = data
        return data

    # ── Core autocomplete ─────────────────────────────────────────────── #

    def _autocomplete(
        self,
        message: str,
        choices: list[str],
        meta: dict[str, Any] | None = None,
    ) -> str | None:
        """Run an autocomplete prompt with strict validation.

        Only values present in *choices* can be submitted.
        Returns ``None`` on Ctrl-C / EOF.
        """
        completer = FuzzyMatchCompleter(choices)
        _lower_lookup: dict[str, str] = {c.strip().lower(): c for c in choices}

        validator = make_choice_validator(
            choices,
            error_msg=get_message("invalid_choice"),
            error_chars=get_message("invalid_chars"),
        )

        session: PromptSession[str] = PromptSession(
            completer=completer,
            complete_while_typing=True,
            validator=validator,
            validate_while_typing=False,
            style=pt_style(),
        )

        def _pre_run() -> None:
            session.default_buffer.start_completion()

        try:
            result: str = session.prompt(
                HTML(f"<qmark>?</qmark> <question>{message}</question> "),
                pre_run=_pre_run,
            )
        except (KeyboardInterrupt, EOFError):
            return None

        stripped = result.strip()
        if stripped in choices:
            return stripped
        key = stripped.lower()
        if key in _lower_lookup:
            return _lower_lookup[key]
        return None

    # ── Public pick methods ───────────────────────────────────────────── #

    @beartype
    def pick_country(self, message: str | None = None) -> PickedCountry | None:
        """Select a country via fuzzy search."""
        msg = message or get_message("pick_country")
        data = self._load()

        _title_to_code: dict[str, str] = {}
        titles: list[str] = []
        for code, info in sorted(data.items(), key=lambda x: x[1]["name"]):
            title = f"{info['code']:>2}  {info['name']}"
            titles.append(title)
            _title_to_code[title] = code

        result = self._autocomplete(msg, titles)
        if result is None:
            return None

        code = _title_to_code.get(result)
        if code and code in data:
            info = data[code]
            return PickedCountry(code=code, name=info["name"], id=info["id"])

        m = re.match(r"^\s*([A-Z]{2})\s{2,}(.+)$", result.strip())
        if m:
            code = m.group(1)
            if code in data:
                info = data[code]
                return PickedCountry(code=code, name=info["name"], id=info["id"])
        return None

    @beartype
    def pick_state(
        self,
        country_code: str,
        message: str | None = None,
        allow_skip: bool = True,
    ) -> PickedState | None:
        """Select a state/region via fuzzy search."""
        msg = message or get_message("pick_state")
        data = self._load()
        country = data.get(country_code.upper())
        if not country:
            return None

        states = country.get("states", {})
        state_items = [
            (name, sdata) for name, sdata in sorted(states.items()) if name != "_no_state"
        ]

        if not state_items:
            console.print(f"[dim]{get_message('no_states')}[/dim]")
            return None

        skip_label = get_message("skip")
        cities_word = get_message("cities_suffix")

        _title_to_state: dict[str, str] = {}
        titles: list[str] = []
        if allow_skip:
            titles.append(skip_label)
        for name, sdata in state_items:
            city_count = len(sdata.get("cities", []))
            title = f"{name}  ({city_count} {cities_word})"
            titles.append(title)
            _title_to_state[title] = name

        result = self._autocomplete(msg, titles)
        if result is None or result.startswith("⏭"):
            return None

        state_name = _title_to_state.get(result)
        if state_name is None:
            m = re.match(r"^(.+?)\s{2}\(\d+\s", result)
            if m:
                state_name = m.group(1).strip()

        if state_name is None:
            return None

        for name, sdata in state_items:
            if name == state_name or name.lower() == state_name.lower():
                return PickedState(name=name, id=sdata["id"])
        return None

    @beartype
    def pick_city(
        self,
        country_code: str,
        state_name: str | None = None,
        message: str | None = None,
        allow_skip: bool = True,
    ) -> PickedCity | None:
        """Select a city via fuzzy search."""
        msg = message or get_message("pick_city")
        data = self._load()
        country = data.get(country_code.upper())
        if not country:
            return None

        cities: list[dict[str, Any]] = []
        states = country.get("states", {})

        if state_name:
            state = states.get(state_name)
            if not state:
                for sname, sdata in states.items():
                    if sname.lower() == state_name.lower():
                        state = sdata
                        break
            if state:
                cities = state.get("cities", [])
        else:
            for sdata in states.values():
                cities.extend(sdata.get("cities", []))

        if not cities:
            console.print(f"[dim]{get_message('no_cities')}[/dim]")
            return None

        sorted_cities = sorted(cities, key=lambda x: x["name"])
        skip_label = get_message("skip")

        _name_to_city: dict[str, dict[str, Any]] = {}
        _lower_to_city: dict[str, dict[str, Any]] = {}
        titles: list[str] = []
        if allow_skip:
            titles.append(skip_label)
        for city in sorted_cities:
            cname = city["name"]
            titles.append(cname)
            _name_to_city[cname] = city
            _lower_to_city[cname.lower()] = city

        result = self._autocomplete(msg, titles)
        if result is None or result.startswith("⏭"):
            return None

        city_data = _name_to_city.get(result)
        if city_data is None:
            city_data = _lower_to_city.get(result.strip().lower())

        if city_data is not None:
            return PickedCity(name=city_data["name"], id=city_data["id"])
        return None

    @beartype
    def pick_asn(
        self,
        country_code: str,
        message: str | None = None,
        allow_skip: bool = True,
    ) -> PickedASN | None:
        """Select an ASN provider via fuzzy search."""
        msg = message or get_message("pick_asn")
        data = self._load()
        country = data.get(country_code.upper())
        if not country:
            return None

        asns = country.get("asns", [])
        if not asns:
            console.print(f"[dim]{get_message('no_asns')}[/dim]")
            return None

        sorted_asns = sorted(asns, key=lambda x: x["asn"])
        skip_label = get_message("skip")

        _label_to_asn: dict[str, dict[str, Any]] = {}
        titles: list[str] = []
        if allow_skip:
            titles.append(skip_label)
        for asn in sorted_asns:
            name = asn.get("name", "")
            label = f"AS{asn['asn']}" + (f"  {name}" if name else "")
            titles.append(label)
            _label_to_asn[label] = asn

        result = self._autocomplete(msg, titles)
        if result is None or result.startswith("⏭"):
            return None

        asn_data = _label_to_asn.get(result)
        if asn_data is None:
            rl = result.strip().lower()
            for label, adata in _label_to_asn.items():
                if label.lower() == rl:
                    asn_data = adata
                    break

        if asn_data is not None:
            return PickedASN(number=asn_data["asn"], name=asn_data.get("name", ""))
        return None

    # ── Type pickers ──────────────────────────────────────────────────── #

    @beartype
    def _pick_from_list(
        self,
        message: str,
        items: list[tuple[int, str]],
    ) -> tuple[int, str] | None:
        """Generic picker for static (id, label) lists."""
        _label_to_id: dict[str, int] = {}
        titles: list[str] = []
        for type_id, label in items:
            titles.append(label)
            _label_to_id[label] = type_id

        result = self._autocomplete(message, titles)
        if result is None:
            return None

        tid = _label_to_id.get(result)
        if tid is None:
            rl = result.strip().lower()
            for label, t in _label_to_id.items():
                if label.lower() == rl:
                    tid = t
                    result = label
                    break
        if tid is not None:
            return tid, result
        return None

    @beartype
    def pick_connection_type(self, message: str | None = None) -> PickedConnectionType | None:
        """Select a connection type."""
        msg = message or get_message("pick_connection_type")
        picked = self._pick_from_list(msg, CONNECTION_TYPES)
        if picked:
            return PickedConnectionType(id=picked[0], label=picked[1])
        return None

    @beartype
    def pick_proxy_type(self, message: str | None = None) -> PickedProxyType | None:
        """Select a proxy type."""
        msg = message or get_message("pick_proxy_type")
        picked = self._pick_from_list(msg, PROXY_TYPES)
        if picked:
            return PickedProxyType(id=picked[0], label=picked[1])
        return None

    @beartype
    def pick_server_port_type(self, message: str | None = None) -> PickedServerPortType | None:
        """Select a server port type."""
        msg = message or get_message("pick_server_port_type")
        picked = self._pick_from_list(msg, SERVER_PORT_TYPES)
        if picked:
            return PickedServerPortType(id=picked[0], label=picked[1])
        return None

    # ── Free-text input ───────────────────────────────────────────────── #

    @beartype
    def _free_input(
        self,
        message: str,
        default: str = "",
        allow_empty: bool = True,
    ) -> str:
        """Show a free-text input prompt."""
        session: PromptSession[str] = PromptSession(style=pt_style())
        placeholder = HTML(f"<ansigray>{default}</ansigray>") if default else None
        try:
            result: str = session.prompt(
                HTML(f"<qmark>?</qmark> <question>{message}</question> "),
                placeholder=placeholder,
            )
        except (KeyboardInterrupt, EOFError):
            return default

        stripped = result.strip()
        if not stripped and allow_empty:
            return default
        return stripped

    # ── Action / number / misc pickers ────────────────────────────────── #

    @beartype
    def pick_action(self, message: str | None = None) -> str | None:
        """Pick wizard action: create proxies or find best proxies.

        Returns ``"create"``, ``"best"`` or ``None``.
        """
        msg = message or get_message("pick_action")
        action_create = get_message("action_create")
        action_best = get_message("action_best")
        choices = [action_create, action_best]

        result = self._autocomplete(msg, choices)
        if result is None:
            return None
        if result == action_best:
            return "best"
        return "create"

    @beartype
    def pick_count(self, message: str | None = None, default: int = 10) -> int:
        """Pick number of proxies to create."""
        msg = message or get_message("pick_count")
        choices = ["1", "5", "10", "25", "50", "100", "250", "500", "1000"]
        result = self._autocomplete(msg, choices)
        if result and result.isdigit():
            return int(result)
        return default

    @beartype
    def pick_keep(self, message: str | None = None, default: int = 10) -> int:
        """Pick how many best proxies to keep."""
        msg = message or get_message("pick_keep")
        choices = ["1", "3", "5", "10", "20", "50"]
        result = self._autocomplete(msg, choices)
        if result and result.isdigit():
            return int(result)
        return default

    @beartype
    def pick_name(self, message: str | None = None) -> str:
        """Pick port name (free text, optional)."""
        msg = message or get_message("pick_name")
        return self._free_input(msg, default="", allow_empty=True)

    @beartype
    def pick_format(self, message: str | None = None) -> str:
        """Pick export format (``txt``, ``json``, ``csv``)."""
        msg = message or get_message("pick_format")
        labels = [
            "txt — one proxy per line",
            "json — JSON array",
            "csv — CSV with header",
        ]
        result = self._autocomplete(msg, labels)
        if result:
            return result.split(" ")[0]
        return "txt"

    @beartype
    def pick_output(self, message: str | None = None) -> str:
        """Pick output file path (optional)."""
        msg = message or get_message("pick_output")
        return self._free_input(msg, default="", allow_empty=True)

    @beartype
    def pick_timeout(self, message: str | None = None, default: float = 15.0) -> float:
        """Pick benchmark timeout."""
        msg = message or get_message("pick_timeout")
        choices = ["5", "10", "15", "30", "60"]
        result = self._autocomplete(msg, choices)
        if result and result.replace(".", "", 1).isdigit():
            return float(result)
        return default

    @beartype
    def pick_concurrency(self, message: str | None = None, default: int = 50) -> int:
        """Pick benchmark concurrency."""
        msg = message or get_message("pick_concurrency")
        choices = ["10", "25", "50", "100", "200"]
        result = self._autocomplete(msg, choices)
        if result and result.isdigit():
            return int(result)
        return default

    # ── Proxy template picker ─────────────────────────────────────────── #

    @beartype
    def pick_proxy_template(self, message: str | None = None) -> str:
        """Select a proxy output template.

        Returns the template string, e.g.
        ``"{protocol}://{login}:{password}@{ip}:{port}"``.
        """
        msg = message or get_message("pick_proxy_template")
        _label_to_tpl: dict[str, str] = {}
        titles: list[str] = []
        for tpl, label in PROXY_TEMPLATES:
            titles.append(label)
            _label_to_tpl[label] = tpl

        result = self._autocomplete(msg, titles)
        if result is None:
            return "{protocol}://{login}:{password}@{ip}:{port}"

        tpl = _label_to_tpl.get(result)
        if tpl is None:
            rl = result.strip().lower()
            for label, t in _label_to_tpl.items():
                if label.lower() == rl:
                    tpl = t
                    break
        return tpl or "{protocol}://{login}:{password}@{ip}:{port}"

    # ── Full wizards ──────────────────────────────────────────────────── #

    @beartype
    def pick_full(self) -> dict[str, str | int | None]:
        """Full wizard: connection type -> proxy type -> port type -> geo."""
        result: dict[str, str | int | None] = {
            "country_code": None,
            "country_name": None,
            "state": None,
            "city": None,
            "city_id": None,
            "type_id": None,
            "proxy_type_id": None,
            "server_port_type_id": None,
            "traffic_limit": None,
        }

        conn = self.pick_connection_type()
        if conn:
            result["type_id"] = conn.id

        ptype = self.pick_proxy_type()
        if ptype:
            result["proxy_type_id"] = ptype.id

        spt = self.pick_server_port_type()
        if spt:
            result["server_port_type_id"] = spt.id

        country = self.pick_country()
        if not country:
            return result
        result["country_code"] = country.code
        result["country_name"] = country.name

        state = self.pick_state(country.code)
        if state:
            result["state"] = state.name

        city = self.pick_city(
            country.code,
            state_name=state.name if state else None,
        )
        if city:
            result["city"] = city.name
            result["city_id"] = city.id

        if result.get("server_port_type_id") == 1:
            traffic_msg = get_message("pick_traffic_limit")
            traffic_choices = ["1", "5", "10", "25", "50", "100", "250", "500", "1000"]
            traffic_result = self._autocomplete(traffic_msg, traffic_choices)
            if traffic_result and traffic_result.isdigit():
                result["traffic_limit"] = int(traffic_result)

        return result

    @beartype
    def pick_wizard(self) -> dict[str, str | int | float | None]:
        """Full interactive wizard — everything in one flow.

        Returns a dict with all wizard parameters.
        """
        result: dict[str, str | int | float | None] = {
            "action": None,
            "country_code": None,
            "country_name": None,
            "state": None,
            "city": None,
            "city_id": None,
            "type_id": 1,
            "proxy_type_id": 1,
            "server_port_type_id": 0,
            "traffic_limit": 10,
            "count": 10,
            "keep": 10,
            "ttl": 1,
            "name": "",
            "format": "txt",
            "output": "",
            "timeout": 15.0,
            "concurrency": 50,
            "proxy_template": "{protocol}://{login}:{password}@{ip}:{port}",
        }

        action = self.pick_action()
        if action is None:
            return result
        result["action"] = action

        ptype = self.pick_proxy_type()
        if ptype:
            result["proxy_type_id"] = ptype.id

        conn = self.pick_connection_type()
        if conn:
            result["type_id"] = conn.id

        spt = self.pick_server_port_type()
        if spt:
            result["server_port_type_id"] = spt.id

        country = self.pick_country()
        if not country:
            return result
        result["country_code"] = country.code
        result["country_name"] = country.name

        state = self.pick_state(country.code)
        if state:
            result["state"] = state.name

        city = self.pick_city(
            country.code,
            state_name=state.name if state else None,
        )
        if city:
            result["city"] = city.name
            result["city_id"] = city.id

        if action == "best":
            result["count"] = self.pick_count(default=100)
            result["keep"] = self.pick_keep(default=10)
        else:
            result["count"] = self.pick_count(default=10)

        result["name"] = self.pick_name()

        if result.get("server_port_type_id") == 1:
            traffic_msg = get_message("pick_traffic_limit")
            traffic_choices = ["1", "5", "10", "25", "50", "100", "250", "500", "1000"]
            traffic_result = self._autocomplete(traffic_msg, traffic_choices)
            if traffic_result and traffic_result.isdigit():
                result["traffic_limit"] = int(traffic_result)

        result["proxy_template"] = self.pick_proxy_template()
        result["format"] = self.pick_format()
        result["output"] = self.pick_output()

        if action == "best":
            result["timeout"] = self.pick_timeout()
            result["concurrency"] = self.pick_concurrency()

        return result
