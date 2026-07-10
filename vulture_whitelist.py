"""Vulture whitelist for the BTicino C300X integration.

Home Assistant (and PyAV) call these names dynamically -- entity properties,
entity lifecycle/interaction hooks, config-flow steps, platform entry points,
``_attr_*`` entity attributes and PyAV frame attributes -- so a static scan
cannot see the use and flags them as dead. Listing them here marks them as
used. This module is never imported at runtime; vulture only parses it.

Run:  vulture custom_components/bticino_c300x/ vulture_whitelist.py --min-confidence 60
"""

from typing import Any

_hass: Any = None

# Framework names that are called/read by Home Assistant or PyAV, grouped for review.
_ = (
    # entity properties HA reads
    _hass.current_option,
    _hass.device_info,
    _hass.entity_picture,
    _hass.is_on,
    # entity lifecycle / interaction HA calls
    _hass.async_press,
    _hass.async_select_option,
    _hass.async_set_native_value,
    _hass.async_turn_on,
    _hass.async_turn_off,
    _hass.async_will_remove_from_hass,
    # camera / media-source platform hooks
    _hass.async_camera_image,
    _hass.camera_image,
    _hass.use_stream_for_stills,
    _hass.async_browse_media,
    _hass.async_resolve_media,
    _hass.async_get_media_source,
    _hass.async_get_config_entry_diagnostics,
    # config-flow / options-flow entry points and steps
    _hass.async_get_options_flow,
    _hass.async_step_init,
    _hass.async_step_reconfigure,
    _hass.async_step_zeroconf,
    _hass.async_step_ignore,
    _hass.async_step_dashboard_entity_display,
    _hass.async_step_reconfigure_dashboard_entity_display,
    _hass.async_step_user_dashboard_entity_display,
    _hass.async_step_device_activation_item,
    _hass.async_step_reconfigure_device_activation_item,
    _hass.async_step_user_device_activation_item,
    # HA _attr_* entity attributes
    _hass._attr_device_info,
    _hass._attr_event_types,
    _hass._attr_extra_state_attributes,
    _hass._attr_icon,
    _hass._attr_name,
    _hass._attr_unique_id,
    # PyAV frame attributes (set on av frames, read by PyAV)
    _hass.pix_fmt,
    _hass.sample_rate,
    _hass.time_base,
    _hass.layout,
)
