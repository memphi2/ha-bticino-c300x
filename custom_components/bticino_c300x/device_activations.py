"""Device activation configuration helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .const import DEVICE_ACTIVATION_MODE_MANUAL
from .validation_patterns import ACTIVATION_ID_RE, DEVICE_ACTIVATION_ADDRESS_RE

DEVICE_ACTIVATION_TYPES = ("lock", "light", "stair_light", "generic", "scenario")
DEVICE_ACTIVATION_ADDRESS_MODES = ("manual", "auto")
MAX_DEVICE_ACTIVATIONS = 16
MAX_DEVICE_ACTIVATION_NAME_LEN = 63


class DeviceActivationConfigError(ValueError):
    """Raised when a configured device activation is invalid."""


def normalize_device_activations(
    value: Any,
    *,
    reserved_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Return validated native-agent activation items."""

    raw_items = _raw_activation_items(value)
    if len(raw_items) > MAX_DEVICE_ACTIVATIONS:
        raise DeviceActivationConfigError("too_many_device_activations")

    seen_ids = {str(item).strip() for item in reserved_ids if str(item).strip()}
    normalized: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            raise DeviceActivationConfigError("invalid_device_activation")
        item = _normalize_activation_item(raw_item)
        activation_id = item["id"]
        if activation_id in seen_ids:
            raise DeviceActivationConfigError("duplicate_device_activation_id")
        seen_ids.add(activation_id)
        normalized.append(item)
    return normalized


def activation_items_json(value: Any) -> str:
    """Return the compact native-agent JSON payload for activation items."""

    return json.dumps(normalize_device_activations(value), separators=(",", ":"))


def desired_activation_items(
    *,
    mode: str,
    stair_light_address: str,
    device_activations: Any,
) -> list[dict[str, Any]]:
    """Return the full native-agent activation item list for an entry."""

    items: list[dict[str, Any]] = []
    reserved_ids: set[str] = set()
    if mode == DEVICE_ACTIVATION_MODE_MANUAL:
        items.append(stair_light_activation(stair_light_address))
        reserved_ids.add("stair_light")
    additional_items = normalize_device_activations(
        device_activations,
        reserved_ids=reserved_ids,
    )
    if len(items) + len(additional_items) > MAX_DEVICE_ACTIVATIONS:
        raise DeviceActivationConfigError("too_many_device_activations")
    items.extend(additional_items)
    return items


def stair_light_activation(stair_light_address: str) -> dict[str, Any]:
    """Return the generated manual stair-light activation item."""

    address = str(stair_light_address or "").strip()
    if not DEVICE_ACTIVATION_ADDRESS_RE.fullmatch(address):
        raise DeviceActivationConfigError("invalid_device_activation_address")
    return {
        "id": "stair_light",
        "name": "Stair light",
        "type": "stair_light",
        "addressMode": "manual",
        "address": address,
    }


def activation_items_match(left: Sequence[Mapping[str, Any]], right: Any) -> bool:
    """Return true when two activation item lists have the same config payload."""

    try:
        return normalize_device_activations(left) == normalize_device_activations(right)
    except DeviceActivationConfigError:
        return False


def _raw_activation_items(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as err:
            raise DeviceActivationConfigError("invalid_device_activations") from err
        if decoded in (None, ""):
            return []
        if not isinstance(decoded, list):
            raise DeviceActivationConfigError("invalid_device_activations")
        return decoded
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    raise DeviceActivationConfigError("invalid_device_activations")


def _normalize_activation_item(item: Mapping[str, Any]) -> dict[str, Any]:
    activation_id = _normalized_id(item.get("id"))
    name = _normalized_name(item.get("name"))
    activation_type = str(item.get("type") or "lock").strip()
    if activation_type not in DEVICE_ACTIVATION_TYPES:
        raise DeviceActivationConfigError("invalid_device_activation_type")
    address_mode = str(
        item.get("addressMode", item.get("address_mode", "manual")) or "manual"
    ).strip()
    if address_mode not in DEVICE_ACTIVATION_ADDRESS_MODES:
        raise DeviceActivationConfigError("invalid_device_activation_address_mode")
    address = str(item.get("address") or "").strip()
    if address and not DEVICE_ACTIVATION_ADDRESS_RE.fullmatch(address):
        raise DeviceActivationConfigError("invalid_device_activation_address")
    _validate_executable_activation(activation_type, address_mode, address)
    normalized = {
        "id": activation_id,
        "name": name,
        "type": activation_type,
        "addressMode": address_mode,
    }
    if address:
        normalized["address"] = address
    return normalized


def _normalized_id(value: Any) -> str:
    activation_id = str(value or "").strip()
    if not ACTIVATION_ID_RE.fullmatch(activation_id):
        raise DeviceActivationConfigError("invalid_device_activation_id")
    return activation_id


def _normalized_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or len(name) > MAX_DEVICE_ACTIVATION_NAME_LEN:
        raise DeviceActivationConfigError("invalid_device_activation_name")
    return name


def _validate_executable_activation(
    activation_type: str,
    address_mode: str,
    address: str,
) -> None:
    if address_mode == "auto":
        return
    if activation_type in {"lock", "light", "stair_light"} and address:
        return
    raise DeviceActivationConfigError("invalid_device_activation_address")
