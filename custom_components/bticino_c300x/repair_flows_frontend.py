"""Lovelace card setup repair flow for BTicino C300X."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_FRONTEND_CARD_SETUP_DISMISSED,
    CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION,
    DOMAIN,
    FRONTEND_CARD_SETUP_REPAIR_VERSION,
)
from .frontend import async_setup_frontend
from .repair_issues import FRONTEND_CARD_SETUP_HINT_ISSUE, repair_issue_id

_DOORBELL_CALL_CARD_TYPE = "custom:c300x-doorbell-call-card"
_DOORBELL_CAMERA_UNIQUE_ID_SUFFIX = "doorbell_camera"
_LOVELACE_DASHBOARD_FIELD = "dashboard_path"
_LOVELACE_DEFAULT_DASHBOARD_VALUE = "__default__"
_LOVELACE_VIEW_FIELD = "view_path"
_LOVELACE_C300X_VIEW_PATH = "c300x"
_LOVELACE_C300X_VIEW_TITLE = "C300X"


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

    config_changed = any(
        (
            _remove_state_entity_overrides_from_existing_cards(view, camera_entity_id),
            config_changed,
        )
    )
    if _dashboard_has_c300x_cards(view, camera_entity_id):
        if config_changed:
            await dashboard.async_save(config)
        return _lovelace_dashboard_path(dashboard_path, view_path)

    cards = _cards_for_view(view)
    cards.append(_doorstation_card(camera_entity_id))

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

    return _resolve_registry_entity_id(
        hass,
        "camera",
        f"{entry.entry_id}_{_DOORBELL_CAMERA_UNIQUE_ID_SUFFIX}",
    )


def _resolve_registry_entity_id(
    hass: HomeAssistant,
    domain: str,
    unique_id: str,
) -> str | None:
    """Resolve a registered entity id for one C300X unique id."""

    try:
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
    except (ImportError, ModuleNotFoundError):
        return None
    registry = er.async_get(hass)
    if registry is None or not hasattr(registry, "async_get_entity_id"):
        return None
    entity_id = registry.async_get_entity_id(
        domain,
        DOMAIN,
        unique_id,
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
    """Return true when the generated central C300X card already exists."""

    modes = _dashboard_c300x_card_modes(config, camera_entity_id)
    return "auto" in modes or {"doorbell_call", "home_call"}.issubset(modes)


def _dashboard_c300x_card_modes(
    config: dict[str, Any],
    camera_entity_id: str,
) -> set[str]:
    """Return generated C300X card modes already present in a dashboard."""

    modes: set[str] = set()
    for card in _iter_lovelace_cards(config):
        if not isinstance(card, dict):
            continue
        if card.get("type") != _DOORBELL_CALL_CARD_TYPE:
            continue
        if card.get("entity") != camera_entity_id:
            continue
        card_mode = str(card.get("mode") or "auto")
        if card_mode in {"auto", "doorbell_call", "home_call"}:
            modes.add(card_mode)
    return modes


def _remove_state_entity_overrides_from_existing_cards(
    config: dict[str, Any],
    camera_entity_id: str,
) -> bool:
    """Remove obsolete state-entity overrides from generated C300X cards."""

    changed = False
    for card in _iter_lovelace_cards(config):
        if not isinstance(card, dict):
            continue
        if card.get("type") != _DOORBELL_CALL_CARD_TYPE:
            continue
        if card.get("entity") != camera_entity_id:
            continue
        for key in ("home_call_entity", "doorbell_state_entity"):
            if key in card:
                del card[key]
                changed = True
    return changed


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


def _doorstation_card(
    camera_entity_id: str,
) -> dict[str, Any]:
    """Return the generated central doorstation Lovelace card config."""

    return {
        "type": _DOORBELL_CALL_CARD_TYPE,
        "entity": camera_entity_id,
        "mode": "auto",
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

    data_version = entry.data.get(CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION)
    options_version = entry.options.get(CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION)
    if (
        data_version == FRONTEND_CARD_SETUP_REPAIR_VERSION
        or options_version == FRONTEND_CARD_SETUP_REPAIR_VERSION
    ):
        return
    hass.config_entries.async_update_entry(
        entry,
        data={
            **dict(entry.data),
            CONF_FRONTEND_CARD_SETUP_DISMISSED: True,
            CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION: (
                FRONTEND_CARD_SETUP_REPAIR_VERSION
            ),
        },
    )
