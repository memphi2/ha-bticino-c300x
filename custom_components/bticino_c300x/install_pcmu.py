"""A new installation switches a Classe 300X on firmware 1.7.x or 2.0.2 to PCMU.

The station runs Speex there from the factory, and a codec switch goes live
only with a station restart. A new installation restarts the station once
for it, at its end:

- The setup marks the entry it creates when it installed the agent on such a
  station itself. An agent that was there already, a reinstall, an agent
  update and every existing entry keep their codec. Firmware 3.0.x runs PCMU
  from the factory and a Classe 100X stays on Speex: neither gets the mark.
- The first start of the marked entry, after the media user and the Display
  setting reached the station, waits until no call or stream runs, writes
  the switch without a restart and asks the agent for its one restart. The
  agent restarts at once, so the wait is Home Assistant's: the station's own
  call state, the agent's calls and its media bridge must all be idle. The
  routing program that the media-user setup replaced starts with that
  restart as well.
- A write that fails leaves the station on Speex and restarts nothing. The
  mark goes before the restart is asked for, so no later start restarts the
  station a second time.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api_errors import C300XAgentApiError
from .capabilities import entry_maintenance_action_is_advertised
from .const import CONF_INSTALL_PCMU_PENDING, DOMAIN, SIGNAL_AUDIO_CODEC_STATUS
from .device_profile import entry_profile, reported_model, setup_profile
from .entry_locks import entry_lock
from .error_text import compact_error_text

_LOGGER = logging.getLogger(__name__)

# The text of the setup's last dialog: config.create_entry.pcmu_restart.
PCMU_RESTART_TEXT = "pcmu_restart"
IDLE_POLL_SECONDS = 30.0
# A station call state without its end frame counts for at most this long,
# as a call does in the agent's restart gate of the Classe 100X.
_STATION_STATE_HOLD_MS = 600_000
_LIVE_CALLS = frozenset({"ringing", "answered", "viewing"})
# The agent's own reading of a busy camera (camera_update_guard.c).
_MEDIA_BUSY = (
    "call_active", "clients", "media_starting", "media_active", "stop_in_progress",
    "external_media_active", "ring_call_active", "ring_media_active", "ring_audio_active",
    "ring_answer_requested", "home_call_active", "home_call_running", "talkback_running",
)


class InstallPcmuSteps:
    """The setup's part: the entry of a new installation carries the mark."""

    _setup_bootstrapped: bool
    _setup_agent_info: dict[str, Any]
    # The setup installed the agent again over one whose keys were lost.
    _setup_reinstall: bool = False

    def _install_switches_to_pcmu(self) -> bool:
        info = self._setup_agent_info
        return (
            self._setup_bootstrapped
            and not self._setup_reinstall
            # A station that named neither model nor display is not judged.
            and reported_model(info) is not None
            and setup_profile(info).installs_pcmu
        )

    def async_create_entry(
        self, *, title: str | None = None, data: Mapping[str, Any], **kwargs: Any,
    ) -> ConfigFlowResult:
        if self._install_switches_to_pcmu():
            data = {**data, CONF_INSTALL_PCMU_PENDING: True}
            kwargs.setdefault("description", PCMU_RESTART_TEXT)
            kwargs.setdefault("description_placeholders", {"model": setup_profile(self._setup_agent_info).model})
        return cast(ConfigFlowResult, super().async_create_entry(  # type: ignore[misc]
            title=title, data=data, **kwargs,
        ))


def install_pcmu_pending(entry: Any) -> bool:
    """Whether this entry's first start still owes the switch of its new installation."""

    data = getattr(entry, "data", None)
    return isinstance(data, Mapping) and data.get(CONF_INSTALL_PCMU_PENDING) is True


@callback
def async_start_install_pcmu(hass: HomeAssistant, entry: Any) -> None:
    """Switch a new installation to PCMU in the background, once the station is idle."""

    if install_pcmu_pending(entry):
        entry.async_create_background_task(
            hass, async_switch_install_pcmu(hass, entry), f"{DOMAIN}_install_pcmu_{entry.entry_id}",
        )


async def async_switch_install_pcmu(
    hass: HomeAssistant, entry: Any, *, poll_seconds: float = IDLE_POLL_SECONDS,
) -> None:
    """Write PCMU without a restart, then ask the agent for the one restart."""

    from .agent_update import async_retry_update_maintenance_busy

    lock = entry_lock(entry.entry_id, "install_pcmu")
    if lock.locked():
        return
    async with lock:
        if not install_pcmu_pending(entry):
            return
        reason = _not_switched(entry)
        if reason is not None:
            _LOGGER.info("C300X stays on its audio codec: %s", reason)
            _async_clear_mark(hass, entry)
            return
        api = entry.runtime_data.api
        # The station is asked again while a call or stream runs.
        while True:
            if await _async_station_idle(api):
                break
            await asyncio.sleep(poll_seconds)
        try:
            status = await async_retry_update_maintenance_busy(
                lambda: api.async_apply_audio_codec(reboot=False)
            )
        except C300XAgentApiError as err:
            _LOGGER.warning(
                "C300X stays on Speex: the PCMU switch of the new installation failed: %s",
                compact_error_text(err),
            )
            _async_clear_mark(hass, entry)
            return
        _async_clear_mark(hass, entry)
        if not isinstance(status, Mapping):
            _LOGGER.warning("C300X stays on Speex: the agent did not answer the PCMU switch")
            return
        async_dispatcher_send(hass, SIGNAL_AUDIO_CODEC_STATUS, entry.entry_id, status)
        if status.get("configured_state", status.get("state")) != "pcmu":
            _LOGGER.warning(
                "C300X stays on Speex: the agent reports the codec %s after the PCMU switch",
                status.get("configured_state", status.get("state")),
            )
            return
        if status.get("reboot_required") is not True:
            _LOGGER.info("C300X runs PCMU already; it does not restart")
            return
        try:
            await async_retry_update_maintenance_busy(api.async_reboot)
        except C300XAgentApiError as err:
            _LOGGER.warning(
                "C300X did not restart: PCMU is set and runs after the next restart of the station: %s",
                compact_error_text(err),
            )
            return
        _LOGGER.info("C300X restarts once to switch its sound to PCMU")


def _not_switched(entry: Any) -> str | None:
    """Why this start does not switch, as the agent now reports the station."""

    if not entry_profile(entry).installs_pcmu:
        return "the station is no Classe 300X on firmware 1.7.x or 2.0.2"
    if not entry_maintenance_action_is_advertised(entry, "audio_codec_apply"):
        return "the agent offers no codec switch"
    if not entry_maintenance_action_is_advertised(entry, "reboot"):
        return "the agent offers no station restart"
    return None


async def _async_station_idle(api: Any) -> bool:
    """No call and no stream: the station's state, the agent's calls and its media bridge."""

    try:
        calls = await api.async_calls()
        video = await api.async_doorbell_video_status()
    except C300XAgentApiError as err:
        _LOGGER.debug("C300X call state for the PCMU restart not read: %s", compact_error_text(err))
        return False
    if any(call.state in _LIVE_CALLS for call in calls.calls):
        return False
    station = calls.station_state
    if (
        station is not None
        and station.state != "idle"
        and (station.age_ms or 0) < _STATION_STATE_HOLD_MS
    ):
        return False
    bridge = video.bridge if isinstance(video.bridge, Mapping) else {}
    return not any(bridge.get(key) for key in _MEDIA_BUSY)


@callback
def _async_clear_mark(hass: HomeAssistant, entry: Any) -> None:
    data = {key: value for key, value in entry.data.items() if key != CONF_INSTALL_PCMU_PENDING}
    hass.config_entries.async_update_entry(entry, data=data)
