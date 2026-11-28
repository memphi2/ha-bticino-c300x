"""Config-flow helpers for additional C300X device activations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .activation_address import normalize_stair_light_part
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
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_ACTIVATIONS,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEVICE_ACTIVATION_FLOW_ACTION_ADD,
    DEVICE_ACTIVATION_FLOW_ACTION_DONE,
    DEVICE_ACTIVATION_FLOW_ACTION_EDIT,
    DEVICE_ACTIVATION_FLOW_ACTION_REMOVE,
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODE_MANUAL,
    DEVICE_ACTIVATION_MODES,
    DOMAIN,
)
from .device_activations import (
    MAX_DEVICE_ACTIVATIONS,
    DeviceActivationConfigError,
    normalize_device_activations,
    unnamed_activation_key,
)
from .schema_compat import vol

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult as FlowResult
else:
    FlowResult = dict[str, Any]

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


def activation_settings_step(
    user_input: dict[str, Any] | None,
    feature_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Handle activation address settings from the management step."""

    if user_input is None:
        return dict(feature_data), {}

    data = dict(feature_data)
    errors: dict[str, str] = {}

    mode = str(
        user_input.get(
            CONF_DEVICE_ACTIVATION_MODE,
            data.get(CONF_DEVICE_ACTIVATION_MODE, DEVICE_ACTIVATION_MODE_AUTO),
        )
        or DEVICE_ACTIVATION_MODE_AUTO
    ).strip()
    if mode not in DEVICE_ACTIVATION_MODES:
        errors[CONF_DEVICE_ACTIVATION_MODE] = "invalid_device_activation_mode"
        mode = str(data.get(CONF_DEVICE_ACTIVATION_MODE, DEVICE_ACTIVATION_MODE_AUTO))

    try:
        stair_light_p = normalize_stair_light_part(
            user_input.get(
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
                data.get(CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P, DEFAULT_STAIR_LIGHT_P),
            ),
            default=DEFAULT_STAIR_LIGHT_P,
        )
    except vol.Invalid:
        errors[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] = "invalid_stair_light_part"
        stair_light_p = _stair_light_part_default(
            data.get(CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P, DEFAULT_STAIR_LIGHT_P),
            default=DEFAULT_STAIR_LIGHT_P,
        )

    try:
        stair_light_n = normalize_stair_light_part(
            user_input.get(
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
                data.get(CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N, DEFAULT_STAIR_LIGHT_N),
            ),
            default=DEFAULT_STAIR_LIGHT_N,
        )
    except vol.Invalid:
        errors[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] = "invalid_stair_light_part"
        stair_light_n = _stair_light_part_default(
            data.get(CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N, DEFAULT_STAIR_LIGHT_N),
            default=DEFAULT_STAIR_LIGHT_N,
        )

    data[CONF_DEVICE_ACTIVATION_MODE] = mode
    data[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] = stair_light_p
    data[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] = stair_light_n
    return data, errors


def activation_manage_step(
    user_input: dict[str, Any] | None,
    items: list[dict[str, Any]],
    *,
    max_items: int = MAX_DEVICE_ACTIVATIONS,
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
        if len(items) > _bounded_max_items(max_items):
            return ActivationStepResult(
                ACTIVATION_STEP_MANAGE,
                items,
                None,
                {"base": "invalid_device_activations"},
            )
        return ActivationStepResult(ACTIVATION_STEP_DONE, items, None, {})
    if action == DEVICE_ACTIVATION_FLOW_ACTION_ADD:
        if len(items) >= _bounded_max_items(max_items):
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
    if edit_id is None and len(items) >= activation_item_limit(feature_data):
        return ActivationStepResult(
            ACTIVATION_STEP_MANAGE,
            items,
            None,
            {"base": "invalid_device_activations"},
        )
    try:
        item = _activation_from_form(
            user_input,
            reserved_ids=_activation_reserved_ids(
                items,
                edit_id=edit_id,
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


def activation_item_limit(feature_data: dict[str, Any]) -> int:
    """Return the maximum number of user-managed activation items."""

    if _activation_mode_is_manual(feature_data):
        return MAX_DEVICE_ACTIVATIONS - 1
    return MAX_DEVICE_ACTIVATIONS


def activation_manage_form(
    show_form: Callable[..., FlowResult],
    *,
    step_id: str,
    items: list[dict[str, Any]],
    feature_data: dict[str, Any],
    errors: dict[str, str],
    entry: Any = None,
) -> FlowResult:
    """Return the Home Assistant manage form result.

    With the entry, the form also lists the station's own activations.
    """

    return show_form(
        step_id=step_id,
        data_schema=device_activation_manage_schema(items, feature_data),
        errors=errors,
        description_placeholders=activation_placeholders(
            items, station_activation_items(entry)
        ),
    )


def activation_item_form(
    show_form: Callable[..., FlowResult],
    *,
    step_id: str,
    items: list[dict[str, Any]],
    edit_id: str | None,
    errors: dict[str, str],
) -> FlowResult:
    """Return the Home Assistant single-item form result."""

    return show_form(
        step_id=step_id,
        data_schema=device_activation_item_schema(activation_by_id(items, edit_id)),
        errors=errors,
    )


def activation_placeholders(
    items: list[dict[str, Any]],
    station_items: Sequence[Mapping[str, Any]] = (),
) -> dict[str, str]:
    """Return display placeholders for the activation management step.

    ``items`` are the ones set up here (manual), ``station_items`` the ones the
    station knows from its own configuration.
    """

    return {
        "device_activation_count": str(len(items)),
        "device_activation_items": _activation_summary(items),
        "station_activation_count": str(len(station_items)),
        "station_activation_items": _activation_summary(station_items),
    }


def station_activation_items(entry: Any) -> list[Mapping[str, Any]]:
    """The station's own activations as the loaded entry read them from the agent."""

    activations = getattr(getattr(entry, "runtime_data", None), "activations", None)
    items = activations.get("items") if isinstance(activations, Mapping) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, Mapping) and item.get("source") == "station"]


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


def _activation_summary(items: Sequence[Mapping[str, Any]]) -> str:
    # Names, ids, types and bus addresses only: the form's own text names the list.
    if not items:
        return "–"
    return "\n".join(
        "- {name} (`{id}`): {type} {address}".format(
            id=item.get("id") or "",
            name=_activation_name(item),
            type=item.get("type") or "",
            address=item.get("address") or "",
        ).rstrip()
        for item in items
    )


def _activation_name(item: Mapping[str, Any]) -> str:
    """The item's name; one the station names nowhere as its button reads it.

    That is in the language of Home Assistant, from the translations it
    loaded for the entry; without them the item's id.
    """

    key = unnamed_activation_key(item)
    if key is None:
        return str(item.get("name") or "")
    from homeassistant.core import async_get_hass_or_none
    from homeassistant.helpers.translation import async_get_cached_translations

    hass = async_get_hass_or_none()
    texts = async_get_cached_translations(hass, hass.config.language, "entity", DOMAIN) if hass else {}
    text = texts.get(f"component.{DOMAIN}.entity.button.{key}.name", "")
    return text.replace("{address}", str(item["address"])) if text else str(item.get("id") or "")


def _activation_reserved_ids(
    items: list[dict[str, Any]],
    *,
    edit_id: str | None,
) -> set[str]:
    reserved = {
        str(item.get("id") or "")
        for item in items
        if item.get("id") and item.get("id") != edit_id
    }
    reserved.add("stair_light")
    return reserved


def _bounded_max_items(value: int) -> int:
    return max(0, min(value, MAX_DEVICE_ACTIVATIONS))


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


def _stair_light_part_default(value: Any, *, default: str) -> str:
    try:
        return normalize_stair_light_part(value, default=default)
    except vol.Invalid:
        return normalize_stair_light_part(default, default=default)
