"""The C100X display shows no memos and asks the agent for none (owner decision 2026-11-24)."""

from types import SimpleNamespace

import pytest
from test_c100x_qml_adapter import ROOT, builder
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original


def test_original_firmware_has_no_memo_page_to_read_a_text_memo_on():
    original("c100x-1.5.8")
    root = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino"
    # The vendor store exists, but the station's own display has no page for it.
    assert b"/home/bticino/cfg/extra/47/memos_text" in (root / "bin/bt_answering_machine").read_bytes()
    assert not (root / "bin/gui/skins/default/MemoPage.qml").exists()


def test_adapter_ships_no_memo_page_script_or_request(tmp_path):
    assert not (ROOT / "device_qml/c100x/C100XMemos.qml").exists()
    assert not (ROOT / "device_qml/c100x/js/c100x_memos.js").exists()
    builder.build(tmp_path)
    delivered = sorted(path for path in tmp_path.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    assert len(delivered) > 20
    for path in delivered:
        assert "memo" not in path.name.lower(), path
        text = path.read_text()
        assert "/ui/memos" not in text and "C100XMemos" not in text and "c300x_memos" not in text, path
    manifest = (tmp_path / "SHA256SUMS").read_text()
    assert "memo" not in manifest.lower()


MODELS = [("C100X", {"model": "C100X", "display_kind": "qt5_ondisk"}), ("C300X", {"model": "C300X"})]


def _setup(model, info):
    import c100x_answering_capabilities

    return {**info, "version": "2.9.1", "capabilities": dict(getattr(c100x_answering_capabilities, model))}


def _entry():
    from types import MappingProxyType

    return SimpleNamespace(entry_id="entry", data={}, options=MappingProxyType({}), update_listeners=[],
                           runtime_data=SimpleNamespace(agent_info={}, capabilities={}))


def _hass():
    def update(entry, *, data, options=None):
        entry.data = data

    return SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))


def _check(model, capabilities):
    from custom_components.bticino_c300x.capabilities import (
        events_for_capabilities,
        memo_text_write_supported,
        memos_supported,
    )

    wanted = model == "C300X"
    assert memos_supported(capabilities) is wanted
    assert memo_text_write_supported(capabilities) is wanted
    assert ("memos.changed" in events_for_capabilities(capabilities)) is wanted
    if wanted:
        import c100x_answering_capabilities

        assert capabilities["memos"] == c100x_answering_capabilities.C300X["memos"]


@pytest.mark.parametrize("model,info", MODELS)
def test_setup_gates_the_memo_capabilities_by_the_model_the_agent_reports(monkeypatch, model, info):
    import asyncio
    from unittest.mock import AsyncMock

    from custom_components.bticino_c300x import agent_update, runtime_manager

    async def bundle(_hass):
        return {}

    monkeypatch.setattr(agent_update, "async_load_packaged_bundle_metadata", bundle)
    entry = _entry()
    manager = runtime_manager.C300XRuntimeManager(_hass(), entry)
    manager.api = SimpleNamespace(async_validate_setup=AsyncMock(return_value=_setup(model, info)))
    asyncio.run(manager.async_validate_agent())
    assert manager.connection_state.available
    _check(model, manager.capabilities)


@pytest.mark.parametrize("model,info", MODELS)
def test_a_repaired_agent_gates_the_memo_capabilities_by_its_model(monkeypatch, model, info):
    import asyncio

    from custom_components.bticino_c300x import repairs

    async def bundle(_hass):
        return {}

    monkeypatch.setattr(repairs, "async_load_packaged_bundle_metadata", bundle)
    monkeypatch.setattr(repairs, "async_dispatcher_send", lambda *args: None)
    entry = _entry()
    asyncio.run(repairs._async_apply_repaired_agent_setup(_hass(), entry, _setup(model, info)))
    assert entry.runtime_data.agent_info["model"] == model
    _check(model, entry.runtime_data.capabilities)
