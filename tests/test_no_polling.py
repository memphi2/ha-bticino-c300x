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
    start = text.index("interval: 5000")
    recovery = text[start : text.index("interval: 1000\n", start)]
    assert "repeat: false" in recovery
    assert "running: pageActive && watchFailed" in recovery
    assert "repeat: true" not in recovery


def test_device_homeassistant_page_has_no_refresh_timer() -> None:
    text = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(encoding="utf-8")
    helper = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(encoding="utf-8")

    assert text.count("Timer {") == 3
    assert "repeat: true" not in text
    assert "running: pageActive && watchFailed" in text
    assert "running: pageActive && pendingEntity.length > 0" in text
    feedback_timer = text[text.index("id: feedbackExpiry"):].split("}", 1)[0]
    assert "repeat: false" in feedback_timer
    assert "onTriggered: feedbackDue = true" in feedback_timer
    assert "refreshFeedbackExpiry()" in feedback_timer.split("onRunningChanged:", 1)[1]
    expiry = helper[
        helper.index("function expireDashboardFeedback("):
        helper.index("function dashboardExpectation(")
    ]
    assert "getJson" not in expiry
    assert "XMLHttpRequest" not in expiry
    assert "refreshTimer" not in helper
    assert "setInterval" not in helper


def test_device_homeassistant_page_cleans_dashboard_runtime() -> None:
    text = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(encoding="utf-8")
    helper = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(encoding="utf-8")

    assert "function stopDashboardRuntime()" in helper
    assert "function aboutToHide()" in text
    assert "Api.stopDashboardRuntime()" in text
    assert "time=\" + Date.now()" not in helper
    assert "time=\" + Date.now()" not in text


def test_device_home_page_buttons_do_not_poll() -> None:
    text = (ROOT / "native_agent" / "scripts" / "qml_patch.sh").read_text(
        encoding="utf-8"
    )
    helper = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(encoding="utf-8")

    assert 'print_home_assistant_button("alarmButton", "alarmButtonVisible", "keylock_icon-small"' in text
    assert 'print_home_assistant_button("haButton", "haButtonVisible", "call/icon_call-home"' in text
    assert 'id: displayBridgeButtonRow' in text
    assert "width: buttonPrototype.width * 2 + foobar.spacing" in text
    assert "x: buttonPrototype.width + foobar.spacing" in text
    assert "+ (page.alarmButtonVisible ? 1 : 0) + (page.haButtonVisible ? 1 : 0) + 2" in text
    assert 'source: control.pressed ? \\"images/" icon "_p.svg\\" : \\"images/" icon ".svg\\""' in text
    assert "HAConfig.homeButtons" in text
    assert "function startMessageNotificationWatch()" in text
    assert "MemoSync.startEventWatch(handleMessageNotificationEvent)" in text
    assert "function homeButtons(callback, owner)" in helper
    # The page owns a one-shot notification reconnect timer for Qt 4 safety;
    # it must never become a periodic status poll.
    assert "id: memoRetryTimer" in text
    assert "repeat: false" in text
    assert "onTriggered: MemoSync.retryEventWatch()" in text
    assert "repeat: true" not in text
    assert "setInterval" not in text
    assert "Timer" not in helper
    assert "setInterval" not in helper
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
    text = (
        ROOT / "custom_components" / "bticino_c300x" / "runtime_manager.py"
    ).read_text(encoding="utf-8")
    required_block = text.split("required = (", maxsplit=1)[1].split(")", maxsplit=1)[0]

    assert "CONF_AGENT_HOST" in required_block
    assert "CONF_AGENT_TOKEN" not in required_block
