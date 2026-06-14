"""Safe callback-target classification helpers."""

from __future__ import annotations

import ipaddress
from typing import Final
from urllib.parse import urlsplit

HOST_TYPE_HOSTNAME: Final = "hostname"
HOST_TYPE_IPV4: Final = "ipv4"
HOST_TYPE_IPV6: Final = "ipv6"
HOST_TYPE_LINK_LOCAL_IPV4: Final = "link_local_ipv4"
HOST_TYPE_LINK_LOCAL_IPV6: Final = "link_local_ipv6"
HOST_TYPE_LOOPBACK: Final = "loopback"
HOST_TYPE_MDNS: Final = "mdns"
HOST_TYPE_UNSPECIFIED: Final = "unspecified"

CALLBACK_REWRITE_HOST_TYPES: Final = frozenset(
    {
        HOST_TYPE_LINK_LOCAL_IPV4,
        HOST_TYPE_LINK_LOCAL_IPV6,
        HOST_TYPE_LOOPBACK,
        HOST_TYPE_MDNS,
    }
)

UNREACHABLE_CALLBACK_HOST_TYPES: Final = frozenset(
    {
        None,
        *CALLBACK_REWRITE_HOST_TYPES,
        HOST_TYPE_UNSPECIFIED,
    }
)


def callback_url_scheme(callback_url: str) -> str | None:
    """Return a normalized URL scheme, or None when missing."""

    scheme = urlsplit(callback_url).scheme.strip().lower()
    return scheme or None


def callback_url_host_type(callback_url: str) -> str | None:
    """Return the callback host type for a full callback URL."""

    return callback_host_type(urlsplit(callback_url).hostname)


def callback_host_type(host: str | None) -> str | None:
    """Return a privacy-safe host classification for callback diagnostics."""

    clean_host = clean_callback_host(host)
    if not clean_host:
        return None
    if clean_host.endswith(".local"):
        return HOST_TYPE_MDNS
    if clean_host in {"localhost", "localhost.localdomain"}:
        return HOST_TYPE_LOOPBACK
    try:
        address = ipaddress.ip_address(clean_host)
    except ValueError:
        return HOST_TYPE_HOSTNAME
    return callback_address_type(address)


def callback_address_type(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
) -> str | None:
    """Return the callback host type for a parsed IP address."""

    if address is None:
        return None
    if address.is_unspecified:
        return HOST_TYPE_UNSPECIFIED
    if address.is_loopback:
        return HOST_TYPE_LOOPBACK
    if address.is_link_local:
        return (
            HOST_TYPE_LINK_LOCAL_IPV6
            if address.version == 6
            else HOST_TYPE_LINK_LOCAL_IPV4
        )
    return HOST_TYPE_IPV6 if address.version == 6 else HOST_TYPE_IPV4


def clean_callback_host(host: str | None) -> str:
    """Return a normalized host value without resolving it."""

    value = str(host or "").strip()
    if "://" in value:
        value = urlsplit(value).hostname or value
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    return value.split("%", 1)[0].lower()


def callback_target_is_clean_local_http(
    scheme: str | None,
    host_type: str | None,
) -> bool | None:
    """Return whether a callback target can be used by the native C agent."""

    if scheme is None and host_type is None:
        return None
    return scheme == "http" and host_type not in UNREACHABLE_CALLBACK_HOST_TYPES


def callback_host_needs_rewrite(host: str | None) -> bool:
    """Return whether HA should rewrite this callback host for the C300X."""

    return callback_host_type(host) in CALLBACK_REWRITE_HOST_TYPES
