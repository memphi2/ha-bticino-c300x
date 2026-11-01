"""Exercise production schemas with real HA, isolated from module stubs."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", ["backend", "forms", "services", "websockets"])
def test_schemas_with_real_home_assistant(case: str) -> None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), case],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _probe(case: str, config_dir: str) -> None:
    from homeassistant import data_entry_flow
    from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
    from homeassistant.core import HomeAssistant

    modern = (MAJOR_VERSION, MINOR_VERSION) >= (2026, 9)
    if not modern:
        # A dependency installing Probatio must not change an older HA's engine.
        sys.modules["probatio"] = ModuleType("probatio")

    from custom_components.bticino_c300x import camera, schema_compat
    from custom_components.bticino_c300x.schema_compat import vol

    assert modern == schema_compat.HA_USES_PROBATIO
    assert issubclass(data_entry_flow.InvalidData, vol.Invalid)
    assert camera.CameraEntityFeature.STREAM
    hass = HomeAssistant(config_dir)

    if case == "backend":
        from homeassistant.helpers import config_validation as cv

        from custom_components.bticino_c300x.activation_address import (
            normalize_stair_light_part,
        )
        from custom_components.bticino_c300x.config_audio import audio_gain_db
        from custom_components.bticino_c300x.service_schema import wyoming_port

        for validator in (
            cv.entity_id,
            audio_gain_db,
            wyoming_port,
            lambda value: normalize_stair_light_part(value, default="00"),
        ):
            with pytest.raises(vol.Invalid):
                validator("invalid!")
        return

    if case == "forms":
        from homeassistant.helpers.data_entry_flow import FlowManagerIndexView

        from custom_components.bticino_c300x.config_flow_input import (
            _setup_connection_schema,
        )
        from custom_components.bticino_c300x.config_schemas import setup_features_schema
        from custom_components.bticino_c300x.const import CONF_DOORSTATION_AUDIO_GAIN_DB
        from custom_components.bticino_c300x.repair_flows_frontend import (
            _frontend_card_setup_schema,
        )

        class ProbeFlow(data_entry_flow.FlowHandler):
            async def async_step_init(self, user_input=None):
                if user_input is not None:
                    return self.async_create_entry(title="Probe", data=user_input)
                return self.async_show_form(
                    step_id="init", data_schema=setup_features_schema(True),
                )

        class ProbeManager(data_entry_flow.FlowManager):
            async def async_create_flow(self, handler_key, *, context=None, data=None):
                return ProbeFlow()

            async def async_finish_flow(self, flow, result):
                return result

        manager = ProbeManager(hass)
        form = await manager.async_init("schema_probe")
        view = FlowManagerIndexView(manager)
        for schema in (
            form["data_schema"],
            _setup_connection_schema("Doorbell", "doorbell.example.test", 8091, ""),
            _frontend_card_setup_schema(hass),
        ):
            assert isinstance(schema, vol.Schema)
            serialized = view._prepare_result_json({**form, "data_schema": schema})
            assert serialized["data_schema"]
            json.dumps(serialized)
        with pytest.raises(data_entry_flow.InvalidData):
            await manager.async_configure(
                form["flow_id"], {CONF_DOORSTATION_AUDIO_GAIN_DB: "invalid!"},
            )
        result = await manager.async_configure(
            form["flow_id"], {CONF_DOORSTATION_AUDIO_GAIN_DB: 0},
        )
        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_DOORSTATION_AUDIO_GAIN_DB] == 0
        return

    if case == "services":
        from custom_components.bticino_c300x.const import SERVICE_WRITE_TEXT_MEMO
        from custom_components.bticino_c300x.services import (
            _base_service_specs,
            _C300XServiceHandlers,
        )

        calls = []

        async def record(call):
            calls.append(call.data)

        for name, _handler, schema in _base_service_specs(_C300XServiceHandlers(hass)):
            assert isinstance(schema, vol.Schema)
            hass.services.async_register("schema_probe", name, record, schema=schema)
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                "schema_probe", SERVICE_WRITE_TEXT_MEMO, {"text": ""}, blocking=True,
            )
        assert not calls
        await hass.services.async_call(
            "schema_probe", SERVICE_WRITE_TEXT_MEMO,
            {"text": "Line 1\r\nLine 2", "read": "yes"}, blocking=True,
        )
        assert calls == [{"text": "Line 1\nLine 2", "read": True}]
        return

    assert case == "websockets"
    from homeassistant.components import websocket_api

    from custom_components.bticino_c300x.camera_media.home_call_ws import (
        async_register_home_call_ws,
    )
    from custom_components.bticino_c300x.debug_ws import async_register_debug_ws

    async_register_debug_ws(hass)
    async_register_home_call_ws(hass, camera.C300XDoorbellCamera)
    registered = hass.data[websocket_api.DOMAIN]
    command = "bticino_c300x/home_call/webrtc/candidate"
    schema = registered[command][1]
    message = {
        "id": 1, "type": command, "entity_id": "camera.doorbell",
        "session_id": "test", "candidate": {"candidate": ""},
    }
    assert schema(message)["candidate"].candidate == ""
    with pytest.raises(vol.Invalid):
        schema({**message, "candidate": "invalid!"})
    with pytest.raises(vol.Invalid):
        schema({**message, "entity_id": "invalid!"})


if __name__ == "__main__":
    with TemporaryDirectory(prefix="c300x-schema-probe-") as directory:
        asyncio.run(_probe(sys.argv[1], directory))
