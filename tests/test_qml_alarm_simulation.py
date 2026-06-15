from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_alarm_qml_contains_alarmo_card_feedback_hooks() -> None:
    alarm_qml = (ROOT / "device_qml" / "Alarm.qml").read_text(encoding="utf-8")

    assert "modeReadyColor(modelData)" in alarm_qml
    assert "modeReadyIndicatorVisible(modelData)" in alarm_qml
    assert "modeFeedbackColor(modelData)" in alarm_qml
    assert "modeFeedbackVisible(modelData)" in alarm_qml
    assert "flashCommandButton(command, color)" in alarm_qml
    assert "modeFeedbackTimer.restart()" in alarm_qml
    assert "selectedCommandBlockedBySensors" in alarm_qml
    assert "bypassVisible()" in alarm_qml
    assert "executeCommand(selectedCommand, true)" in alarm_qml
    assert "feedbackTitle()" in alarm_qml
    assert "feedbackDetail()" in alarm_qml
    assert "feedbackColor()" in alarm_qml
    assert "Api.startEventWatch(handleStatusEvent)" in alarm_qml
    assert 'event.topic === "alarm"' in alarm_qml


def test_alarm_qml_simulates_alarmo_card_behaviour(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    script = tmp_path / "alarm_qml_simulation.js"
    script.write_text(
        f"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const apiPath = {str(ROOT / "device_qml/js/c300x_ha.js")!r};
const i18nPath = {str(ROOT / "device_qml/js/c300x_i18n.js")!r};

function loadLibrary(path) {{
  const code = fs.readFileSync(path, "utf8").replace(/^\\s*\\.pragma library\\s*\\n/, "");
  const context = {{
    Date,
    JSON,
    Math,
    Number,
    String,
    console,
    isNaN,
    parseInt,
    XMLHttpRequest: function() {{}}
  }};
  vm.createContext(context);
  vm.runInContext(code, context, {{ filename: path }});
  return context;
}}

const Api = loadLibrary(apiPath);
const I18n = loadLibrary(i18nPath);

assert.strictEqual(I18n.language("fr-FR"), "fr");
assert.strictEqual(I18n.text("fr-FR", "alarm"), "Alarme");
assert.strictEqual(I18n.text("fr-FR", "armed_away"), "Absent");
assert.strictEqual(I18n.weather("fr-FR", "rainy", ""), "Pluie");
assert.strictEqual(I18n.weather("fr-FR", "unknown", ""), "Inconnu");

let routes = {{}};
let calls = [];

function clone(value) {{
  return JSON.parse(JSON.stringify(value));
}}

Api.getJson = function(path, callback, errorCallback) {{
  calls.push(path);
  if (!(path in routes)) {{
    throw new Error("unexpected GET " + path);
  }}
  const response = routes[path];
  if (response && response.__error) {{
    errorCallback(response.__error);
    return;
  }}
  callback(clone(response));
}};

function command(command, state, options) {{
  options = options || {{}};
  const payload = {{
    command,
    state,
    name: options.name || command,
    code_required: options.code_required === true
  }};
  if (options.code_format) payload.code_format = options.code_format;
  if ("ready" in options) payload.ready = options.ready;
  if (options.blocking_sensors) payload.blocking_sensors = options.blocking_sensors;
  if ("blocking_sensor_count" in options) {{
    payload.blocking_sensor_count = options.blocking_sensor_count;
  }}
  return payload;
}}

function statePayload(state, commands, extra) {{
  extra = extra || {{}};
  return {{
    ok: true,
    alarm_configured: true,
    dashboard_available: true,
    alarm: Object.assign({{
      entity_id: "alarm_control_panel.alarmo",
      state,
      active_since: "2026-05-31T12:00:00+00:00",
      commands
    }}, extra)
  }};
}}

function createPage() {{
  const page = {{
    uiLanguage: "de",
    pinCode: "",
    alarmRawState: "unknown",
    alarmConfigured: false,
    selectedCommand: "arm_home",
      alarmCommands: ["arm_home", "arm_away", "arm_night"],
      alarmCommandDetails: [],
      alarmOpenSensors: [],
      alarmOpenSensorCount: 0,
      selectedCommandReady: true,
      selectedCommandBlockedBySensors: false,
      selectedCommandStatus: "",
      alarmDelayRemaining: 0,
      bypassOffered: false,
      commandFeedback: "",
      commandFeedbackColor: "#c7d0d9",
      activeFeedbackCommand: "",
      feedbackTimerRestarts: 0,
      refreshSoonCalls: 0,
    uiText(key) {{
      return I18n.text(this.uiLanguage, key);
    }},
    appendDigit(digit) {{
      if (this.pinCode.length < 10) this.pinCode = this.pinCode + digit;
    }},
    clearPin() {{
      this.pinCode = "";
    }},
    setAlarmDelayRemaining(seconds) {{
      let value = parseInt(seconds || 0, 10);
      if (isNaN(value)) value = 0;
      this.alarmDelayRemaining = Math.max(0, value);
    }},
    pinMask() {{
      return Array(this.pinCode.length + 1).join("*");
    }},
    commandLabel(command) {{
      if (command === "arm_home") return this.uiText("armed_home");
      if (command === "arm_away") return this.uiText("armed_away");
      if (command === "arm_night") return this.uiText("armed_night");
      if (command === "arm_custom_bypass") return this.uiText("armed_custom_bypass");
      if (command === "arm_vacation") return this.uiText("armed_vacation");
      if (command === "disarm") return this.uiText("disarmed");
      return command;
    }},
    commandTargetState(command) {{
      if (command === "arm_home") return "armed_home";
      if (command === "arm_away") return "armed_away";
      if (command === "arm_night") return "armed_night";
      if (command === "arm_custom_bypass") return "armed_custom_bypass";
      if (command === "arm_vacation") return "armed_vacation";
      if (command === "disarm") return "disarmed";
      return "";
    }},
    isArmCommand(command) {{
      return command.indexOf("arm_") === 0;
    }},
    stateLabel() {{
      if (this.alarmRawState === "disarmed") return this.uiText("disarmed");
      if (this.alarmRawState === "armed_home") return this.uiText("armed_home");
      if (this.alarmRawState === "armed_away") return this.uiText("armed_away");
      if (this.alarmRawState === "armed_night") return this.uiText("armed_night");
      if (this.alarmRawState === "armed_custom_bypass") return this.uiText("armed_custom_bypass");
      if (this.alarmRawState === "armed_vacation") return this.uiText("armed_vacation");
      if (this.alarmRawState === "arming") return this.uiText("arming");
      if (this.alarmRawState === "pending") return this.uiText("pending");
      if (this.alarmRawState === "triggered") return this.uiText("triggered");
      if (this.alarmRawState === "unavailable") return this.uiText("offline");
      return this.uiText("unknown");
    }},
    isArmedState() {{
      return this.alarmRawState === "armed_home"
          || this.alarmRawState === "armed_away"
          || this.alarmRawState === "armed_night"
          || this.alarmRawState === "armed_custom_bypass"
          || this.alarmRawState === "armed_vacation";
    }},
    setCommandFeedback(key, command, color) {{
      this.commandFeedback = this.uiText(key);
      if (command && command.length > 0) {{
        this.commandFeedback = this.commandFeedback + ": " + this.commandLabel(command);
      }}
      this.commandFeedbackColor = color;
      this.flashCommandButton(command, color);
      statusItem.text = this.commandFeedback;
      statusItem.color = color;
    }},
    flashCommandButton(command, color) {{
      if (!command || command.length === 0) return;
      this.activeFeedbackCommand = command;
      this.commandFeedbackColor = color;
      this.feedbackTimerRestarts += 1;
    }},
    expireCommandFlash() {{
      this.activeFeedbackCommand = "";
    }},
    clearCommandFeedback() {{
      this.commandFeedback = "";
    }},
    refreshSoon() {{
      this.refreshSoonCalls += 1;
    }},
      selectCommand(command) {{
      if (this.selectedCommand !== command) {{
        this.bypassOffered = false;
      }}
      this.selectedCommand = command;
      this.flashCommandButton(command, "#f1c40f");
      this.refreshCommandReadiness();
      if (!this.selectedCommandReady) {{
        if (command.indexOf("arm_") === 0) {{
          this.setCommandFeedback("checking", command, "#f1c40f");
          Api.alarmCheck(command, statusItem, this);
        }} else {{
          this.setCommandFeedback("not_ready_to_arm", command, "#ff6b6b");
        }}
        return;
      }}
      if (!this.commandRequiresPin(command)) {{
        this.executeCommand(command, false);
      }} else {{
        this.setCommandFeedback("pin_required", command, "#f1c40f");
      }}
    }},
    commandRequiresPin(command) {{
      return Api.alarmCommandRequiresCode(this.alarmCommandDetails, command);
    }},
    submitPin() {{
      this.executeCommand(this.selectedCommand, false);
    }},
    executeCommand(command, force) {{
      if (!this.alarmConfigured) {{
        statusItem.text = this.uiText("alarm_not_configured");
        statusItem.color = "#ff6b6b";
        return;
      }}
      if (this.alarmCommands.length === 0) {{
        statusItem.text = this.uiText("no_mode_available");
        statusItem.color = "#f1c40f";
        return;
      }}
      this.refreshCommandReadiness();
      if (!force && !this.selectedCommandReady) {{
        this.setCommandFeedback("not_ready_to_arm", command, "#ff6b6b");
        return;
      }}
      const needsPin = this.commandRequiresPin(command);
      if (needsPin && this.pinCode.length === 0) {{
        this.setCommandFeedback("pin_required", command, "#f1c40f");
        return;
      }}
        const code = needsPin ? this.pinCode : "";
        this.pinCode = "";
        this.selectedCommand = command;
        this.flashCommandButton(command, "#f1c40f");
        if (force) {{
          this.bypassOffered = false;
        }}
        this.setCommandFeedback(force ? "bypass_open_sensors" : "sending", command, "#f1c40f");
        Api.alarmCommand(command, code, statusItem, this, alarmStateItem, activeSinceItem, force);
    }},
    modeReadyColor(command) {{
      return Api.alarmCommandReady(this.alarmCommandDetails, command) ? "#58d68d" : "#ff6b6b";
    }},
    modeReadyIndicatorVisible(command) {{
      return this.isArmCommand(command) && this.commandTargetState(command) !== this.alarmRawState;
    }},
    modeFeedbackVisible(command) {{
      return this.activeFeedbackCommand === command;
    }},
    modeFeedbackColor(command) {{
      if (!this.modeFeedbackVisible(command)) return "transparent";
      if (this.commandFeedbackColor === "#f1c40f") return "#f1c40f";
      if (this.commandFeedbackColor === "#58d68d") return "#58d68d";
      if (this.commandFeedbackColor === "#ff6b6b" || !Api.alarmCommandReady(this.alarmCommandDetails, command)) return "#ff6b6b";
      return "#58d68d";
    }},
    refreshCommandReadiness() {{
      this.selectedCommandReady = Api.alarmCommandReady(this.alarmCommandDetails, this.selectedCommand);
      this.selectedCommandBlockedBySensors = Api.alarmCommandHasBlockers(this.alarmCommandDetails, this.selectedCommand);
      this.selectedCommandStatus = this.selectedCommandReady ? "" : Api.alarmBlockingText(this.alarmCommandDetails, this.selectedCommand, this);
    }},
    feedbackTitle() {{
      if (!this.alarmConfigured) return this.uiText("alarm_not_configured");
        if (this.alarmCommands.length === 0) return this.uiText("no_mode_available");
        if (this.bypassVisible()) return this.uiText("not_ready_to_arm");
        if (this.isArmedState()) return this.commandLabel(Api.commandForState(this.alarmRawState));
        return this.stateLabel();
      }},
      feedbackDetail() {{
        if (!this.alarmConfigured || this.alarmCommands.length === 0) return "";
        if (this.alarmRawState === "triggered") {{
          const sensors = Api.alarmOpenSensorsText(this);
          if (sensors.length > 0) return sensors;
          return this.commandLabel(this.selectedCommand);
        }}
        if (this.bypassVisible()) return this.selectedCommandStatus;
        const timer = this.alarmDelayRemaining > 0 ? this.alarmDelayRemaining + " " + this.uiText("seconds_short") : "";
        const pin = this.pinCode.length > 0 ? this.uiText("pin_label") + ": " + this.pinMask() : "";
        if (timer.length > 0 && pin.length > 0) {{
          return timer + "  " + this.commandLabel(this.selectedCommand) + "  " + pin;
        }}
        if (this.pinCode.length > 0) {{
          return this.commandLabel(this.selectedCommand) + "  " + pin;
        }}
        if (this.alarmRawState === "disarmed") {{
          const sensors = Api.alarmOpenSensorsText(this);
          if (sensors.length > 0) return sensors;
          if (!this.selectedCommandReady && this.selectedCommandStatus.length > 0) return this.selectedCommandStatus;
          return this.uiText("sensor_ok");
        }}
        if (this.commandRequiresPin(this.selectedCommand)) {{
          if (timer.length > 0) return timer + "  " + this.commandLabel(this.selectedCommand);
          return this.uiText("pin_label") + ":";
        }}
        if (timer.length > 0) return timer + "  " + this.commandLabel(this.selectedCommand);
        if (!this.selectedCommandReady) return this.commandLabel(this.selectedCommand);
        if (this.isArmedState()) return "";
        return this.uiText("ready_to_arm") + ": " + this.commandLabel(this.selectedCommand);
      }},
    feedbackColor() {{
      if (this.alarmRawState === "triggered") return "#ff6b6b";
      if (!this.alarmConfigured || this.bypassVisible()) return "#ff6b6b";
      if (this.alarmRawState === "arming" || this.alarmRawState === "pending") return "#f1c40f";
      if (this.alarmRawState === "unavailable" || this.alarmRawState === "unknown") return "#f1c40f";
      return "#58d68d";
    }},
      bypassVisible() {{
        return this.bypassOffered && this.selectedCommandBlockedBySensors && this.selectedCommand.indexOf("arm_") === 0;
      }},
    modeColumnCount() {{
      if (this.alarmCommands.length <= 0) return 1;
      if (this.alarmCommands.length <= 4) return this.alarmCommands.length;
      return 4;
    }},
    modeRowCount() {{
      return this.alarmCommands.length <= this.modeColumnCount() ? 1 : 2;
    }}
  }};
  return page;
}}

let statusItem;
let alarmStateItem;
let activeSinceItem;

function reset(initialState) {{
  calls = [];
  routes = {{ "/ui/state": initialState }};
  statusItem = {{ text: "", color: "" }};
  alarmStateItem = {{ text: "" }};
  activeSinceItem = {{ text: "" }};
  const page = createPage();
  Api.status(statusItem, page, alarmStateItem, activeSinceItem);
  return page;
}}

function assertBlockedModesLookLikeAlarmoCard() {{
  const page = reset(statePayload("disarmed", [
    command("arm_away", "armed_away", {{
      ready: false,
      blocking_sensors: [{{ entity_id: "binary_sensor.front", name: "Haustuer", state: "open" }}],
      blocking_sensor_count: 1
    }}),
    command("arm_night", "armed_night", {{ ready: false, blocking_sensor_count: 0 }}),
    command("arm_vacation", "armed_vacation", {{ ready: true }})
  ]));

  assert.strictEqual(
    JSON.stringify(page.alarmCommands),
    JSON.stringify(["arm_away", "arm_night", "arm_vacation"])
  );
  assert.strictEqual(page.modeReadyColor("arm_away"), "#ff6b6b");
    assert.strictEqual(page.modeReadyColor("arm_night"), "#ff6b6b");
    assert.strictEqual(page.modeReadyColor("arm_vacation"), "#58d68d");
    assert.strictEqual(page.modeReadyIndicatorVisible("arm_away"), true);
    assert.strictEqual(page.modeReadyIndicatorVisible("disarm"), false);
    assert.strictEqual(page.modeFeedbackVisible("arm_away"), false);
    assert.strictEqual(page.modeFeedbackColor("arm_away"), "transparent");
    assert.strictEqual(page.selectedCommand, "arm_away");
    assert.strictEqual(page.selectedCommandReady, false);
    assert.strictEqual(page.bypassVisible(), false);
    assert.strictEqual(page.feedbackTitle(), "Aus");
    assert.strictEqual(page.feedbackDetail(), "Sensor offen: Haustuer");
  assert.strictEqual(page.modeColumnCount(), 3);
  assert.strictEqual(page.modeRowCount(), 1);

  routes["/ui/alarm/command?command=arm_away&check=true"] = {{
    ok: false,
    error: "not_ready_to_arm",
    command: "arm_away",
    ready: false,
    blocking_sensors: [{{ entity_id: "binary_sensor.front", name: "Haustuer", state: "open" }}],
    blocking_sensor_count: 1
  }};
  page.selectCommand("arm_away");
  assert(calls.includes("/ui/alarm/command?command=arm_away&check=true"));
  assert(!calls.includes("/ui/alarm/command?command=arm_away"));
  assert.strictEqual(page.bypassVisible(), true);
  assert.strictEqual(page.feedbackTitle(), "Nicht bereit");
  assert.strictEqual(page.feedbackDetail(), "Sensor offen: Haustuer");
  assert.strictEqual(page.modeFeedbackVisible("arm_away"), true);
  assert.strictEqual(page.modeFeedbackColor("arm_away"), "#ff6b6b");
  assert(page.feedbackTimerRestarts >= 3);
  page.expireCommandFlash();
  assert.strictEqual(page.modeFeedbackVisible("arm_away"), false);

  routes["/ui/alarm/command?command=arm_night&check=true"] = {{
    ok: false,
    error: "not_ready_to_arm",
    command: "arm_night",
    ready: false,
    blocking_sensors: [{{ entity_id: "binary_sensor.kitchen", name: "Kueche", state: "open" }}],
    blocking_sensor_count: 1
  }};
  page.selectCommand("arm_night");
  assert(calls.includes("/ui/alarm/command?command=arm_night&check=true"));
  assert(!calls.includes("/ui/alarm/command?command=arm_night"));
  assert.strictEqual(page.selectedCommand, "arm_night");
  assert.strictEqual(page.selectedCommandReady, false);
  assert.strictEqual(page.bypassVisible(), true);
  assert.strictEqual(page.feedbackDetail(), "Sensor offen: Kueche");
  assert.strictEqual(page.modeFeedbackVisible("arm_night"), true);
  assert.strictEqual(page.modeFeedbackColor("arm_night"), "#ff6b6b");

  routes["/ui/alarm/command?command=arm_away&force=true"] = {{
    ok: true,
    command: "arm_away",
    state: "armed_away"
  }};
  page.executeCommand("arm_away", true);
  assert(calls.includes("/ui/alarm/command?command=arm_away&force=true"));
  assert.strictEqual(page.modeFeedbackVisible("arm_away"), true);
  assert.strictEqual(page.modeFeedbackColor("arm_away"), "#58d68d");
}}

function assertReadyModeExecutesWithoutPin() {{
  const page = reset(statePayload("disarmed", [
    command("arm_away", "armed_away", {{ ready: false, blocking_sensor_count: 1 }}),
    command("arm_vacation", "armed_vacation", {{ ready: true }})
  ]));
  routes["/ui/alarm/command?command=arm_vacation"] = {{
    ok: true,
    command: "arm_vacation",
    state: "armed_vacation"
  }};
  assert.strictEqual(page.modeFeedbackColor("arm_vacation"), "transparent");
  page.selectCommand("arm_vacation");
  assert(calls.includes("/ui/alarm/command?command=arm_vacation"));
  assert.strictEqual(statusItem.text, "Alarmbefehl gesendet: Urlaub");
  assert.strictEqual(statusItem.color, "#58d68d");
  assert.strictEqual(page.modeFeedbackVisible("arm_vacation"), true);
  assert.strictEqual(page.modeFeedbackColor("arm_vacation"), "#58d68d");
  assert.strictEqual(page.refreshSoonCalls, 1);
}}

function assertDisarmRequiresConfiguredPin() {{
  const page = reset(statePayload("armed_away", [
    command("disarm", "disarmed", {{ code_required: true, code_format: "number" }}),
    command("arm_away", "armed_away", {{ ready: true }})
  ]));

  page.selectCommand("disarm");
  assert.strictEqual(page.feedbackTitle(), "Abwesend");
  assert.strictEqual(statusItem.text, "PIN benoetigt: Aus");
      assert.strictEqual(JSON.stringify(calls), JSON.stringify(["/ui/state"]));
  page.appendDigit("1");
  page.appendDigit("2");
    page.appendDigit("3");
    page.appendDigit("4");
    assert.strictEqual(page.feedbackDetail(), "Aus  PIN: ****");
  routes["/ui/alarm/command?command=disarm&code=1234"] = {{
    ok: true,
    command: "disarm",
    state: "disarmed"
  }};
  page.submitPin();
  assert(calls.includes("/ui/alarm/command?command=disarm&code=1234"));
  assert.strictEqual(page.pinCode, "");
}}

function assertServerSideBlockerUpdatesFeedbackWithoutHttpError() {{
  const page = reset(statePayload("disarmed", [
    command("arm_away", "armed_away", {{ ready: true }})
  ]));
  routes["/ui/alarm/command?command=arm_away"] = {{
    ok: false,
    error: "not_ready_to_arm",
    command: "arm_away",
    ready: false,
    blocking_sensors: [{{ entity_id: "binary_sensor.window", name: "Fenster", state: "open" }}],
    blocking_sensor_count: 1
  }};
  page.selectCommand("arm_away");
  assert.strictEqual(page.selectedCommandReady, false);
  assert.strictEqual(page.bypassVisible(), true);
  assert.strictEqual(page.feedbackTitle(), "Nicht bereit");
  assert.strictEqual(page.feedbackDetail(), "Sensor offen: Fenster");
  assert.strictEqual(statusItem.text, "");
  assert.strictEqual(statusItem.color, "#ff6b6b");
}}

function assertInvalidCodeFeedbackIsExplicit() {{
  const page = reset(statePayload("armed_away", [
    command("disarm", "disarmed", {{ code_required: true, code_format: "number" }}),
    command("arm_away", "armed_away", {{ ready: true }})
  ]));
  page.selectCommand("disarm");
  page.appendDigit("0");
  page.appendDigit("0");
  page.appendDigit("0");
  page.appendDigit("0");
  routes["/ui/alarm/command?command=disarm&code=0000"] = {{
    ok: false,
    error: "invalid_code",
    command: "disarm",
    state: "armed_away"
  }};
  page.submitPin();
  assert.strictEqual(statusItem.text, "PIN falsch: Aus");
  assert.strictEqual(statusItem.color, "#ff6b6b");
}}

function assertAllOpenSensorsAreShown() {{
  const page = reset(statePayload("disarmed", [
    command("arm_away", "armed_away", {{
      ready: false,
      blocking_sensors: [
        {{ entity_id: "binary_sensor.front", name: "Haustuer", state: "open" }},
        {{ entity_id: "binary_sensor.window", name: "Fenster", state: "open" }},
        {{ entity_id: "binary_sensor.garage", name: "Garage", state: "open" }},
        {{ entity_id: "binary_sensor.kitchen", name: "Kueche", state: "open" }}
      ],
      blocking_sensor_count: 4
    }})
  ]));
  routes["/ui/alarm/command?command=arm_away&check=true"] = {{
    ok: false,
    error: "not_ready_to_arm",
    command: "arm_away",
    ready: false,
    blocking_sensors: page.alarmCommandDetails[0].blocking_sensors,
    blocking_sensor_count: 4
  }};
  page.selectCommand("arm_away");
  assert(calls.includes("/ui/alarm/command?command=arm_away&check=true"));
  assert(!calls.includes("/ui/alarm/command?command=arm_away"));
  assert.strictEqual(page.feedbackDetail(), "Sensor offen: Haustuer, Fenster, Garage, Kueche");
}}

function assertTransportErrorDoesNotLeakRawApiError() {{
  const page = reset(statePayload("disarmed", [
    command("arm_away", "armed_away", {{ ready: true }})
  ]));
  routes["/ui/alarm/command?command=arm_away"] = {{ __error: "API error: 0" }};
  page.selectCommand("arm_away");
  assert.strictEqual(statusItem.text, "Alarmbefehl Fehler: Abwesend");
  assert.strictEqual(statusItem.color, "#ff6b6b");
}}

function assertDelayCountdownFeedbackWins() {{
  const page = reset(statePayload("arming", [
    command("disarm", "disarmed", {{ code_required: true, code_format: "number" }}),
    command("arm_away", "armed_away", {{ ready: true }})
  ], {{ delay_remaining: 30 }}));
    assert.strictEqual(page.feedbackTitle(), "Aktiviert");
    assert.strictEqual(page.feedbackDetail(), "30 s  Aus");
    assert.strictEqual(page.feedbackColor(), "#f1c40f");
}}

function assertDisarmPinFeedbackWinsDuringDelay() {{
  const page = reset(statePayload("pending", [
    command("arm_home", "armed_home", {{ ready: true }}),
    command("disarm", "disarmed", {{ code_required: true, code_format: "number" }}),
    command("arm_away", "armed_away", {{ ready: true }})
    ], {{ delay_remaining: 25 }}));
    assert.strictEqual(page.selectedCommand, "disarm");
    assert.strictEqual(page.feedbackTitle(), "Wartet");
    assert.strictEqual(page.feedbackDetail(), "25 s  Aus");
    assert.strictEqual(page.feedbackColor(), "#f1c40f");
    page.appendDigit("1");
    page.appendDigit("2");
    assert.strictEqual(page.feedbackDetail(), "25 s  Aus  PIN: **");
}}

function assertTriggeredAlarmSelectsDisarmAndShowsAlarm() {{
  const page = reset(statePayload("triggered", [
    command("arm_home", "armed_home", {{ ready: true }}),
    command("disarm", "disarmed", {{ code_required: true, code_format: "number" }}),
    command("arm_away", "armed_away", {{ ready: true }})
  ]));
  assert.strictEqual(page.selectedCommand, "disarm");
  assert.strictEqual(page.feedbackTitle(), "Alarm");
  assert.strictEqual(page.feedbackDetail(), "Aus");
  assert.strictEqual(page.feedbackColor(), "#ff6b6b");
    page.appendDigit("1");
    page.appendDigit("2");
    assert.strictEqual(page.feedbackDetail(), "Aus");
  }}

function assertFourModesFitInOneRow() {{
  const page = reset(statePayload("disarmed", [
    command("arm_home", "armed_home", {{ ready: true }}),
    command("arm_away", "armed_away", {{ ready: true }}),
    command("arm_night", "armed_night", {{ ready: true }}),
    command("arm_vacation", "armed_vacation", {{ ready: true }})
  ]));
  assert.strictEqual(page.alarmCommands.length, 4);
  assert.strictEqual(page.modeColumnCount(), 4);
  assert.strictEqual(page.modeRowCount(), 1);
}}

function assertFiveModesWrapLikeCardControls() {{
  const page = reset(statePayload("disarmed", [
    command("disarm", "disarmed", {{ code_required: true }}),
    command("arm_home", "armed_home", {{ ready: true }}),
    command("arm_away", "armed_away", {{ ready: true }}),
    command("arm_night", "armed_night", {{ ready: true }}),
    command("arm_vacation", "armed_vacation", {{ ready: true }})
  ]));
  assert.strictEqual(page.alarmCommands.length, 5);
  assert.strictEqual(page.modeColumnCount(), 4);
  assert.strictEqual(page.modeRowCount(), 2);
}}

assertBlockedModesLookLikeAlarmoCard();
assertReadyModeExecutesWithoutPin();
assertDisarmRequiresConfiguredPin();
assertServerSideBlockerUpdatesFeedbackWithoutHttpError();
assertInvalidCodeFeedbackIsExplicit();
assertAllOpenSensorsAreShown();
assertTransportErrorDoesNotLeakRawApiError();
assertDelayCountdownFeedbackWins();
assertDisarmPinFeedbackWinsDuringDelay();
assertTriggeredAlarmSelectsDisarmAndShowsAlarm();
assertFourModesFitInOneRow();
assertFiveModesWrapLikeCardControls();
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [node, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
