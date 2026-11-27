from __future__ import annotations

from custom_components.bticino_c300x.config_flow_activations import (
    ACTIVATION_STEP_MANAGE,
    activation_item_step,
    activation_manage_step,
    activation_settings_step,
)
from custom_components.bticino_c300x.config_schemas import (
    device_activation_item_schema,
    device_activation_manage_schema,
)
from custom_components.bticino_c300x.const import (
    CONF_DEVICE_ACTIVATION_FLOW_ACTION,
    CONF_DEVICE_ACTIVATION_ITEM_ADDRESS,
    CONF_DEVICE_ACTIVATION_ITEM_ID,
    CONF_DEVICE_ACTIVATION_ITEM_NAME,
    CONF_DEVICE_ACTIVATION_ITEM_TYPE,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    DEVICE_ACTIVATION_FLOW_ACTION_ADD,
    DEVICE_ACTIVATION_FLOW_ACTION_DONE,
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODE_MANUAL,
)
from custom_components.bticino_c300x.device_activations import MAX_DEVICE_ACTIVATIONS


def _activation(index: int) -> dict[str, str]:
    return {
        "id": f"extra_{index}",
        "name": f"Extra {index}",
        "type": "lock",
        "address": str(index + 1),
        "addressMode": "manual",
    }


def test_activation_manage_step_reserves_generated_stair_light_slot() -> None:
    items = [_activation(index) for index in range(MAX_DEVICE_ACTIVATIONS - 1)]

    result = activation_manage_step(
        {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_ADD},
        items,
        max_items=MAX_DEVICE_ACTIVATIONS - 1,
    )

    assert result.next_step == ACTIVATION_STEP_MANAGE
    assert result.items == items
    assert result.errors == {"base": "invalid_device_activations"}


def test_activation_manage_step_rejects_done_when_current_mode_exceeds_limit() -> None:
    items = [_activation(index) for index in range(MAX_DEVICE_ACTIVATIONS)]

    result = activation_manage_step(
        {CONF_DEVICE_ACTIVATION_FLOW_ACTION: DEVICE_ACTIVATION_FLOW_ACTION_DONE},
        items,
        max_items=MAX_DEVICE_ACTIVATIONS - 1,
    )

    assert result.next_step == ACTIVATION_STEP_MANAGE
    assert result.items == items
    assert result.errors == {"base": "invalid_device_activations"}


def test_activation_manage_schema_contains_address_settings() -> None:
    result = device_activation_manage_schema(
        [],
        {
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "02",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "03",
        },
    )({})

    assert result[CONF_DEVICE_ACTIVATION_MODE] == DEVICE_ACTIVATION_MODE_MANUAL
    assert result[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == "02"
    assert result[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == "03"


def test_activation_settings_step_updates_address_mode_on_manage_page() -> None:
    data, errors = activation_settings_step(
        {
            CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: "2",
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: "3",
        },
        {CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_AUTO},
    )

    assert errors == {}
    assert data[CONF_DEVICE_ACTIVATION_MODE] == DEVICE_ACTIVATION_MODE_MANUAL
    assert data[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] == "02"
    assert data[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] == "03"


def test_activation_item_schema_shows_examples_for_new_items() -> None:
    fields = {getattr(key, "schema", key): key for key in device_activation_item_schema().schema}

    assert fields[CONF_DEVICE_ACTIVATION_ITEM_ID].description == {
        "suggested_value": "front_gate"
    }
    assert fields[CONF_DEVICE_ACTIVATION_ITEM_NAME].description == {
        "suggested_value": "Front gate"
    }
    assert fields[CONF_DEVICE_ACTIVATION_ITEM_ADDRESS].description == {
        "suggested_value": "10"
    }


def test_activation_item_step_rejects_stair_light_id_in_auto_mode() -> None:
    result = activation_item_step(
        {
            CONF_DEVICE_ACTIVATION_ITEM_ID: "stair_light",
            CONF_DEVICE_ACTIVATION_ITEM_NAME: "Conflicting stair light",
            CONF_DEVICE_ACTIVATION_ITEM_TYPE: "actuator",
            CONF_DEVICE_ACTIVATION_ITEM_ADDRESS: "10",
        },
        [],
        None,
        {CONF_DEVICE_ACTIVATION_MODE: "automatic"},
    )

    assert result.next_step == "item"
    assert result.errors == {"base": "invalid_device_activations"}


def test_activation_item_step_enforces_manual_mode_total_limit() -> None:
    items = [_activation(index) for index in range(MAX_DEVICE_ACTIVATIONS - 1)]

    result = activation_item_step(
        {
            CONF_DEVICE_ACTIVATION_ITEM_ID: "extra_16",
            CONF_DEVICE_ACTIVATION_ITEM_NAME: "Extra 16",
            CONF_DEVICE_ACTIVATION_ITEM_TYPE: "lock",
            CONF_DEVICE_ACTIVATION_ITEM_ADDRESS: "16",
        },
        items,
        None,
        {CONF_DEVICE_ACTIVATION_MODE: DEVICE_ACTIVATION_MODE_MANUAL},
    )

    assert result.next_step == ACTIVATION_STEP_MANAGE
    assert result.items == items
    assert result.errors == {"base": "invalid_device_activations"}


def test_the_activation_form_lists_manual_and_station_activations_apart() -> None:
    """Configured items are the manual ones; the station's come from the agent's answer."""

    from types import SimpleNamespace

    from custom_components.bticino_c300x.config_flow_activations import (
        activation_manage_form,
    )

    manual = [{"id": "gate", "name": "Gate", "type": "actuator", "address": "25"}]
    activations = {
        "items": [
            {"id": "gate", "name": "Gate", "type": "actuator", "address": "25", "source": "config"},
            {"id": "station_lock_21", "name": "Garden lock", "type": "lock", "address": "21",
             "source": "station", "unit": "21"},
            {"id": "station_stair_light", "name": "Stairs", "type": "stair_light", "address": "11",
             "source": "station", "unit": None},
        ],
    }
    entry = SimpleNamespace(runtime_data=SimpleNamespace(activations=activations))
    shown: list[dict] = []

    activation_manage_form(
        lambda **kwargs: shown.append(kwargs) or kwargs,
        step_id="device_activations",
        items=manual,
        feature_data={CONF_DEVICE_ACTIVATION_MODE: "automatic"},
        errors={},
        entry=entry,
    )

    assert shown[0]["description_placeholders"] == {
        "device_activation_count": "1",
        "device_activation_items": "- Gate (`gate`): actuator 25",
        "station_activation_count": "2",
        "station_activation_items": (
            "- Garden lock (`station_lock_21`): lock 21\n- Stairs (`station_stair_light`): stair_light 11"
        ),
    }
    # Without a loaded entry (setup) the station's list is empty.
    activation_manage_form(
        lambda **kwargs: shown.append(kwargs) or kwargs,
        step_id="user_device_activations",
        items=[],
        feature_data={},
        errors={},
    )
    assert shown[1]["description_placeholders"]["station_activation_items"] == "–"
    assert shown[1]["description_placeholders"]["device_activation_items"] == "–"


def test_reconfigure_and_options_texts_name_manual_and_station_activations() -> None:
    import json
    from pathlib import Path

    component = Path(__file__).resolve().parents[1] / "custom_components" / "bticino_c300x"
    for path in (component / "strings.json", *sorted((component / "translations").glob("*.json"))):
        data = json.loads(path.read_text(encoding="utf-8"))
        for area, step in (("options", "device_activations"), ("config", "reconfigure_device_activations")):
            description = data[area]["step"][step]["description"]
            assert "{station_activation_items}" in description, (path.name, step)
            assert "{station_activation_count}" in description, (path.name, step)
