"""The Notify switches display, tts and led; the old mode field is gone."""

import asyncio
from itertools import product

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.bticino_c300x.display_notifications import notification_payload
from tests.test_notify import send, speech_context

COMBINATIONS = [
    combination for combination in product((False, True), repeat=3) if any(combination)
]


def effects(entry, spoken):
    """What one call did: display alert, speech, stored notices, LED snapshot."""

    alert = entry.runtime_data.api.async_send_display_alert
    store = entry.runtime_data.display_notifications
    return {
        "alerts": alert.await_count,
        "sound": alert.call_args.args[0]["sound_duration"] if alert.await_count else None,
        "spoken": len(spoken),
        "notices": len(notification_payload(entry)),
        "led": store is not None and store.has_unread(),
    }


def nothing_happened(entry, spoken):
    assert effects(entry, spoken) == {
        "alerts": 0, "sound": None, "spoken": 0, "notices": 0, "led": False,
    }


@pytest.mark.parametrize("explicit_off", [False, True], ids=["on only", "off written"])
@pytest.mark.parametrize("display,tts,led", COMBINATIONS)
def test_every_switch_combination_runs_exactly_its_channels(
    tmp_path, monkeypatch, display, tts, led, explicit_off,
):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.runtime_data.capabilities["memo_led"] = True
            switches = {"display": display, "tts": tts, "led": led}
            if not explicit_off:
                switches = {key: value for key, value in switches.items() if value}
            await send(hass, entry, data=switches)
            assert effects(entry, spoken) == {
                "alerts": int(display),
                "sound": (0 if tts else 30) if display else None,
                "spoken": int(tts),
                # The LED shows an unread notice, so led stores one too.
                "notices": int(display or led),
                "led": led,
            }
            if display:
                alert = entry.runtime_data.api.async_send_display_alert.call_args.args[0]
                assert alert["wake_duration"] == 30
            if tts:
                assert spoken[0]["media_content_id"] == (
                    "media-source://tts/default?message=Test message&language=None")
    asyncio.run(run())


@pytest.mark.parametrize("channels", [{"display": True, "tts": True}], ids=["switches"])
def test_display_and_tts_accept_a_tone_but_the_speech_replaces_it(tmp_path, monkeypatch, channels):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            await send(hass, entry, data={**channels, "sound_duration": 5, "wake_duration": 20})
            alert = entry.runtime_data.api.async_send_display_alert.call_args.args[0]
            # The tone would hold the speaker the speech needs.
            assert (alert["sound_duration"], alert["wake_duration"]) == (0, 20)
            assert len(spoken) == 1
    asyncio.run(run())


@pytest.mark.parametrize("data,switches,led", [
    (None, {"display": True}, True),
], ids=["no switches"])
def test_no_switches_mean_the_display(tmp_path, monkeypatch, data, switches, led):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.runtime_data.capabilities["memo_led"] = True
            await send(hass, entry, data=data or {})
            legacy = effects(entry, spoken)
            # The notice lights the LED, as all notices did before the switches.
            assert legacy["led"] is led
            if entry.runtime_data.display_notifications is not None:
                entry.runtime_data.display_notifications.close()
                entry.runtime_data.display_notifications = None
            entry.runtime_data.api.async_send_display_alert.reset_mock()
            spoken.clear()
            await send(hass, entry, data=switches)
            assert effects(entry, spoken) == {**legacy, "led": "led" in switches}
    asyncio.run(run())


def test_no_switches_light_the_led_without_asking_for_it(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            # No memo LED support: the old default must not start to fail.
            await send(hass, entry, data={"notification_id": "legacy"})
            await send(hass, entry, data={"display": True, "notification_id": "switch"})
            store = entry.runtime_data.display_notifications
            assert [item["led"] for item in store._items.values()] == [True, False]
            with pytest.raises(ServiceValidationError, match="memo LED support"):
                await send(hass, entry, data={"display": True, "led": True})
    asyncio.run(run())


@pytest.mark.parametrize("bad,reason", [
    # 3.1.0 removed mode; it is named instead of being ignored.
    ({"mode": "display"}, "mode was removed; use the switches display, tts and led"),
    ({"mode": "speech", "tts": True}, "mode was removed"),
    ({"mode": "led", "led": True}, "mode was removed"),
    ({"display": False}, "switch on at least one of display, tts and led"),
    ({"display": False, "tts": False, "led": False}, "switch on at least one"),
    ({"display": "true"}, "expected true or false"),
    ({"tts": 1}, "expected true or false"),
    ({"led": None}, "expected true or false"),
    ({"led": True, "wake_duration": 5}, "need display: true"),
    ({"tts": True, "sound_duration": 5}, "need display: true"),
    ({"tts": True, "led": True, "wake_duration": 1}, "need display: true"),
    ({"display": True, "tts_engine": "tts.piper"}, "need tts: true"),
    ({"led": True, "language": "de"}, "need tts: true"),
    ({"tts": True, "severity": "warning"}, "need display or led"),
    ({"tts": True, "notification_id": "door"}, "need display or led"),
    ({"tts": True, "expires_in": 60}, "need display or led"),
])
def test_invalid_switches_are_refused_before_anything_happens(tmp_path, monkeypatch, bad, reason):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.runtime_data.capabilities["memo_led"] = True
            with pytest.raises(ServiceValidationError, match=(
                "^Invalid C300X display notification: .*" + reason
            )):
                await send(hass, entry, data=bad)
            nothing_happened(entry, spoken)
    asyncio.run(run())


SPOKEN = "media-source://tts/{}?message=Test message&language=None"


@pytest.mark.parametrize("data,notice,engine", [
    ({"led": True, "wake_duration": 0, "sound_duration": 0, "severity": "error"},
     {"id": None, "priority": "urgent", "expires_in": 3600}, None),
    ({"tts": True, "wake_duration": 0, "tts_engine": "tts.piper"}, None, "tts.piper"),
    ({"tts": True, "led": True, "notification_id": "door", "expires_in": 60},
     {"id": "door", "priority": "normal", "expires_in": 60}, "default"),
], ids=["led", "tts", "tts+led"])
def test_fields_of_a_channel_that_is_off_may_be_zero_or_apply_elsewhere(
    tmp_path, monkeypatch, data, notice, engine,
):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.runtime_data.capabilities["memo_led"] = True
            before = hass.loop.time()
            await send(hass, entry, data=data)
            after = hass.loop.time()
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
            assert [call["media_content_id"] for call in spoken] == (
                [SPOKEN.format(engine)] if engine else [])
            store = entry.runtime_data.display_notifications
            if notice is None:
                # Speech alone stores nothing, so nothing counts for the LED.
                assert store is None or not store._items
                return
            [item] = store._items.values()
            if notice["id"] is None:
                assert len(item["id"]) == 32  # generated uuid4 hex
            else:
                assert item["id"] == notice["id"]
            assert (item["title"], item["message"], item["priority"], item["led"]) == (
                "Home Assistant", "Test message", notice["priority"], True)
            assert before + notice["expires_in"] <= item["deadline"] <= after + notice["expires_in"]
            assert store.has_unread() is True
    asyncio.run(run())


@pytest.mark.parametrize("capability", [None, False, 1, "true"])
@pytest.mark.parametrize("switches", [
    {"led": True}, {"display": True, "led": True}, {"tts": True, "led": True},
    {"display": True, "tts": True, "led": True},
], ids=["led", "display+led", "tts+led", "all"])
def test_led_needs_an_agent_that_reports_it(tmp_path, monkeypatch, switches, capability):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            if capability is not None:
                entry.runtime_data.capabilities["memo_led"] = capability
            with pytest.raises(ServiceValidationError, match=(
                "^C300X led requires a device agent that reports memo LED support.*leave led off"
            )):
                await send(hass, entry, data=switches)
            nothing_happened(entry, spoken)
            # The same agent still takes the other channels without the LED.
            if len(switches) > 1:
                await send(hass, entry, data={**switches, "led": False})
            assert entry.runtime_data.display_notifications is None or (
                not entry.runtime_data.display_notifications.has_unread())
    asyncio.run(run())


def test_led_and_tts_do_not_need_display_alerts(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.runtime_data.capabilities.update(display_alerts=False, memo_led=True)
            for switches in ({"display": True}, {"display": True, "led": True},
                             {"display": True, "tts": True, "led": True}):
                with pytest.raises(ServiceValidationError, match="require an update"):
                    await send(hass, entry, data=switches)
                nothing_happened(entry, spoken)
            await send(hass, entry, data={"tts": True, "led": True})
            assert effects(entry, spoken) == {
                "alerts": 0, "sound": None, "spoken": 1, "notices": 1, "led": True,
            }
    asyncio.run(run())


@pytest.mark.parametrize("switches", [
    {"tts": True, "led": True}, {"display": True, "tts": True},
    {"display": True, "tts": True, "led": True},
])
def test_nothing_is_stored_or_shown_when_the_speech_cannot_play(tmp_path, monkeypatch, switches):
    async def run():
        async with speech_context(tmp_path, monkeypatch, speaker_state="unavailable") as (
            hass, entry, spoken,
        ):
            entry.runtime_data.capabilities["memo_led"] = True
            with pytest.raises(ServiceValidationError, match="speaker is unavailable"):
                await send(hass, entry, data=switches)
            nothing_happened(entry, spoken)
    asyncio.run(run())


def test_a_protected_screen_keeps_notice_led_and_speech(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.runtime_data.capabilities["memo_led"] = True
            entry.runtime_data.api.async_send_display_alert.return_value = {
                "ok": True, "accepted": False, "suppressed": True, "reason": "display_protected",
            }
            await send(hass, entry, data={"display": True, "tts": True, "led": True})
            assert effects(entry, spoken) == {
                "alerts": 1, "sound": 0, "spoken": 1, "notices": 1, "led": True,
            }
    asyncio.run(run())


def test_severity_replacement_and_expiry_hold_for_led_notices(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.runtime_data.capabilities["memo_led"] = True
            await send(hass, entry, data={"led": True, "notification_id": "door", "severity": "error"})
            await send(hass, entry, data={"display": True, "notification_id": "door"})
            notice, = notification_payload(entry)
            assert notice["priority"] == "normal"
            # The replacement asked for no LED, so the LED is released.
            assert not entry.runtime_data.display_notifications.has_unread()
            store = entry.runtime_data.display_notifications
            await send(hass, entry, data={"led": True, "notification_id": "short", "expires_in": 1})
            assert store.has_unread()
            store._items["short"]["deadline"] = hass.loop.time()
            assert not store.has_unread()
    asyncio.run(run())
