from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ha_integration_has_no_periodic_polling_hooks() -> None:
    forbidden = {
        "custom_components/bticino_c300x/events.py": [
            "async_track_time_interval",
        ],
        "custom_components/bticino_c300x/sensor.py": [
            "SCAN_INTERVAL",
        ],
        "custom_components/bticino_c300x/switch.py": [
            "update_before_add=True",
        ],
        "custom_components/bticino_c300x/webhook.py": [
            "update_entity",
        ],
    }

    for path, markers in forbidden.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in text, f"{path} contains polling marker {marker!r}"


def test_device_alarm_page_has_no_refresh_timer() -> None:
    text = (ROOT / "device_qml" / "Alarm.qml").read_text(encoding="utf-8")

    assert "refreshTimer" not in text
    assert "interval: 5000" not in text


def test_device_homeassistant_page_has_no_refresh_timer() -> None:
    text = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(encoding="utf-8")
    helper = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(encoding="utf-8")

    assert "Timer" not in text
    assert "refreshTimer" not in helper
    assert "setInterval" not in helper


def test_device_home_page_uses_static_display_bridge_buttons() -> None:
    text = (ROOT / "native_agent" / "scripts" / "qml_patch.sh").read_text(
        encoding="utf-8"
    )
    helper = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(encoding="utf-8")

    assert "property bool alarmButtonVisible: false" not in text
    assert "property bool haButtonVisible: false" not in text
    assert "visible: page.alarmButtonVisible" not in text
    assert "visible: page.haButtonVisible" not in text
    assert 'objectName: \\"alarmButton\\"' in text
    assert 'objectName: \\"haButton\\"' in text
    assert 'id: homeAssistantButtonRow' in text
    assert "width: buttonPrototype.width * 2 + foobar.spacing" in text
    assert "spacing: foobar.spacing" in text
    assert 'pressedIcon: \\"images/keylock_icon-small_p.svg\\"' in text
    assert 'defaultIcon: \\"images/keylock_icon-small.svg\\"' in text
    assert 'pressedIcon: \\"images/call/icon_call-home_p.svg\\"' in text
    assert 'defaultIcon: \\"images/call/icon_call-home.svg\\"' in text
    assert "HAConfig.homeButtons" not in text
    assert "function startMessageNotificationWatch()" in text
    assert "MemoSync.startEventWatch(handleMessageNotificationEvent)" in text
    assert "function homeButtons(callback)" in helper
    assert "Timer" not in helper
    assert "setInterval" not in helper


def test_disabled_metric_sensors_do_not_refresh_during_setup() -> None:
    text = (ROOT / "custom_components" / "bticino_c300x" / "sensor.py").read_text(
        encoding="utf-8"
    )
    setup_body = text.split("class C300XConnectionDiagnosticSensor", maxsplit=1)[0]

    assert "initial_refresh_entities.append(C300XDeviceTemperatureSensor" not in setup_body
    assert "initial_refresh_entities.append(C300XDeviceLoadSensor" not in setup_body
    assert "initial_refresh_entities.append(C300XDeviceCpuSensor" not in setup_body
    assert "initial_refresh_entities.append(sensor)" not in setup_body


def test_message_sensors_do_not_scan_device_during_setup() -> None:
    text = (ROOT / "custom_components" / "bticino_c300x" / "sensor.py").read_text(
        encoding="utf-8"
    )
    setup_body = text.split("class C300XConnectionDiagnosticSensor", maxsplit=1)[0]

    assert "initial_refresh_entities.extend(" not in setup_body
    assert "async def _async_refresh_initial_states" not in text


def test_message_delete_buttons_do_not_refresh_during_setup() -> None:
    text = (ROOT / "custom_components" / "bticino_c300x" / "button.py").read_text(
        encoding="utf-8"
    )

    assert "_async_refresh_memos" not in text
    assert "_async_refresh_video_messages" not in text
    assert "async_create_task(self._async_refresh" not in text


def test_system_metric_sensors_are_disabled_by_default_and_not_polled() -> None:
    text = (ROOT / "custom_components" / "bticino_c300x" / "sensor.py").read_text(
        encoding="utf-8"
    )
    metrics_body = text.split("class C300XSystemMetricSensor", maxsplit=1)[1].split(
        "class C300XDeviceTemperatureSensor",
        maxsplit=1,
    )[0]

    assert "_attr_should_poll = False" in metrics_body
    assert "_attr_entity_registry_enabled_default = False" in metrics_body


def test_no_auth_bootstrap_entries_are_not_rejected_before_agent_probe() -> None:
    text = (ROOT / "custom_components" / "bticino_c300x" / "__init__.py").read_text(
        encoding="utf-8"
    )
    required_block = text.split("required = (", maxsplit=1)[1].split(")", maxsplit=1)[0]

    assert "CONF_AGENT_HOST" in required_block
    assert "CONF_AGENT_TOKEN" not in required_block
