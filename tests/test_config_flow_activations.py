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
            CONF_DEVICE_ACTIVATION_ITEM_TYPE: "light",
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
