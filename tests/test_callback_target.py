from __future__ import annotations

import ipaddress

import pytest

from custom_components.bticino_c300x.callback_target import (
    callback_address_type,
    callback_host_needs_rewrite,
    callback_host_type,
    callback_target_is_clean_local_http,
    callback_url_host_type,
    callback_url_scheme,
    clean_callback_host,
)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("homeassistant.local", "mdns"),
        ("localhost", "loopback"),
        ("localhost.localdomain", "loopback"),
        ("127.0.0.1", "loopback"),
        ("0.0.0.0", "unspecified"),
        ("[fe80::1%eth0]", "link_local_ipv6"),
        ("[::]", "unspecified"),
        ("192.0.2.10", "ipv4"),
        ("2001:db8::10", "ipv6"),
        ("ha.example.internal", "hostname"),
        ("", None),
    ],
)
def test_callback_host_type(host: str, expected: str | None) -> None:
    assert callback_host_type(host) == expected


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("127.0.0.1", "loopback"),
        ("0.0.0.0", "unspecified"),
        ("::", "unspecified"),
        ("fe80::1", "link_local_ipv6"),
        ("192.0.2.10", "ipv4"),
        ("2001:db8::10", "ipv6"),
    ],
)
def test_callback_address_type(address: str, expected: str) -> None:
    assert callback_address_type(ipaddress.ip_address(address)) == expected


def test_callback_host_needs_rewrite_for_mdns_and_link_local() -> None:
    assert callback_host_needs_rewrite("homeassistant.local") is True
    assert callback_host_needs_rewrite("fe80::1") is True
    assert callback_host_needs_rewrite("127.0.0.1") is True
    assert callback_host_needs_rewrite("203.0.113.20") is False


def test_callback_url_helpers_classify_full_urls() -> None:
    url = "HTTP://[2001:db8::10]:8123/api/webhook/private"

    assert callback_url_scheme(url) == "http"
    assert callback_url_host_type(url) == "ipv6"
    assert clean_callback_host(url) == "2001:db8::10"


@pytest.mark.parametrize(
    ("scheme", "host_type", "expected"),
    [
        (None, None, None),
        ("http", "ipv4", True),
        ("http", "ipv6", True),
        ("http", "hostname", True),
        ("https", "ipv4", False),
        ("http", "mdns", False),
        ("http", "loopback", False),
        ("http", "link_local_ipv6", False),
        ("http", "unspecified", False),
    ],
)
def test_callback_target_is_clean_local_http(
    scheme: str | None,
    host_type: str | None,
    expected: bool | None,
) -> None:
    assert callback_target_is_clean_local_http(scheme, host_type) is expected
