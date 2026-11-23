"""Update filesystem failures retain endpoint/status identity through Repairs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from test_agent_update_repairs import (
    FakeEntry,
    FakeHass,
    FakePatchApi,
    FakeRuntimeData,
    FakeSelfUpdateState,
)
from test_api import _FakeSession

from custom_components.bticino_c300x import repairs
from custom_components.bticino_c300x.agent_update import (
    async_retry_update_maintenance_busy,
)
from custom_components.bticino_c300x.api import C300XAgentApi
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentUpdateError,
)

UPDATE = "/api/v1/maintenance/update/apply"
ERRORS = [
    (409, "update_root_already_writable"),
    (500, "update_root_readonly_failed"),
    (500, "update_apply_failed"),
]
CASES = [
    (UPDATE, status, {"error": code}, code) for status, code in ERRORS
] + [
    (UPDATE, 500 if status == 409 else 409, {"error": code}, "update_failed")
    for status, code in ERRORS
] + [
    (path, status, {"error": code}, "update_failed")
    for status, code in ERRORS
    for path in ("/api/v1/maintenance/qml-patch/actions/apply", "/api/v1/maintenance/update-other/apply")
] + [
    (UPDATE, 500, payload, "update_failed")
    for payload in (
        {"error": "write_failed"}, {"error": "update_apply_failed extra"},
        {"message": "update_apply_failed"}, {"detail": "update_apply_failed"},
        {"error": 500}, {"error": ["update_apply_failed"]}, [], None,
    )
]


@pytest.mark.parametrize("path,status,payload,key", CASES)
def test_update_failure_contract_is_structured_and_does_not_retry(path, status, payload, key):
    session = _FakeSession(json.dumps(payload), response_status=status)
    api = C300XAgentApi(session, "http://device.invalid", "token")
    with pytest.raises(C300XAgentApiConnectionError) as caught:
        asyncio.run(async_retry_update_maintenance_busy(lambda: api._request_json("POST", path)))
    error = caught.value
    if path == UPDATE:
        assert isinstance(error, C300XAgentUpdateError)
        assert error.status == status
        raw_code = payload.get("error") if isinstance(payload, dict) else None
        assert error.code == (raw_code if isinstance(raw_code, str) else None)
        assert error.repair_key == key
    else:
        assert not isinstance(error, C300XAgentUpdateError)
    assert len(session.requests) == 1


@pytest.mark.parametrize("path,status,payload,key", CASES)
def test_repair_shows_specific_update_failure_without_followup(
    monkeypatch, path, status, payload, key,
):
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    hass = FakeHass(entry)
    session = _FakeSession(json.dumps(payload), response_status=status)
    api = C300XAgentApi(session, "http://device.invalid", "token")

    async def update(*args):
        return await async_retry_update_maintenance_busy(lambda: api._request_json("POST", path))

    async def forbidden(*args):
        pytest.fail("A refused or uncertain update must not trigger follow-up actions")

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", update)
    monkeypatch.setattr(repairs, "_async_verify_agent_after_update", forbidden)
    monkeypatch.setattr(repairs, "_async_restore_external_patch_state", forbidden)
    monkeypatch.setattr(repairs, "_async_migrate_mqtt_after_update", forbidden)
    flow = repairs.DeviceAgentUpdateRepairFlow(hass, entry.entry_id)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    initial = asyncio.run(flow.async_step_confirm())
    assert initial["type"] == "form"
    assert not session.requests
    result = asyncio.run(flow.async_step_confirm({}))
    assert result["step_id"] == "confirm"
    assert result["errors"] == {"base": key}
    assert len(session.requests) == 1
    assert hass.config_entries.reloads == []
    assert entry.data == {}
    assert set(entry.runtime_data.api.calls) <= {"qml_status", "firewall_status", "ipv6_firewall_status"}


def test_repair_does_not_guess_update_cause_from_exception_text(monkeypatch):
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()

    async def update(*args):
        raise C300XAgentApiConnectionError("device agent returned HTTP 500: update_apply_failed")

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", update)
    flow = repairs.DeviceAgentUpdateRepairFlow(FakeHass(entry), entry.entry_id)
    flow.async_show_form = lambda **kwargs: kwargs
    assert asyncio.run(flow.async_step_confirm({}))["errors"] == {"base": "update_failed"}


@pytest.mark.parametrize("language", ["strings", "en", "de", "fr", "it"])
def test_update_root_repair_translations_preserve_failure_distinctions(language):
    component = Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x"
    relative = "strings.json" if language == "strings" else f"translations/{language}.json"
    messages = json.loads((component / relative).read_text())["issues"]["device_agent_update_required"]["fix_flow"]["error"]
    for _status, key in ERRORS:
        assert messages[key]
        assert "{" not in messages[key]
    hints = {
        "strings": ("before applying", "uncertain", "cause and final device state are unknown", "If you previously"),
        "en": ("before applying", "uncertain", "cause and final device state are unknown", "If you previously"),
        "de": ("vor dem Anwenden", "ungewiss", "Ursache und endgültiger Gerätezustand sind unbekannt", "Falls du"),
        "fr": ("avant application", "incertain", "la cause et l'état final de l'appareil sont inconnus", "Si vous"),
        "it": ("prima dell'applicazione", "incerto", "la causa e lo stato finale del dispositivo sono sconosciuti", "Se in precedenza"),
    }
    early, uncertain, unknown, conditional = hints[language]
    assert early in messages["update_root_already_writable"]
    assert uncertain in messages["update_root_readonly_failed"]
    assert unknown in messages["update_apply_failed"]
    assert conditional in messages["update_apply_failed"]
    if language == "en":
        base = json.loads((component / "strings.json").read_text())
        assert messages == base["issues"]["device_agent_update_required"]["fix_flow"]["error"]
