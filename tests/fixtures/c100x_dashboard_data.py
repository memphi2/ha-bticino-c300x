"""Agent replies for the C100X display scenarios, built by the integration's own payload code."""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from test_executor import FakeEntry, FakeHass, FakeState, FakeStates, run  # noqa: E402

from custom_components.bticino_c300x import dashboard  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_ALARM_ENTITY_ID,
    CONF_DASHBOARD_ENTITIES,
    CONF_DEVICE_UI_ENABLED,
)


def build(pin=False):
    """Start page, a Rooms page taller than the screen, a long Agenda and a Leave home page."""
    states = {
        "light.kitchen": FakeState("on", attributes={
            "friendly_name": "Kitchen light", "brightness": 180, "supported_color_modes": ["brightness"]}),
        "alarm_control_panel.home": FakeState("disarmed", attributes={
            "friendly_name": "Alarm", "code_arm_required": pin, "code_format": "number", "supported_features": 63}),
    }
    for number in range(15):
        states[f"switch.socket_{number}"] = FakeState("off", attributes={"friendly_name": f"Socket {number}"})
    hass = FakeHass(states=FakeStates(states), config=types.SimpleNamespace(language="en"))
    entry = FakeEntry(data={CONF_DEVICE_UI_ENABLED: True}, options={
        CONF_DASHBOARD_ENTITIES: [entity for entity in states if not entity.startswith("alarm_")],
        CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"})
    entry.title = "Home"
    board = run(dashboard.async_dashboard_payload(hass, entry))
    pages = board["data"]["pages"]
    pages[1]["title"] = pages[1]["title"] or "Rooms"
    pages.append({"title": "Agenda", "agenda": {"loading": False, "empty_text": "", "error": "", "events": [
        {"summary": f"Event {number}", "when": f"{number + 1}.12. 09:00", "calendar": "Family", "all_day": False}
        for number in range(12)]}})
    pages.append({"title": "Leave home", "leave_home": {
        "checks": [{"name": "Front door", "state_label": "Closed", "color": "#58d68d"}],
        "actions": [{"domain": "c300x", "entity_id": "scene.leave_home", "name": "Everything off", "kind": "button"}],
        "empty_text": "", "confirm_label": "Confirm", "cancel_label": "Cancel", "attention_count": 0}})
    status = run(dashboard.async_status(hass, entry))
    return {
        "/homeassistant": lambda method, url, body: board if not url.query() else {"ok": True},
        "/ui/state": status, "/ui/alarm/status": status, "/ui/alarm/command": {"ok": True},
        "/ui/preferences": {"ok": True, "feedback_enabled": True},
    }
