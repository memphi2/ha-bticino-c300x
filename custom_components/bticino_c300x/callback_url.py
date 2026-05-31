"""Callback URL helpers for C300X agent registrations."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit, urlunsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_AGENT_HOST, CONF_AGENT_PORT, DEFAULT_AGENT_PORT
from .entity import entry_config_value

_SOURCE_CONNECT_TIMEOUT_SECONDS = 0.35


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
    return await async_rewrite_link_local_callback_url(hass, entry, callback_url)


async def async_rewrite_link_local_callback_url(
    hass: HomeAssistant,
    entry: ConfigEntry,
    callback_url: str,
) -> str:
    """Replace mDNS/link-local callback hosts with a routable HA source address."""

    parts = urlsplit(callback_url)
    if not _callback_host_needs_rewrite(parts.hostname):
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


def _callback_host_needs_rewrite(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip("[]").split("%", 1)[0].lower()
    if host.endswith(".local") or host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_link_local or address.is_loopback


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
