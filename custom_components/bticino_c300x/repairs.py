"""Home Assistant Repairs flows for BTicino C300X."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .agent_update import (
    agent_update_repair_placeholders,
    async_apply_packaged_agent_update,
    compare_agent_bundle,
)
from .api import C300XAgentApiError
from .callback_url import async_suggest_callback_base_url, normalize_callback_base_url
from .capabilities import (
    entry_device_ui_enabled,
    gate_capabilities,
    maintenance_action_is_advertised,
    qml_patch_status_is_active,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_CALLBACK_BASE_URL,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
    CONF_FRONTEND_CARD_SETUP_DISMISSED,
    CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION,
    CONF_MAINTENANCE_TOKEN,
    CONF_VIDEO_ENABLED,
    DEFAULT_AGENT_PORT,
    DEFAULT_STAIR_LIGHT_ADDRESS,
    DEVICE_ACTIVATION_MODE_AUTO,
    DOMAIN,
    FRONTEND_CARD_SETUP_REPAIR_VERSION,
    SIGNAL_AGENT_INFO_CHANGED,
    SIGNAL_QML_PATCH_CHANGED,
)
from .device_installer import (
    C300XDeviceInstallRequest,
    async_install_device_agent,
)
from .device_user import homeassistant_account_label
from .entry_config import entry_config_value
from .frontend import async_setup_frontend
from .mqtt_migration import async_migrate_legacy_mqtt_if_available
from .qml_patch import (
    async_apply_qml_core_patch_and_confirm,
    async_apply_qml_patch_and_confirm,
)
from .repair_issues import (
    DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
    DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
    DEVICE_USER_REQUIRED_ISSUE,
    FRONTEND_CARD_SETUP_HINT_ISSUE,
    UNSUPPORTED_CALLBACK_URL_ISSUE,
    repair_issue_id,
)

_AGENT_UPDATE_RESTART_SETTLE_SECONDS = 1.0
_DOORBELL_CALL_CARD_TYPE = "custom:c300x-doorbell-call-card"
_DOORBELL_CAMERA_UNIQUE_ID_SUFFIX = "doorbell_camera"
_LOVELACE_DASHBOARD_FIELD = "dashboard_path"
_LOVELACE_DEFAULT_DASHBOARD_VALUE = "__default__"
_LOVELACE_VIEW_FIELD = "view_path"
_LOVELACE_C300X_VIEW_PATH = "c300x"
_LOVELACE_C300X_VIEW_TITLE = "C300X"


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a C300X repair flow."""

    if (
        data is not None
        and data.get("issue_type") == DEVICE_AGENT_UPDATE_REQUIRED_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return DeviceAgentUpdateRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == UNSUPPORTED_CALLBACK_URL_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return CallbackUrlRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return DeviceCoreQmlHookRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == DEVICE_USER_REQUIRED_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return DeviceUserRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == FRONTEND_CARD_SETUP_HINT_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return FrontendCardSetupRepairFlow(hass, str(data["entry_id"]))
    raise ValueError(f"unknown repair issue: {issue_id}")


class FrontendCardSetupRepairFlow(RepairsFlow):
    """Repair flow that adds the bundled C300X Lovelace cards."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the repair flow."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")
        return self.async_show_menu(
            step_id="init",
            menu_options=("confirm", "ignore"),
            description_placeholders=_frontend_card_setup_placeholders(entry),
        )

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Add the C300X cards to a storage Lovelace dashboard."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")
        placeholders = _frontend_card_setup_placeholders(entry)
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=_frontend_card_setup_schema(self.hass),
                description_placeholders=placeholders,
            )
        try:
            dashboard_path, view_path = _normalize_lovelace_target(
                user_input.get(_LOVELACE_DASHBOARD_FIELD),
                user_input.get(_LOVELACE_VIEW_FIELD),
            )
            await async_setup_frontend(self.hass)
            created_path = await _async_setup_lovelace_cards(
                self.hass,
                entry,
                dashboard_path=dashboard_path,
                view_path=view_path,
            )
        except _LovelaceCardSetupError as err:
            return self.async_show_form(
                step_id="confirm",
                data_schema=_frontend_card_setup_schema(
                    self.hass,
                    dashboard_path=_submitted_dashboard_path(user_input),
                    view_path=_submitted_view_path(user_input),
                ),
                errors={"base": err.error_key},
                description_placeholders=placeholders,
            )
        _mark_frontend_card_setup_dismissed(self.hass, entry)
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(FRONTEND_CARD_SETUP_HINT_ISSUE, self._entry_id),
        )
        return self.async_create_entry(data={"dashboard_path": created_path})

    async def async_step_ignore(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Persistently ignore the Lovelace card setup hint."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")
        _mark_frontend_card_setup_dismissed(self.hass, entry)
        issue_id = repair_issue_id(
            FRONTEND_CARD_SETUP_HINT_ISSUE,
            self._entry_id,
        )
        if hasattr(ir, "async_ignore_issue"):
            with suppress(KeyError):
                ir.async_ignore_issue(self.hass, DOMAIN, issue_id, True)
        else:  # pragma: no cover - older HA/test stub fallback
            ir.async_delete_issue(
                hass=self.hass,
                domain=DOMAIN,
                issue_id=issue_id,
            )
        return self.async_create_entry(data={"ignored": True})


class _LovelaceCardSetupError(Exception):
    """Raised when Lovelace cards cannot be added automatically."""

    def __init__(self, error_key: str) -> None:
        super().__init__(error_key)
        self.error_key = error_key


class DeviceUserRepairFlow(RepairsFlow):
    """Repair flow that creates or repairs the dedicated HA media user."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the repair flow."""

        return await self.async_step_confirm(user_input)

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Create or repair the Home Assistant Flexisip user."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")
        if user_input is None:
            return self.async_show_form(step_id="confirm")
        try:
            status = await entry.runtime_data.api.async_ensure_homeassistant_user(
                account_label=homeassistant_account_label(self.hass)
            )
        except C300XAgentApiError:
            return self.async_show_form(
                step_id="confirm",
                errors={"base": "device_user_setup_failed"},
            )
        entry.runtime_data.device_user_status = status
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, self._entry_id),
        )
        return self.async_create_entry(data={})


async def _async_setup_lovelace_cards(
    hass: HomeAssistant,
    entry: Any,
    *,
    dashboard_path: str | None = None,
    view_path: str = _LOVELACE_C300X_VIEW_PATH,
) -> str:
    """Add the C300X call cards to a storage Lovelace dashboard."""

    camera_entity_id = _resolve_doorbell_camera_entity_id(hass, entry)
    if camera_entity_id is None:
        raise _LovelaceCardSetupError("camera_entity_missing")

    dashboard_path, dashboard = _storage_lovelace_dashboard(hass, dashboard_path)
    try:
        config = await dashboard.async_load(False)
    except Exception:  # noqa: BLE001 - storage dashboards may still be auto-generated
        config = {"views": []}
    if not isinstance(config, dict):
        raise _LovelaceCardSetupError("lovelace_config_invalid")
    views = config.setdefault("views", [])
    if not isinstance(views, list):
        raise _LovelaceCardSetupError("lovelace_config_invalid")

    config_changed = False
    view = _c300x_view(views, view_path)
    if view is None:
        view = _empty_placeholder_view(views)
        if view is None:
            view = _new_c300x_view(view_path)
            views.append(view)
        else:
            view.clear()
            view.update(_new_c300x_view(view_path))
        config_changed = True
    else:
        config_changed = _remove_empty_placeholder_views(views, keep=view)

    if _dashboard_has_c300x_cards(view, camera_entity_id):
        if config_changed:
            await dashboard.async_save(config)
        return _lovelace_dashboard_path(dashboard_path, view_path)

    cards = _cards_for_view(view)
    if not _dashboard_has_c300x_card(view, camera_entity_id, "home_call"):
        cards.append(_home_call_card(camera_entity_id))
    if not _dashboard_has_c300x_card(view, camera_entity_id, "doorbell_call"):
        cards.append(_doorbell_card(camera_entity_id))

    await dashboard.async_save(config)
    return _lovelace_dashboard_path(dashboard_path, view_path)


def _storage_lovelace_dashboard(
    hass: HomeAssistant,
    requested_path: str | None = None,
) -> tuple[str | None, Any]:
    """Return the preferred storage Lovelace dashboard."""

    dashboards, storage_mode = _storage_lovelace_dashboards(hass)
    if requested_path is not None:
        dashboard = dashboards.get(requested_path)
        if (
            getattr(dashboard, "mode", None) == storage_mode
            and hasattr(dashboard, "async_load")
            and hasattr(dashboard, "async_save")
        ):
            return requested_path, dashboard
        raise _LovelaceCardSetupError("lovelace_storage_unavailable")
    for path in (None, *sorted(item for item in dashboards if item is not None)):
        dashboard = dashboards.get(path)
        if (
            getattr(dashboard, "mode", None) == storage_mode
            and hasattr(dashboard, "async_load")
            and hasattr(dashboard, "async_save")
        ):
            return path, dashboard
    raise _LovelaceCardSetupError("lovelace_storage_unavailable")


def _storage_lovelace_dashboards(hass: HomeAssistant) -> tuple[dict[Any, Any], Any]:
    """Return Lovelace dashboards and the storage mode sentinel."""

    try:
        from homeassistant.components.lovelace.const import (  # noqa: PLC0415
            LOVELACE_DATA,
            MODE_STORAGE,
        )
    except (ImportError, ModuleNotFoundError) as err:
        raise _LovelaceCardSetupError("lovelace_unavailable") from err
    lovelace_data = hass.data.get(LOVELACE_DATA) if hasattr(hass, "data") else None
    dashboards = getattr(lovelace_data, "dashboards", None)
    if not isinstance(dashboards, dict):
        raise _LovelaceCardSetupError("lovelace_unavailable")
    return dashboards, MODE_STORAGE


def _resolve_doorbell_camera_entity_id(hass: HomeAssistant, entry: Any) -> str | None:
    """Resolve the doorbell camera entity for a config entry."""

    try:
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError):
        return None
    registry = er.async_get(hass)
    if registry is None or not hasattr(registry, "async_get_entity_id"):
        return None
    entity_id = registry.async_get_entity_id(
        "camera",
        DOMAIN,
        f"{entry.entry_id}_{_DOORBELL_CAMERA_UNIQUE_ID_SUFFIX}",
    )
    return entity_id if isinstance(entity_id, str) else None


def _c300x_view(views: list[Any], view_path: str) -> dict[str, Any] | None:
    """Return the existing C300X Lovelace view."""

    for view in views:
        if not isinstance(view, dict):
            continue
        if (
            view.get("path") == view_path
            or (
                view_path == _LOVELACE_C300X_VIEW_PATH
                and view.get("title") == _LOVELACE_C300X_VIEW_TITLE
            )
        ):
            return view
    return None


def _new_c300x_view(view_path: str) -> dict[str, Any]:
    """Return a Home Assistant sections view for C300X cards."""

    return {
        "type": "sections",
        "title": _LOVELACE_C300X_VIEW_TITLE,
        "path": view_path,
        "sections": [{"type": "grid", "cards": []}],
    }


def _empty_placeholder_view(views: list[Any]) -> dict[str, Any] | None:
    """Return the first empty HA-created placeholder view."""

    for view in views:
        if isinstance(view, dict) and _is_empty_placeholder_view(view):
            return view
    return None


def _remove_empty_placeholder_views(
    views: list[Any],
    *,
    keep: dict[str, Any],
) -> bool:
    """Remove HA-created placeholder views before an existing C300X view."""

    original_len = len(views)
    views[:] = [
        view
        for view in views
        if view is keep
        or not (isinstance(view, dict) and _is_empty_placeholder_view(view))
    ]
    return len(views) != original_len


def _is_empty_placeholder_view(view: dict[str, Any]) -> bool:
    """Return true for HA's empty default sections view."""

    if view.get("path") or view.get("title"):
        return False
    sections = view.get("sections")
    if not isinstance(sections, list):
        return False
    if not sections:
        return True
    for section in sections:
        if not isinstance(section, dict):
            return False
        cards = section.get("cards")
        if not isinstance(cards, list):
            return False
        for card in cards:
            if not isinstance(card, dict):
                return False
            if card.get("type") != "heading":
                return False
            heading = str(card.get("heading") or "").strip().lower()
            if heading not in {"", "new section"}:
                return False
    return True


def _cards_for_view(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the card list where generated cards should be added."""

    sections = view.setdefault("sections", [{"type": "grid", "cards": []}])
    if isinstance(sections, list) and sections:
        section = sections[0]
        if isinstance(section, dict):
            cards = section.setdefault("cards", [])
            if isinstance(cards, list):
                return cards
    cards = view.setdefault("cards", [])
    if isinstance(cards, list):
        return cards
    raise _LovelaceCardSetupError("lovelace_config_invalid")


def _dashboard_has_c300x_cards(config: dict[str, Any], camera_entity_id: str) -> bool:
    """Return true when both generated C300X card modes already exist."""

    return _dashboard_has_c300x_card(
        config,
        camera_entity_id,
        "home_call",
    ) and _dashboard_has_c300x_card(config, camera_entity_id, "doorbell_call")


def _dashboard_has_c300x_card(
    config: dict[str, Any],
    camera_entity_id: str,
    mode: str,
) -> bool:
    """Return true when a generated C300X card mode already exists."""

    for card in _iter_lovelace_cards(config):
        if not isinstance(card, dict):
            continue
        if card.get("type") != _DOORBELL_CALL_CARD_TYPE:
            continue
        if card.get("entity") != camera_entity_id:
            continue
        card_mode = str(card.get("mode") or "doorbell_call")
        if card_mode == mode:
            return True
    return False


def _iter_lovelace_cards(value: Any):
    """Yield cards from a Lovelace config tree."""

    if isinstance(value, dict):
        if "type" in value:
            yield value
        for key in ("views", "sections", "cards", "entities"):
            yield from _iter_lovelace_cards(value.get(key))
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_lovelace_cards(item)


def _home_call_card(camera_entity_id: str) -> dict[str, Any]:
    """Return the generated Home Call Lovelace card config."""

    return {
        "type": _DOORBELL_CALL_CARD_TYPE,
        "entity": camera_entity_id,
        "mode": "home_call",
        "name": "C300X Home Call",
        "grid_options": {"columns": 6, "rows": 1},
    }


def _doorbell_card(camera_entity_id: str) -> dict[str, Any]:
    """Return the generated Doorbell / On-demand Lovelace card config."""

    return {
        "type": _DOORBELL_CALL_CARD_TYPE,
        "entity": camera_entity_id,
        "grid_options": {"columns": 12, "rows": 7},
    }


def _lovelace_dashboard_path(
    path: str | None,
    view_path: str = _LOVELACE_C300X_VIEW_PATH,
) -> str:
    """Return the frontend path to the created C300X view."""

    dashboard_path = "lovelace" if path is None else path
    return f"/{dashboard_path}/{view_path}"


def _frontend_card_setup_schema(
    hass: HomeAssistant,
    *,
    dashboard_path: str | None = None,
    view_path: str = _LOVELACE_C300X_VIEW_PATH,
) -> vol.Schema:
    """Return the Lovelace card setup repair form schema."""

    dashboard_default = _dashboard_selector_value(dashboard_path)
    view_default = view_path or _LOVELACE_C300X_VIEW_PATH
    return vol.Schema(
        {
            vol.Required(
                _LOVELACE_DASHBOARD_FIELD,
                default=dashboard_default,
            ): _dashboard_selector(hass),
            vol.Required(
                _LOVELACE_VIEW_FIELD,
                default=view_default,
            ): _text_selector(),
        }
    )


def _dashboard_selector(hass: HomeAssistant) -> Any:
    """Return a dashboard selector, falling back to plain text in tests."""

    try:
        from homeassistant.helpers import selector  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError):
        return str
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=_dashboard_select_options(hass),
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _text_selector() -> Any:
    """Return a text selector, falling back to plain text in tests."""

    try:
        from homeassistant.helpers import selector  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError):
        return str
    return selector.TextSelector(selector.TextSelectorConfig())


def _dashboard_select_options(hass: HomeAssistant) -> list[dict[str, str]]:
    """Return storage-mode dashboard options for the repair form."""

    try:
        dashboards, storage_mode = _storage_lovelace_dashboards(hass)
    except _LovelaceCardSetupError:
        return [
            {
                "value": _LOVELACE_DEFAULT_DASHBOARD_VALUE,
                "label": "Lovelace (/lovelace)",
            }
        ]
    options: list[dict[str, str]] = []
    for path in (None, *sorted(item for item in dashboards if item is not None)):
        dashboard = dashboards.get(path)
        if getattr(dashboard, "mode", None) != storage_mode:
            continue
        config = getattr(dashboard, "config", None)
        label = (
            config.get("title")
            if isinstance(config, dict) and isinstance(config.get("title"), str)
            else None
        ) or (
            "Lovelace" if path is None else str(path)
        )
        options.append(
            {
                "value": _dashboard_selector_value(path),
                "label": f"{label} ({_lovelace_dashboard_path(path, '').rstrip('/')})",
            }
        )
    return options or [
        {
            "value": _LOVELACE_DEFAULT_DASHBOARD_VALUE,
            "label": "Lovelace (/lovelace)",
        }
    ]


def _dashboard_selector_value(path: str | None) -> str:
    """Return the repair-form value for a Lovelace dashboard path."""

    return _LOVELACE_DEFAULT_DASHBOARD_VALUE if path is None else path


def _normalize_lovelace_target(
    dashboard_path: Any,
    view_path: Any,
) -> tuple[str | None, str]:
    """Normalize dashboard and view input from the repair flow."""

    dashboard = None
    dashboard_value = str(dashboard_path or _LOVELACE_DEFAULT_DASHBOARD_VALUE).strip()
    if dashboard_value and dashboard_value != _LOVELACE_DEFAULT_DASHBOARD_VALUE:
        dashboard = dashboard_value.strip("/")
    view = str(view_path or _LOVELACE_C300X_VIEW_PATH).strip()
    if view.startswith("/"):
        parts = [part for part in view.strip("/").split("/") if part]
        if len(parts) >= 2:
            dashboard = None if parts[0] == "lovelace" else parts[0]
            view = parts[1]
        elif parts:
            view = parts[0]
    view = view.strip("/")
    if not view or "/" in view:
        raise _LovelaceCardSetupError("lovelace_config_invalid")
    return dashboard, view


def _submitted_dashboard_path(user_input: dict[str, Any]) -> str | None:
    """Return the submitted dashboard path for form defaults."""

    try:
        dashboard, _view = _normalize_lovelace_target(
            user_input.get(_LOVELACE_DASHBOARD_FIELD),
            None,
        )
    except _LovelaceCardSetupError:
        return None
    return dashboard


def _submitted_view_path(user_input: dict[str, Any]) -> str:
    """Return the submitted view path for form defaults."""

    value = str(user_input.get(_LOVELACE_VIEW_FIELD) or "").strip().strip("/")
    return value or _LOVELACE_C300X_VIEW_PATH


def _frontend_card_setup_placeholders(entry: Any) -> dict[str, str]:
    """Return Lovelace card setup repair description placeholders."""

    return {
        "dashboard_path": _lovelace_dashboard_path(None),
        "entry_title": str(getattr(entry, "title", "") or entry.entry_id),
    }


def _mark_frontend_card_setup_dismissed(hass: HomeAssistant, entry: Any) -> None:
    """Persist that the Lovelace card setup hint has been handled."""

    if (
        entry.options.get(CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION)
        == FRONTEND_CARD_SETUP_REPAIR_VERSION
    ):
        return
    hass.config_entries.async_update_entry(
        entry,
        options={
            **dict(entry.options),
            CONF_FRONTEND_CARD_SETUP_DISMISSED: True,
            CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION: (
                FRONTEND_CARD_SETUP_REPAIR_VERSION
            ),
        },
    )


class CallbackUrlRepairFlow(RepairsFlow):
    """Repair flow for callback targets the C300X cannot reach."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the callback URL repair flow."""

        return await self.async_step_configure(user_input)

    async def async_step_configure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Store a local HTTP callback base URL override."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")

        errors: dict[str, str] = {}
        if user_input is not None:
            callback_base_url = _validated_callback_base_url(user_input, errors)
            if callback_base_url:
                self.hass.config_entries.async_update_entry(
                    entry,
                    options={
                        **dict(entry.options),
                        CONF_CALLBACK_BASE_URL: callback_base_url,
                    },
                )
                ir.async_delete_issue(
                    hass=self.hass,
                    domain=DOMAIN,
                    issue_id=repair_issue_id(
                        UNSUPPORTED_CALLBACK_URL_ISSUE,
                        self._entry_id,
                    ),
                )
                await _async_reload_entry_after_agent_update(self.hass, self._entry_id)
                return self.async_create_entry(data={})
            errors[CONF_CALLBACK_BASE_URL] = "invalid_callback_base_url"

        suggested = await async_suggest_callback_base_url(self.hass, entry)
        return self.async_show_form(
            step_id="configure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CALLBACK_BASE_URL,
                        default=suggested,
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "suggested_callback_base_url": suggested or "http://HA_LOCAL_IP:8123",
            },
        )


class DeviceCoreQmlHookRepairFlow(RepairsFlow):
    """Repair flow for the core media QML hook used by video session tracking."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the repair flow."""

        return await self.async_step_confirm(user_input)

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Apply the minimal core QML hook after explicit confirmation."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        capabilities = getattr(entry.runtime_data, "capabilities", {})
        if not maintenance_action_is_advertised(capabilities, "qml_core_patch"):
            return self.async_abort(reason="core_patch_unsupported")
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "qml_patch_status": _runtime_qml_patch_status(entry),
                },
            )
        try:
            status = await async_apply_qml_core_patch_and_confirm(
                entry,
                lambda: async_dispatcher_send(
                    self.hass,
                    SIGNAL_QML_PATCH_CHANGED,
                    entry.entry_id,
                ),
            )
        except C300XAgentApiError:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "core_patch_failed"},
                description_placeholders={
                    "qml_patch_status": _runtime_qml_patch_status(entry),
                },
            )
        if status.get("core_patched") is not True:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "core_patch_verify_failed"},
                description_placeholders={
                    "qml_patch_status": _runtime_qml_patch_status(entry),
                },
            )
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(
                DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
                self._entry_id,
            ),
        )
        return self.async_create_entry(data={})


class DeviceAgentUpdateRepairFlow(RepairsFlow):
    """Explicit user-confirmed native-agent update repair flow."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the repair flow."""

        return await self.async_step_confirm()

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Confirm and run a device-agent self-update."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        update_state = getattr(entry.runtime_data, "agent_update_state", None)
        placeholders = agent_update_repair_placeholders(update_state, entry.runtime_data)
        if not getattr(update_state, "self_update_repair_supported", False):
            return await self.async_step_ssh_install(user_input)
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders=placeholders,
            )
        try:
            patch_state = await _async_capture_external_patch_state(entry)
            update_result = await async_apply_packaged_agent_update(
                self.hass,
                entry.runtime_data.api,
            )
            setup_data = await _async_verify_agent_after_update(
                entry.runtime_data.api,
                update_result,
            )
            changes = _ExternalPatchChanges.from_update_result(update_result)
            if changes.config_schema_changed:
                await entry.runtime_data.api.async_normalize_agent_config()
                setup_data = await entry.runtime_data.api.async_validate_setup()
            await _async_restore_external_patch_state(
                entry,
                patch_state,
                changes,
            )
            await async_migrate_legacy_mqtt_if_available(entry.runtime_data.api)
            setup_data = await entry.runtime_data.api.async_validate_setup()
        except Exception:  # noqa: BLE001 - Repairs shows a translated failure
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "update_failed"},
                description_placeholders=placeholders,
            )
        await _async_apply_repaired_agent_setup(self.hass, entry, setup_data)
        if entry.runtime_data.agent_update_state.update_required:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "update_verify_failed"},
                description_placeholders=agent_update_repair_placeholders(
                    entry.runtime_data.agent_update_state,
                    entry.runtime_data,
                ),
            )
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, self._entry_id),
        )
        await _async_reload_entry_after_agent_update(self.hass, self._entry_id)
        return self.async_create_entry(data={})

    async def async_step_ssh_install(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Repair an older agent by reinstalling the packaged bundle over SSH."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        update_state = getattr(entry.runtime_data, "agent_update_state", None)
        placeholders = agent_update_repair_placeholders(update_state, entry.runtime_data)
        if user_input is None:
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(),
                description_placeholders=placeholders,
            )

        try:
            patch_state = await _async_capture_external_patch_state(entry)
            install_result = await async_install_device_agent(
                C300XDeviceInstallRequest(
                    host=str(entry_config_value(entry, CONF_AGENT_HOST, "")).strip(),
                    ssh_username=str(
                        user_input.get(CONF_BOOTSTRAP_SSH_USERNAME, "")
                    ).strip(),
                    ssh_password=str(user_input.get(CONF_BOOTSTRAP_SSH_PASSWORD, "")),
                    agent_port=int(
                        entry_config_value(entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)
                    ),
                    apply_firewall_patch=(
                        patch_state.firewall_patched
                        or not patch_state.firewall_status_known
                    ),
                    apply_gui_patch=False,
                    device_activation_mode=str(
                        entry_config_value(
                            entry,
                            CONF_DEVICE_ACTIVATION_MODE,
                            DEVICE_ACTIVATION_MODE_AUTO,
                        )
                    ),
                    device_activation_stair_light_address=str(
                        entry_config_value(
                            entry,
                            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
                            DEFAULT_STAIR_LIGHT_ADDRESS,
                        )
                    ),
                ),
                api_token=str(entry_config_value(entry, CONF_AGENT_TOKEN, "")),
                maintenance_token=str(
                    entry_config_value(entry, CONF_MAINTENANCE_TOKEN, "")
                ),
            )
            setup_data = await _async_wait_for_agent_after_update(entry.runtime_data.api)
            await _async_restore_external_patch_state(
                entry,
                patch_state,
                _ExternalPatchChanges.from_install_result(install_result),
            )
            await async_migrate_legacy_mqtt_if_available(entry.runtime_data.api)
            setup_data = await entry.runtime_data.api.async_validate_setup()
        except Exception:  # noqa: BLE001 - Repairs shows a translated failure
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(),
                errors={"base": "ssh_install_failed"},
                description_placeholders=placeholders,
            )

        await _async_apply_repaired_agent_setup(self.hass, entry, setup_data)
        if entry.runtime_data.agent_update_state.update_required:
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(),
                errors={"base": "update_verify_failed"},
                description_placeholders=agent_update_repair_placeholders(
                    entry.runtime_data.agent_update_state,
                    entry.runtime_data,
                ),
            )
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, self._entry_id),
        )
        await _async_reload_entry_after_agent_update(self.hass, self._entry_id)
        return self.async_create_entry(data={})


async def _async_wait_for_agent_after_update(
    api: Any,
    *,
    initial_delay: float = 0.0,
) -> dict[str, Any]:
    """Wait briefly for the native agent to restart after self-update."""

    last_error: Exception | None = None
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
    for _attempt in range(12):
        try:
            return await api.async_validate_setup()
        except Exception as err:  # noqa: BLE001 - retry during controlled restart
            last_error = err
            await asyncio.sleep(1)
    if last_error is not None:
        raise last_error
    raise RuntimeError("agent update verification failed")


async def _async_verify_agent_after_update(
    api: Any,
    update_result: dict[str, Any],
) -> dict[str, Any]:
    """Verify the native agent after an update, waiting only after restarts."""

    if update_result.get("restart_scheduled") is True:
        return await _async_wait_for_agent_after_update(
            api,
            initial_delay=_AGENT_UPDATE_RESTART_SETTLE_SECONDS,
        )
    return await api.async_validate_setup()


async def _async_apply_repaired_agent_setup(
    hass: HomeAssistant,
    entry: Any,
    setup_data: dict[str, Any],
) -> None:
    """Update runtime metadata after a successful agent repair."""

    from .agent_update import async_load_packaged_bundle_metadata

    capabilities = setup_data.get("capabilities", {})
    if not isinstance(capabilities, dict):
        capabilities = {}
    entry.runtime_data.agent_info = setup_data
    entry.runtime_data.capabilities = gate_capabilities(
        capabilities,
        doorbell_video_enabled=bool(entry_config_value(entry, CONF_VIDEO_ENABLED, False)),
    )
    entry.runtime_data.agent_update_state = compare_agent_bundle(
        setup_data,
        await async_load_packaged_bundle_metadata(hass),
    )
    async_dispatcher_send(hass, SIGNAL_AGENT_INFO_CHANGED, entry.entry_id)


async def _async_reload_entry_after_agent_update(
    hass: HomeAssistant,
    entry_id: str,
) -> None:
    """Reload the entry so newly advertised platforms/entities are created."""

    with suppress(Exception):
        await hass.config_entries.async_reload(entry_id)


class _ExternalPatchState:
    """Read-only snapshot of device-side patches that must survive updates."""

    def __init__(
        self,
        *,
        qml_patch_required: bool,
        firewall_patched: bool,
        firewall_status_known: bool,
        ipv6_firewall_patched: bool,
    ) -> None:
        self.qml_patch_required = qml_patch_required
        self.firewall_patched = firewall_patched
        self.firewall_status_known = firewall_status_known
        self.ipv6_firewall_patched = ipv6_firewall_patched


class _ExternalPatchChanges:
    """Logical device-artifact changes produced by an agent update/install."""

    def __init__(
        self,
        *,
        qml_patch_changed: bool = False,
        firewall_patch_changed: bool = False,
        ipv6_firewall_patch_changed: bool = False,
        config_schema_changed: bool = False,
    ) -> None:
        self.qml_patch_changed = qml_patch_changed
        self.firewall_patch_changed = firewall_patch_changed
        self.ipv6_firewall_patch_changed = ipv6_firewall_patch_changed
        self.config_schema_changed = config_schema_changed

    @classmethod
    def from_update_result(cls, update_result: dict[str, Any]) -> _ExternalPatchChanges:
        """Return changed groups reported by native self-update."""

        return cls(
            qml_patch_changed=update_result.get("qml_patch_changed") is True,
            firewall_patch_changed=update_result.get("firewall_patch_changed") is True,
            ipv6_firewall_patch_changed=(
                update_result.get("ipv6_firewall_patch_changed") is True
            ),
            config_schema_changed=update_result.get("config_schema_changed") is True,
        )

    @classmethod
    def from_install_result(cls, install_result: Any) -> _ExternalPatchChanges:
        """Return changed groups from the SSH installer result."""

        changed_files = tuple(getattr(install_result, "changed_files", ()))
        config_changed = any(path.endswith("/config.json") for path in changed_files)
        firewall_source_changed = any(
            path.endswith("/bootstrap_firewall.sh") for path in changed_files
        )
        qml_changed = any(
            "/qml/" in path or path.endswith("/qml_patch.sh")
            for path in changed_files
        )
        return cls(
            qml_patch_changed=qml_changed,
            firewall_patch_changed=firewall_source_changed,
            ipv6_firewall_patch_changed=config_changed or firewall_source_changed,
            config_schema_changed=config_changed,
        )


async def _async_capture_external_patch_state(entry: Any) -> _ExternalPatchState:
    """Capture active patch state without mutating the device."""

    api = entry.runtime_data.api
    qml_status = getattr(entry.runtime_data, "qml_patch_status", {})
    try:
        qml_status = await api.async_qml_patch_status()
        entry.runtime_data.qml_patch_status = qml_status
    except C300XAgentApiError:
        pass

    firewall_patched = False
    firewall_status_known = False
    try:
        firewall_status = await api.async_firewall_status()
        firewall_patched = firewall_status.get("patched") is True
        firewall_status_known = firewall_status.get("patched") is not None
    except C300XAgentApiError:
        pass

    ipv6_firewall_patched = False
    try:
        ipv6_firewall_status = await api.async_ipv6_firewall_status()
        ipv6_firewall_patched = ipv6_firewall_status.get("patched") is True
    except C300XAgentApiError:
        pass

    return _ExternalPatchState(
        qml_patch_required=(
            entry_device_ui_enabled(entry) or qml_patch_status_is_active(qml_status)
        ),
        firewall_patched=firewall_patched,
        firewall_status_known=firewall_status_known,
        ipv6_firewall_patched=ipv6_firewall_patched,
    )


async def _async_restore_external_patch_state(
    entry: Any,
    patch_state: _ExternalPatchState,
    changed: _ExternalPatchChanges,
) -> None:
    """Re-apply active external patches only when their patch source changed."""

    api = entry.runtime_data.api
    if patch_state.firewall_patched and changed.firewall_patch_changed:
        await api.async_apply_firewall()
    if patch_state.ipv6_firewall_patched and changed.ipv6_firewall_patch_changed:
        with suppress(C300XAgentApiError):
            await api.async_set_ipv6_firewall_enabled(True)
        await api.async_apply_ipv6_firewall()
    if changed.qml_patch_changed:
        entry.runtime_data.qml_patch_status = await api.async_apply_qml_core_patch()
        if patch_state.qml_patch_required:
            await async_apply_qml_patch_and_confirm(entry)


def _ssh_install_schema() -> vol.Schema:
    """Return the SSH repair schema for agents without self-update support."""

    return vol.Schema(
        {
            vol.Required(CONF_BOOTSTRAP_SSH_USERNAME): str,
            vol.Required(CONF_BOOTSTRAP_SSH_PASSWORD): str,
        }
    )


def _validated_callback_base_url(
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> str:
    """Validate a required local callback base URL for the repair flow."""

    try:
        return normalize_callback_base_url(user_input.get(CONF_CALLBACK_BASE_URL, ""))
    except ValueError:
        errors[CONF_CALLBACK_BASE_URL] = "invalid_callback_base_url"
        return ""


def _runtime_qml_patch_status(entry: Any) -> str:
    status = getattr(getattr(entry, "runtime_data", None), "qml_patch_status", {})
    if isinstance(status, dict):
        core_state = str(status.get("core_state") or "").strip()
        if core_state:
            return core_state
        state = str(status.get("state") or "").strip()
        if state:
            return state
    return "unknown"
