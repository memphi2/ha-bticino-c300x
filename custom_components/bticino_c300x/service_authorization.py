"""Authorize HA callers separately from the trusted physical display bridge."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any

from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import Unauthorized, UnknownUser
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .dashboard_config import configured_alarm_entity_id
from .entity import entry_entity_unique_id

_CAMERA_SERVICES = {
    "activate_doorbell_video",
    "stop_doorbell_video",
    "answer_doorbell_call",
    "hangup_doorbell_call",
    "start_home_call",
    "stop_home_call",
}


def authorized_service[T](
    hass: HomeAssistant,
    name: str,
    handler: Callable[[ServiceCall], Awaitable[T]],
    resolve_entry: Callable[[ServiceCall], Any],
) -> Callable[[ServiceCall], Coroutine[Any, Any, T]]:
    """Fail closed for services without an entity-level authorization contract."""

    @wraps(handler)
    async def checked(call: ServiceCall) -> T:
        context = getattr(call, "context", None)
        if context is not None and context.user_id:
            user = await hass.auth.async_get_user(context.user_id)
            if user is None:
                raise UnknownUser(context=context)
            if not user.is_admin and name != "run_action":
                entity_id = _control_entity(hass, name, call, resolve_entry)
                if entity_id is None or not user.permissions.check_entity(
                    entity_id, POLICY_CONTROL
                ):
                    raise Unauthorized(context=context)
        return await handler(call)

    return checked


def _control_entity(
    hass: HomeAssistant,
    name: str,
    call: ServiceCall,
    resolve_entry: Callable[[ServiceCall], Any],
) -> str | None:
    if name == "alarm_command":
        return configured_alarm_entity_id(resolve_entry(call))
    domain = "button"
    if name == "unlock_door":
        lock_id = call.data.get("lock_id", "default")
        key = "door_unlock" if lock_id == "default" else f"door_unlock_{lock_id}"
    elif name == "stair_light" and not call.data.get("address"):
        key = "stair_light"
    elif name == "run_device_activation":
        key = f"device_activation_{call.data['activation_id']}"
    elif name in _CAMERA_SERVICES:
        domain, key = "camera", "doorbell_camera"
    else:
        # Maintenance, file analysis, notifications and stored-message operations
        # have no equivalent control entity with matching authority.
        return None
    entry = resolve_entry(call)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        domain, DOMAIN, entry_entity_unique_id(entry, key)
    )
    registered = registry.async_get(entity_id) if entity_id else None
    return entity_id if registered is not None and not registered.disabled_by else None
