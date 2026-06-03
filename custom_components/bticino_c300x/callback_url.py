"""Callback URL helpers for C300X agent registrations."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit, urlunsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .callback_target import (
    callback_host_needs_rewrite,
    callback_host_type,
    callback_target_is_clean_local_http,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_CALLBACK_BASE_URL,
    DEFAULT_AGENT_PORT,
)
from .entry_config import entry_config_value

_SOURCE_CONNECT_TIMEOUT_SECONDS = 0.35
_DEFAULT_CALLBACK_PORT = 8123


async def async_generate_agent_callback_url(
    hass: HomeAssistant,
    entry: ConfigEntry,
    webhook_id: str,
) -> str:
    """Generate a HA webhook URL suitable for callbacks from the device agent.

    Home Assistant's default internal URL is often ``homeassistant.local``. On
    IPv6-enabled networks that can resolve to a link-local address, which is a
    poor callback target for the C300X and can also make the display bridge feel
    flaky. For agent callbacks we can safely replace only local/link-local hosts
    with HA's source address for the configured agent route.
    """

    from homeassistant.components import webhook

    try:
        callback_url = webhook.async_generate_url(
            hass,
            webhook_id,
            allow_external=False,
            allow_internal=True,
            prefer_external=False,
        )
    except TypeError:
        callback_url = webhook.async_generate_url(hass, webhook_id)
    callback_url = apply_callback_base_url(
        callback_url,
        str(entry_config_value(entry, CONF_CALLBACK_BASE_URL, "") or ""),
    )
    return await async_rewrite_link_local_callback_url(hass, entry, callback_url)


async def async_suggest_callback_base_url(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> str:
    """Suggest a local HTTP callback base URL without mutating the entry."""

    try:
        configured = normalize_callback_base_url(
            entry_config_value(entry, CONF_CALLBACK_BASE_URL, "") or ""
        )
    except ValueError:
        configured = ""
    if configured:
        return configured

    agent_host = str(entry_config_value(entry, CONF_AGENT_HOST, "") or "").strip()
    if not agent_host:
        return ""
    try:
        agent_port = int(entry_config_value(entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    except (TypeError, ValueError):
        agent_port = DEFAULT_AGENT_PORT
    source_ip = await hass.async_add_executor_job(
        _select_non_link_local_source_ip,
        agent_host,
        agent_port,
    )
    if source_ip is None:
        return ""
    return urlunsplit(
        ("http", f"{_format_url_host(source_ip)}:{_DEFAULT_CALLBACK_PORT}", "", "", "")
    )


def normalize_callback_base_url(value: object) -> str:
    """Validate and normalize a local HTTP callback base URL.

    Empty values disable the override. Non-empty values must be a plain HTTP
    endpoint that the embedded native agent can call directly on the local LAN.
    """

    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    parts = urlsplit(text)
    _valid_callback_port(parts)
    host_type = callback_host_type(parts.hostname)
    if (
        parts.scheme.lower() != "http"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or callback_target_is_clean_local_http(parts.scheme, host_type) is not True
    ):
        raise ValueError("callback base URL must be a reachable local HTTP URL")
    return urlunsplit(("http", parts.netloc, "", "", ""))


def apply_callback_base_url(callback_url: str, callback_base_url: str) -> str:
    """Return a callback URL using an optional configured base endpoint."""

    base_url = normalize_callback_base_url(callback_base_url)
    if not base_url:
        return callback_url
    callback = urlsplit(callback_url)
    base = urlsplit(base_url)
    return urlunsplit((base.scheme, base.netloc, callback.path, callback.query, ""))


async def async_rewrite_link_local_callback_url(
    hass: HomeAssistant,
    entry: ConfigEntry,
    callback_url: str,
) -> str:
    """Replace mDNS/link-local callback hosts with a routable HA source address."""

    parts = urlsplit(callback_url)
    if not callback_host_needs_rewrite(parts.hostname):
        return callback_url

    agent_host = str(entry_config_value(entry, CONF_AGENT_HOST, "") or "").strip()
    if not agent_host:
        return callback_url
    try:
        agent_port = int(entry_config_value(entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    except (TypeError, ValueError):
        agent_port = DEFAULT_AGENT_PORT

    source_ip = await hass.async_add_executor_job(
        _select_non_link_local_source_ip,
        agent_host,
        agent_port,
    )
    if source_ip is None:
        return callback_url
    return _replace_url_host(parts, source_ip)


def _valid_callback_port(parts: SplitResult) -> int | None:
    """Return a valid explicit callback port or reject malformed ports."""

    try:
        port = parts.port
    except ValueError as err:
        raise ValueError("callback base URL port is invalid") from err
    if port == 0 or parts.netloc.endswith(":"):
        raise ValueError("callback base URL port is invalid")
    return port


def _select_non_link_local_source_ip(agent_host: str, agent_port: int) -> str | None:
    """Return HA's preferred non-link-local source IP for the agent route."""

    candidates: list[str] = []
    for family, socktype, proto, _canonname, sockaddr in _route_candidates(
        agent_host,
        agent_port,
    ):
        with socket.socket(family, socktype, proto) as sock:
            sock.settimeout(_SOURCE_CONNECT_TIMEOUT_SECONDS)
            try:
                sock.connect(sockaddr)
                source = str(sock.getsockname()[0])
            except OSError:
                continue
        source = source.split("%", 1)[0]
        if not _source_ip_is_usable(source):
            continue
        candidates.append(source)

    return _preferred_source_ip(candidates)


def _route_candidates(
    agent_host: str,
    agent_port: int,
) -> list[tuple[int, int, int, str, tuple]]:
    host = agent_host.strip()
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    host = host.replace("%25", "%")
    try:
        return list(socket.getaddrinfo(host, agent_port, type=socket.SOCK_DGRAM))
    except OSError:
        return []


def _source_ip_is_usable(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (address.is_link_local or address.is_loopback or address.is_unspecified)


def _preferred_source_ip(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    unique = list(dict.fromkeys(candidates))
    for value in unique:
        try:
            if ipaddress.ip_address(value).version == 4:
                return value
        except ValueError:
            continue
    return unique[0]


def _replace_url_host(parts: SplitResult, host: str) -> str:
    hostname = _format_url_host(host)
    netloc = hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )


def _format_url_host(host: str) -> str:
    try:
        if ipaddress.ip_address(host).version == 6:
            return f"[{host}]"
    except ValueError:
        pass
    return host
