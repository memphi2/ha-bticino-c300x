"""Config-flow helpers for additional C300X device activations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config_schemas import (
    device_activation_item_schema,
    device_activation_manage_schema,
)
from .const import (
    CONF_DEVICE_ACTIVATION_FLOW_ACTION,
    CONF_DEVICE_ACTIVATION_FLOW_TARGET,
    CONF_DEVICE_ACTIVATION_ITEM_ADDRESS,
    CONF_DEVICE_ACTIVATION_ITEM_ID,
    CONF_DEVICE_ACTIVATION_ITEM_NAME,
    CONF_DEVICE_ACTIVATION_ITEM_TYPE,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATIONS,
    DEVICE_ACTIVATION_FLOW_ACTION_ADD,
    DEVICE_ACTIVATION_FLOW_ACTION_DONE,
    DEVICE_ACTIVATION_FLOW_ACTION_EDIT,
    DEVICE_ACTIVATION_FLOW_ACTION_REMOVE,
    DEVICE_ACTIVATION_MODE_MANUAL,
)
from .device_activations import (
    MAX_DEVICE_ACTIVATIONS,
    DeviceActivationConfigError,
    normalize_device_activations,
)

ACTIVATION_STEP_DONE = "done"
ACTIVATION_STEP_ITEM = "item"
ACTIVATION_STEP_MANAGE = "manage"


@dataclass(frozen=True, slots=True)
class ActivationStepResult:
    """Result of one activation flow sub-step."""

    next_step: str
    items: list[dict[str, Any]]
    edit_id: str | None
    errors: dict[str, str]


def activation_items_from_feature_data(
    feature_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return copied activation items from collected feature data."""

    return list(feature_data.get(CONF_DEVICE_ACTIVATIONS, []) or [])


def activation_manage_step(
    user_input: dict[str, Any] | None,
    items: list[dict[str, Any]],
) -> ActivationStepResult:
    """Handle Add/Edit/Remove/Done input for activation management."""

    if user_input is None:
        return ActivationStepResult(ACTIVATION_STEP_MANAGE, items, None, {})

    action = str(
        user_input.get(
            CONF_DEVICE_ACTIVATION_FLOW_ACTION,
            DEVICE_ACTIVATION_FLOW_ACTION_DONE,
        )
    )
    target = str(user_input.get(CONF_DEVICE_ACTIVATION_FLOW_TARGET, "")).strip()
    if action == DEVICE_ACTIVATION_FLOW_ACTION_DONE:
        return ActivationStepResult(ACTIVATION_STEP_DONE, items, None, {})
    if action == DEVICE_ACTIVATION_FLOW_ACTION_ADD:
        if len(items) >= MAX_DEVICE_ACTIVATIONS:
            return ActivationStepResult(
                ACTIVATION_STEP_MANAGE,
                items,
                None,
                {"base": "invalid_device_activations"},
            )
        return ActivationStepResult(ACTIVATION_STEP_ITEM, items, None, {})
    if action not in {
        DEVICE_ACTIVATION_FLOW_ACTION_EDIT,
        DEVICE_ACTIVATION_FLOW_ACTION_REMOVE,
    }:
        return ActivationStepResult(
            ACTIVATION_STEP_MANAGE,
            items,
            None,
            {CONF_DEVICE_ACTIVATION_FLOW_ACTION: "required"},
        )
    if not target or activation_by_id(items, target) is None:
        return ActivationStepResult(
            ACTIVATION_STEP_MANAGE,
            items,
            None,
            {CONF_DEVICE_ACTIVATION_FLOW_TARGET: "required"},
        )
    if action == DEVICE_ACTIVATION_FLOW_ACTION_REMOVE:
        return ActivationStepResult(
            ACTIVATION_STEP_MANAGE,
            activation_remove(items, target),
            None,
            {},
        )
    return ActivationStepResult(ACTIVATION_STEP_ITEM, items, target, {})


def activation_item_step(
    user_input: dict[str, Any] | None,
    items: list[dict[str, Any]],
    edit_id: str | None,
    feature_data: dict[str, Any],
) -> ActivationStepResult:
    """Handle the structured single activation item form."""

    if user_input is None:
        return ActivationStepResult(ACTIVATION_STEP_ITEM, items, edit_id, {})
    try:
        item = _activation_from_form(
            user_input,
            reserved_ids=_activation_reserved_ids(
                items,
                edit_id=edit_id,
                manual_stair_light=_activation_mode_is_manual(feature_data),
            ),
        )
    except DeviceActivationConfigError:
        return ActivationStepResult(
            ACTIVATION_STEP_ITEM,
            items,
            edit_id,
            {"base": "invalid_device_activations"},
        )
    return ActivationStepResult(
        ACTIVATION_STEP_MANAGE,
        activation_upsert(items, item, edit_id=edit_id),
        None,
        {},
    )


def activation_manage_form(
    show_form: Any,
    *,
    step_id: str,
    items: list[dict[str, Any]],
    errors: dict[str, str],
) -> dict[str, Any]:
    """Return the Home Assistant manage form result."""

    return show_form(
        step_id=step_id,
        data_schema=device_activation_manage_schema(items),
        errors=errors,
        description_placeholders=activation_placeholders(items),
    )


def activation_item_form(
    show_form: Any,
    *,
    step_id: str,
    items: list[dict[str, Any]],
    edit_id: str | None,
    errors: dict[str, str],
) -> dict[str, Any]:
    """Return the Home Assistant single-item form result."""

    return show_form(
        step_id=step_id,
        data_schema=device_activation_item_schema(activation_by_id(items, edit_id)),
        errors=errors,
    )


def activation_placeholders(items: list[dict[str, Any]]) -> dict[str, str]:
    """Return display placeholders for the activation management step."""

    return {
        "device_activation_count": str(len(items)),
        "device_activation_items": _activation_summary(items),
    }


def activation_by_id(
    items: list[dict[str, Any]],
    activation_id: str | None,
) -> dict[str, Any] | None:
    """Return one activation by id."""

    if activation_id is None:
        return None
    for item in items:
        if item.get("id") == activation_id:
            return item
    return None


def activation_upsert(
    items: list[dict[str, Any]],
    activation: dict[str, Any],
    *,
    edit_id: str | None,
) -> list[dict[str, Any]]:
    """Return items with one activation added or replaced."""

    if edit_id is None:
        return [*items, activation]
    return [activation if item.get("id") == edit_id else item for item in items]


def activation_remove(
    items: list[dict[str, Any]],
    activation_id: str,
) -> list[dict[str, Any]]:
    """Return items without one activation id."""

    return [item for item in items if item.get("id") != activation_id]


def _activation_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "None"
    return "\n".join(
        "- {id}: {name} ({type}, address {address})".format(
            id=item.get("id", ""),
            name=item.get("name", ""),
            type=item.get("type", ""),
            address=item.get("address", ""),
        )
        for item in items
    )


def _activation_reserved_ids(
    items: list[dict[str, Any]],
    *,
    edit_id: str | None,
    manual_stair_light: bool,
) -> set[str]:
    reserved = {
        str(item.get("id") or "")
        for item in items
        if item.get("id") and item.get("id") != edit_id
    }
    if manual_stair_light:
        reserved.add("stair_light")
    return reserved


def _activation_from_form(
    user_input: dict[str, Any],
    *,
    reserved_ids: set[str],
) -> dict[str, Any]:
    item = {
        "id": str(user_input.get(CONF_DEVICE_ACTIVATION_ITEM_ID, "")).strip(),
        "name": str(user_input.get(CONF_DEVICE_ACTIVATION_ITEM_NAME, "")).strip(),
        "type": str(user_input.get(CONF_DEVICE_ACTIVATION_ITEM_TYPE, "lock")).strip(),
        "addressMode": "manual",
        "address": str(user_input.get(CONF_DEVICE_ACTIVATION_ITEM_ADDRESS, "")).strip(),
    }
    return normalize_device_activations([item], reserved_ids=reserved_ids)[0]


def _activation_mode_is_manual(feature_data: dict[str, Any]) -> bool:
    return feature_data.get(CONF_DEVICE_ACTIVATION_MODE) == DEVICE_ACTIVATION_MODE_MANUAL
