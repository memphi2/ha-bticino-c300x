from __future__ import annotations

# ruff: noqa: E402, I001

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from custom_components.bticino_c300x.agent_contracts import CapabilityPayload  # noqa: E402
from custom_components.bticino_c300x.entity import C300XEntity  # noqa: E402


@dataclass
class _FakeConnectionState:
    available: bool = True


@dataclass
class _FakeEventState:
    last_event: str | None = None
    last_event_time: str | None = None
    last_event_data: dict[str, Any] = field(default_factory=dict)
    smartphone_forwarding_mode: str | None = None
    ringer_muted: bool | None = None
    ringer_volume: int | None = None
    voicemail_total: int | None = None
    voicemail_unread: int | None = None


@dataclass
class _FakeRuntimeData:
    event_state: _FakeEventState = field(default_factory=_FakeEventState)
    connection_state: _FakeConnectionState = field(default_factory=_FakeConnectionState)
    agent_info: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


class _FakeBus:
    def __init__(self) -> None:
        self.listeners: list[tuple[str, Any]] = []

    def async_listen(self, event_type: str, callback: Any) -> Any:
        self.listeners.append((event_type, callback))
        return lambda: None


class _FakeHass:
    def __init__(self, language: str = "en") -> None:
        self.bus = _FakeBus()
        self.config = SimpleNamespace(language=language)


def test_device_info_uses_c300x_firmware_as_software_version() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(agent_info={"firmware": "1.7.19"}),
    )
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]

    assert entity.device_info["sw_version"] == "1.7.19"


def test_device_info_uses_typed_setup_firmware_as_software_version() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_info=CapabilityPayload(
                raw={"api_version": "1"},
                version="1.2.0",
                agent={"version": "1.2.0"},
                implementation="native-c",
                api_version="1",
                device_id="device",
                model="C300X",
                firmware="1.7.19",
                capabilities={},
            ),
        ),
    )
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]

    assert entity.device_info["sw_version"] == "1.7.19"


def test_device_info_names_the_model_the_agent_detected() -> None:
    c100x = _FakeEntry(runtime_data=_FakeRuntimeData(agent_info={"model": "C100X"}))
    c300x = _FakeEntry(runtime_data=_FakeRuntimeData(agent_info={"model": "C300X"}))
    offline = _FakeEntry(runtime_data=_FakeRuntimeData(agent_info={"model": None}))

    assert C300XEntity(c100x, "test").device_info["model"] == "Classe 100X"  # type: ignore[arg-type]
    assert C300XEntity(c300x, "test").device_info["model"] == "Classe 300X"  # type: ignore[arg-type]
    assert C300XEntity(offline, "test").device_info["model"] == "Classe 300X"  # type: ignore[arg-type]


def test_device_info_shows_the_board_and_the_article_number_the_station_reports() -> None:
    owner = _FakeEntry(runtime_data=_FakeRuntimeData(agent_info={
        "model": "C300X", "firmware": "1.7.19",
        "board": "BTicino ZIA board HW Rev 3", "article": "344642",
    }))
    info = C300XEntity(owner, "test").device_info  # type: ignore[arg-type]
    assert (info["model"], info["sw_version"]) == ("Classe 300X", "1.7.19")
    # The full board name, and the article number as the model id.
    assert (info["hw_version"], info["model_id"]) == ("BTicino ZIA board HW Rev 3", "344642")

    c100x = _FakeEntry(runtime_data=_FakeRuntimeData(agent_info={
        "model": "C100X", "board": "BTicino SHARK board (Dig-D/Car-C)", "article": "",
    }))
    info = C300XEntity(c100x, "test").device_info  # type: ignore[arg-type]
    assert info["hw_version"] == "BTicino SHARK board (Dig-D/Car-C)"
    assert "model_id" not in info and "sw_version" not in info

    # An agent that reports neither leaves the device as release 2.10.0 showed it.
    plain = _FakeEntry(runtime_data=_FakeRuntimeData(agent_info={"model": "C300X", "firmware": "2.0.2"}))
    assert dict(C300XEntity(plain, "test").device_info) == {  # type: ignore[arg-type]
        "identifiers": {("bticino_c300x", plain.entry_id)}, "manufacturer": "BTicino",
        "model": "Classe 300X", "name": plain.title, "sw_version": "2.0.2",
    }
    for empty in (None, "", "  "):
        blank = _FakeEntry(runtime_data=_FakeRuntimeData(agent_info={"board": empty, "article": empty}))
        info = C300XEntity(blank, "test").device_info  # type: ignore[arg-type]
        assert "hw_version" not in info and "model_id" not in info


def test_device_info_omits_empty_firmware_version() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(agent_info={"firmware": ""}),
    )
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]

    assert "sw_version" not in entity.device_info


def test_base_entity_deduplicates_unchanged_connection_state_writes() -> None:
    entry = _FakeEntry()
    entity = C300XEntity(entry, "test")  # type: ignore[arg-type]
    writes: list[str] = []
    entity.async_write_ha_state = lambda: writes.append("write")  # type: ignore[method-assign]

    entity._handle_c300x_connection_state_changed(entry.entry_id)
    entry.runtime_data.connection_state.available = False
    entity._handle_c300x_connection_state_changed(entry.entry_id)
    entity._handle_c300x_connection_state_changed(entry.entry_id)
    entry.runtime_data.connection_state.available = True
    entity._handle_c300x_connection_state_changed(entry.entry_id)
    entity._handle_c300x_connection_state_changed("other-entry")

    assert writes == ["write", "write"]
