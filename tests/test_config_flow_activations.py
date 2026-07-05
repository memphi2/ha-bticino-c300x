from __future__ import annotations

from custom_components.bticino_c300x.config_flow_activations import (
    ACTIVATION_STEP_MANAGE,
    activation_item_step,
    activation_manage_step,
)
from custom_components.bticino_c300x.const import (
    CONF_DEVICE_ACTIVATION_FLOW_ACTION,
    CONF_DEVICE_ACTIVATION_ITEM_ADDRESS,
    CONF_DEVICE_ACTIVATION_ITEM_ID,
    CONF_DEVICE_ACTIVATION_ITEM_NAME,
    CONF_DEVICE_ACTIVATION_ITEM_TYPE,
    CONF_DEVICE_ACTIVATION_MODE,
    DEVICE_ACTIVATION_FLOW_ACTION_ADD,
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
