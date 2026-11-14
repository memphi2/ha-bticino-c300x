"""Tiles step of the display dashboard settings.

The form has one section per tile, in the order the display shows them: page
by page, and within a page in the order of its entities. A section is titled
with the page and the name of the entity. The Alarmo quick entity is on no
page and comes last; it has a name and a secondary line, but no size.

Section titles and field labels cannot come from the translation files,
because Home Assistant looks them up by a fixed key and the sections here
depend on the chosen entities. They are the keys of the form instead: the
titles are built from the names of the entities, the labels are read from
the ``tile_field`` selector translations in the language of Home Assistant.
The choices of each field are translated by the frontend as usual.

A posted form is turned back into the per-entity fields the dashboard
settings are built from, see ``config_flow_dashboard``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.data_entry_flow import section

from .config_flow_dashboard import (
    dashboard_display_entity_ids,
    dashboard_entity_display_field_names,
)
from .config_flow_dashboard_pages import dashboard_page_layout
from .config_flow_forms import (
    dashboard_entity_secondary_info_selector as _secondary_selector,
)
from .config_flow_forms import (
    dashboard_entity_tile_size_selector as _size_selector,
)
from .config_flow_forms import (
    dashboard_tile_name_selector as _name_selector,
)
from .const import (
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS,
    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
    DOMAIN,
)
from .dashboard_entities import (
    DASHBOARD_STATUS_PAGE,
    DASHBOARD_TILE_SIZE_AUTO,
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_entity_ids,
)
from .schema_compat import vol

TILE_LABEL_TRANSLATION_KEY = "tile_field"
# English labels, used when Home Assistant has no translation to offer.
TILE_LABELS: dict[str, str] = {
    "width": "Width",
    "height": "Height",
    "name": "Name",
    "secondary": "Secondary line",
    "status_page": "Status page",
    "alarm_page": "Alarm page",
}
_SIZE_FIELDS = ("width", "height")
# With more tiles than this the sections start collapsed, as a list to pick from.
_OPEN_SECTIONS_MAX = 2


@dataclass(frozen=True)
class TileForm:
    """The tiles form and what it takes to read a post of it."""

    schema: vol.Schema
    # Section title -> entity, in display order.
    sections: dict[str, str]
    labels: dict[str, str]
    # Per section the values the form shows, keyed by field.
    shown: dict[str, dict[str, str]] = field(default_factory=dict)
    # Per entity the per-entity fields of the dashboard settings.
    fields: dict[str, dict[str, str]] = field(default_factory=dict)

    def entity_fields(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Return a post as the per-entity fields of the dashboard settings.

        A section or a field the post lacks keeps the value the form showed,
        so a tile is never reset because its section was not sent.
        """

        result: dict[str, Any] = {}
        for title, entity_id in self.sections.items():
            posted = user_input.get(title)
            posted = posted if isinstance(posted, dict) else {}
            values = {
                key: str(posted.get(self.labels[key], shown) or "").strip()
                for key, shown in self.shown[title].items()
            }
            names = self.fields[entity_id]
            for size in _SIZE_FIELDS:
                if size in values:
                    result[names[size]] = values[size] or DASHBOARD_TILE_SIZE_AUTO
            name = values["name"] or DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME
            # Anything that is not one of the choices is a name of its own.
            custom = name not in DASHBOARD_ENTITY_NAME_DISPLAY_OPTIONS or (
                name == DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM
            )
            result[names["name"]] = (
                DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM if custom else name
            )
            result[names["custom_name"]] = (
                name if custom and name != DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM else ""
            )
            result[names["secondary"]] = (
                values["secondary"] or DASHBOARD_ENTITY_SECONDARY_INFO_STATE
            )
        return result


def tile_entity_name(entity_id: str, hass: Any = None) -> str:
    """Return the name a tile's section shows for its entity."""

    states = getattr(hass, "states", None)
    state = states.get(entity_id) if states is not None else None
    name = str(getattr(state, "name", "") or "").strip()
    if name:
        return name
    return entity_id.split(".", 1)[-1].replace("_", " ").strip().title() or entity_id


async def async_tile_labels(hass: Any = None) -> dict[str, str]:
    """Return the field labels in the language of Home Assistant."""

    labels = dict(TILE_LABELS)
    language = getattr(getattr(hass, "config", None), "language", None)
    if not language:
        return labels
    try:
        from homeassistant.helpers.translation import async_get_translations

        translations = await async_get_translations(
            hass, language, "selector", {DOMAIN}
        )
    except Exception:  # noqa: BLE001 - the form works with the English labels
        return labels
    prefix = f"component.{DOMAIN}.selector.{TILE_LABEL_TRANSLATION_KEY}.options."
    for key in labels:
        translated = str(translations.get(prefix + key) or "").strip()
        if translated:
            labels[key] = translated
    # Two fields with the same label would be one field of the form.
    shown = [labels[key] for key in ("width", "height", "name", "secondary")]
    return labels if len(set(shown)) == len(shown) else dict(TILE_LABELS)


def tile_form(
    dashboard_input: dict[str, Any],
    overrides: Any = None,
    *,
    labels: dict[str, str] | None = None,
    hass: Any = None,
) -> TileForm:
    """Return the tiles form for the chosen pages and entities."""

    labels = {**TILE_LABELS, **(labels or {})}
    saved = normalize_dashboard_entity_display_overrides(overrides)
    shown_entities = dashboard_display_entity_ids(dashboard_input)
    on_pages = set(
        normalize_dashboard_entity_ids(dashboard_input.get(CONF_DASHBOARD_ENTITIES, []))
    )
    ordered: list[tuple[str, str]] = []
    # The layout lists the status page first; the display follows the positions.
    for page in sorted(dashboard_page_layout(dashboard_input), key=lambda page: page["order"]):
        page_name = (
            labels["status_page"]
            # An entity without a page is shown on the status page.
            if page["name"] in ("", DASHBOARD_STATUS_PAGE)
            else page["name"]
        )
        ordered += [(page_name, entity_id) for entity_id in page["entities"]]
    placed = {entity_id for _, entity_id in ordered}
    ordered += [
        (labels["alarm_page"], entity_id)
        for entity_id in shown_entities
        if entity_id not in placed
    ]

    form = TileForm(
        schema=vol.Schema({}),
        sections={},
        labels=labels,
        fields=dashboard_entity_display_field_names(shown_entities),
    )
    schema: dict[Any, Any] = {}
    collapsed = len(ordered) > _OPEN_SECTIONS_MAX
    for group, entity_id in ordered:
        title = f"{group} › {tile_entity_name(entity_id, hass)}"
        if title in form.sections:
            title = f"{title} ({entity_id})"
        options = saved.get(entity_id, {})
        name = options.get("name", DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME)
        if name == DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM:
            name = options.get("custom_name") or DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME
        values: dict[str, str] = {}
        selectors: dict[str, Any] = {}
        if entity_id in on_pages:
            for size in _SIZE_FIELDS:
                values[size] = options.get(size, DASHBOARD_TILE_SIZE_AUTO)
                selectors[size] = _size_selector()
        values["name"] = name
        selectors["name"] = _name_selector()
        values["secondary"] = options.get(
            "secondary", DASHBOARD_ENTITY_SECONDARY_INFO_STATE
        )
        selectors["secondary"] = _secondary_selector()
        form.sections[title] = entity_id
        form.shown[title] = values
        schema[vol.Required(title)] = section(
            vol.Schema(
                {
                    vol.Optional(labels[key], default=value): selectors[key]
                    for key, value in values.items()
                }
            ),
            {"collapsed": collapsed},
        )
    return TileForm(
        schema=vol.Schema(schema),
        sections=form.sections,
        labels=labels,
        shown=form.shown,
        fields=form.fields,
    )


async def async_tile_form(
    flow: Any,
    dashboard_input: dict[str, Any],
    overrides: Any,
) -> TileForm:
    """Build the tiles form and keep it on the flow for reading the post."""

    hass = getattr(flow, "hass", None)
    form = tile_form(
        dashboard_input,
        overrides,
        labels=await async_tile_labels(hass),
        hass=hass,
    )
    flow._tile_form = form
    return form


async def async_tile_entity_fields(
    flow: Any,
    dashboard_input: dict[str, Any],
    user_input: dict[str, Any],
) -> dict[str, Any]:
    """Return a posted tiles form as the per-entity display fields.

    The post is read with the form that was shown, so a name that changed in
    between does not move a tile's settings to another entity.
    """

    form: TileForm = getattr(flow, "_tile_form", None) or await async_tile_form(
        flow,
        dashboard_input,
        dashboard_input.get(CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {}),
    )
    return form.entity_fields(user_input)
