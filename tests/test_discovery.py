from __future__ import annotations

import pytest

from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    DEFAULT_NAME,
)
from custom_components.bticino_c300x.discovery import (
    discovery_connection_updates,
    discovery_display_name,
    discovery_matches_entry,
    discovery_unique_id,
)


def test_discovery_unique_id_accepts_txt_properties() -> None:
    assert discovery_unique_id({b"serialno": b"C300X-001"}) == "c300x001"


def test_discovery_unique_id_prefers_stable_identity_keys() -> None:
    assert discovery_unique_id({"name": "Panel", "mac": "AA:BB:CC:00:11:22"}) == (
        "aabbcc001122"
    )


def test_discovery_unique_id_rejects_unidentified_advertisement() -> None:
    assert discovery_unique_id({"name": "Panel"}) is None


def test_discovery_display_name_strips_service_suffix() -> None:
    assert (
        discovery_display_name(
            {},
            "C300X Agent._bticino-c300x-agent._tcp.local.",
        )
        == DEFAULT_NAME
    )


def test_discovery_display_name_prefers_txt_friendly_name() -> None:
    assert (
        discovery_display_name(
            {b"friendly_name": b"Front door"},
            "C300X Agent._bticino-c300x-agent._tcp.local.",
        )
        == "Front door"
    )


def test_discovery_display_name_uses_default_for_generic_model() -> None:
    assert discovery_display_name({"model": "C300X"}, "") == DEFAULT_NAME


def test_discovery_connection_updates_validates_network_target() -> None:
    assert discovery_connection_updates(" c300x-agent.local ", 8091) == {
        CONF_AGENT_HOST: "c300x-agent.local",
        CONF_AGENT_PORT: 8091,
    }


@pytest.mark.parametrize(("host", "port"), [("", 8091), ("host", 0), ("host", 70000)])
def test_discovery_connection_updates_rejects_invalid_targets(
    host: str,
    port: int,
) -> None:
    with pytest.raises(ValueError):
        discovery_connection_updates(host, port)


def test_discovery_matches_entry_normalizes_identity() -> None:
    assert discovery_matches_entry("AA-BB-CC", "aa:bb:cc")
