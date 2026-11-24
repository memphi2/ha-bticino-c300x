"""Key-driven scenarios on the original C100X main.qml; see c100x_stock_runtime."""

import sys
from pathlib import Path

from c100x_stock_runtime import Probe, Runtime

PREFERENCES = {"ok": True, "feedback_enabled": True}


def bridge_urls(work, skin):
    """Every bridge request must name the agent's loopback UI listener."""
    runtime = Runtime(work, skin, {"/ui/preferences": PREFERENCES})
    runtime.js("c100xHost.preferences.load()")
    runtime.wait(300)
    urls = [url for method, url, body in runtime.requests]
    assert urls and all(url.startswith("http://127.0.0.1:8090/ui/") for url in urls), urls
    assert "http://127.0.0.1:8090/ui/preferences" in urls, urls
    assert any(url.startswith("http://127.0.0.1:8090/ui/touch-tone/next?enabled=1&") for url in urls), urls
    assert runtime.js("c100xHost.preferences.ready && c100xHost.preferences.feedbackEnabled"), "preferences not read"
    assert not runtime.adapter_warnings(), runtime.adapter_warnings()


def action_destroyed_by_click(work, skin):
    """A click may unload the delegate that owns the action (More list, page change)."""
    probe = Probe(work, """import QtQuick 2.7
Item {
    id: root
    property QtObject c100xHost: QtObject { property string language: "en" }
    property var order: []
    Loader {
        id: loader
        sourceComponent: C100XAction {
            width: 80; height: 40
            onActionPressed: root.order.push("pressed")
            onActionReleased: root.order.push("released")
            onClicked: { root.order.push("clicked"); loader.active = false }
        }
    }
    function run() { loader.item.activate(); return order.join(",") }
}
""")
    assert probe.js("run()") == "pressed,released,clicked"
    probe.wait(50)
    assert not probe.warnings, probe.warnings


def settings_status_item(work, skin):
    """Statusmeldungen sits in the vendor Settings carousel, before its Exit."""
    state = {"feedback_enabled": True, "fail": False}

    def preferences(method, url, body):
        if state["fail"]:
            return 503, {"ok": False}
        if method == "POST":
            state["feedback_enabled"] = __import__("json").loads(body)["feedback_enabled"]
        return {"ok": True, "feedback_enabled": state["feedback_enabled"]}

    runtime = Runtime(work, skin, {"/ui/preferences": preferences})
    runtime.keys("D")
    runtime.keys("R", settle=1800)
    assert runtime.stack("count") == 5 and runtime.stack("currentIndex") == 0, runtime.stack("count")
    kinds = runtime.stack("(function() { var out = []; for (var i = 0; i < menuModel.count; i++) "
                          "out.push(menuModel.get(i).sourceImg); return out.join('|') })()")
    assert kinds.split("|")[:3] == ["images/Wi-Fi.png", "images/Wi-Fi reset.svg", "images/Device reset.svg"], kinds
    assert kinds.endswith("C100XStatus.svg|images/Exit.svg"), kinds
    runtime.keys("3D")
    assert runtime.stack("currentIndex") == 3 and runtime.js("pageIndicator.count") == 5
    label = runtime.stack("listView.currentItem.item.item.children[1].text")
    assert label == "Status messages", label
    assert runtime.stack("listView.currentItem.item.item.children[0].item.children[0].children[1].text") == "ON"
    runtime.keys("R")
    posts = [body for method, url, body in runtime.requests if method == "POST" and url.endswith("/ui/preferences")]
    assert posts == ['{"feedback_enabled":false}'], posts
    assert runtime.js("c100xHost.feedbackEnabled") is False
    assert runtime.stack("listView.currentItem.item.item.children[0].item.children[0].children[1].text") == "OFF"
    runtime.keys("R")
    assert runtime.js("c100xHost.feedbackEnabled") is True and state["feedback_enabled"] is True
    # A refused change reads back the old value; the unreadable preference leaves no item behind.
    state["fail"] = True
    runtime.keys("R")
    assert runtime.js("c100xHost.feedbackEnabled") is True and runtime.js("c100xHost.feedbackToggle.on") is True
    assert runtime.stack("count") == 4 and runtime.js("pageIndicator.count") == 4, "item kept without a preference"
    index = runtime.stack("currentIndex")
    assert index == runtime.js("pageIndicator.currentIndex") and 0 <= index < 4, index
    assert runtime.stack("listView.currentItem !== null && listView.currentItem.item !== null")
    runtime.keys(f"{3 - index}D") if index < 3 else None
    assert runtime.stack("menuModel.get(currentIndex).sourceImg") == "images/Exit.svg"
    runtime.keys("R", settle=1800)
    assert runtime.js("mainStackView.depth") == 1, "Exit did not leave the settings"
    # Every other vendor carousel stays as it is.
    runtime.keys("D R", settle=1800)
    assert runtime.stack("count") == 2, "Info page changed"
    assert not runtime.adapter_warnings(), runtime.adapter_warnings()


def settings_without_bridge(work, skin):
    """No readable preference, no item: the vendor Settings carousel is untouched."""
    runtime = Runtime(work, skin, {})
    runtime.keys("D")
    runtime.keys("R", settle=1800)
    assert runtime.stack("count") == 4 and runtime.js("pageIndicator.count") == 4
    assert not runtime.adapter_warnings(), runtime.adapter_warnings()


RINGTONE, AUTO_OPEN, NETATMO = "images/Ringtone.svg", "images/Professional studio.svg", "images/security-netatmo.svg"
TAIL = ["images/settings.svg", "images/Info.svg", "images/Exit.svg"]
ORDER = ("(function() { var out = []; for (var i = 0; i < listView.model.count; i++) "
         "out.push(listView.model.get(i).sourceImg.replace(/^.*C100X/, 'C100X')); return out.join('|') })()")
STOCK = ("(function() { var out = []; for (var i = 0; i < listModel.count; i++) "
         "out.push(listModel.get(i).sourceImg); return out.join('|') })()")


def state_route(state):
    def route(method, url, body):
        state["reads"] += 1
        if state.get("fail", 0) > 0:
            state["fail"] -= 1
            return 503, {"ok": False}
        return {"ok": True, "alarm_configured": state["alarm"], "dashboard_available": state["home"]}
    return route


def shown_order(stock, home, alarm):
    shown = []
    for item in stock:
        shown.append(item)
        if item == RINGTONE:
            shown += (["C100XHome.svg"] if home else []) + (["C100XAlarm.svg"] if alarm else [])
    return shown


def check_menu(runtime, reference, home, alarm, where):
    """The vendor's own list equals the unpatched station's; the carousel shows it with our entries."""
    stock = runtime.stack(STOCK).split("|")
    if reference is not None:
        assert stock == reference.stack(STOCK).split("|"), (where, stock, reference.stack(STOCK))
        assert runtime.stack("listModel.autoOpenMenuPresent()") == reference.stack("listModel.autoOpenMenuPresent()")
        assert runtime.stack("listModel.netatmoPresent()") == reference.stack("listModel.netatmoPresent()"), where
    shown = shown_order(stock, home, alarm)
    assert runtime.stack(ORDER).split("|") == shown, (where, runtime.stack(ORDER), shown)
    count, index = runtime.stack("count"), runtime.stack("currentIndex")
    assert count == len(shown) == runtime.js("pageIndicator.count"), where
    assert 0 <= index < count and index == runtime.js("pageIndicator.currentIndex"), (where, index)
    assert runtime.stack("listView.currentItem !== null && listView.currentItem.item !== null"), where


def menu_combinations(work, skin, netatmo, auto_open, home, alarm):
    """Every start state, then runtime toggles from it, beside the unpatched vendor page doing the same."""
    netatmo, auto_open, home, alarm = (flag == "1" for flag in (netatmo, auto_open, home, alarm))
    state = {"reads": 0, "home": home, "alarm": alarm}
    setup = f"netatmoCount = {int(netatmo)}; configuration.isAutoOpenAllowed = {str(auto_open).lower()}"
    runtime = Runtime(work, skin, {"/ui/state": state_route(state)}, setup=setup)
    reference = Runtime(work, skin, setup=setup, patched=False)
    assert reference.stack(ORDER) == reference.stack(STOCK), "reference is not the vendor page"
    check_menu(runtime, reference, home, alarm, "start")
    both = (runtime, reference)

    def toggle_auto_open():
        nonlocal auto_open
        auto_open = not auto_open
        for target in both:
            target.js(f"global.configuration.isAutoOpenAllowed = {str(auto_open).lower()}")

    def toggle_netatmo():
        nonlocal netatmo
        netatmo = not netatmo
        for target in both:
            target.js(f"global.netatmoCount = {int(netatmo)}; global.mNetatmoCamera = {{}}")

    def toggle_home():
        nonlocal home
        home = state["home"] = not home
        runtime.js("c100xHost.refreshEntries()")

    def toggle_alarm():
        nonlocal alarm
        alarm = state["alarm"] = not alarm
        runtime.js("c100xHost.refreshEntries()")

    # A Gray code over the four flags: from this start, every one of the 16 combinations is reached at runtime.
    toggles = (toggle_auto_open, toggle_home, toggle_netatmo, toggle_alarm)
    seen = {(netatmo, auto_open, home, alarm)}
    for number in range(1, 17):
        step = toggles[min(3, (number & -number).bit_length() - 1)]
        # Stand on every position in turn, so an item also appears and vanishes under the selection.
        runtime.keys("D", settle=450)
        step()
        runtime.wait(150)
        check_menu(runtime, reference, home, alarm, f"{number}:{step.__name__}")
        seen.add((netatmo, auto_open, home, alarm))
    assert len(seen) == 16, seen
    assert not runtime.adapter_warnings(), runtime.adapter_warnings()


def menu_entries_open_their_pages(work, skin):
    """Return on an entry opens its page directly; there is no sub-menu in between."""
    state = {"reads": 0, "home": True, "alarm": True}
    runtime = Runtime(work, skin, {"/ui/state": state_route(state)})
    check_menu(runtime, None, True, True, "start")
    for downs, page, label in ((1, "HomeAssistant.qml", "Home Assistant"), (2, "Alarm.qml", "Alarmo")):
        runtime.keys(f"{downs}D")
        assert runtime.stack("listView.currentItem.item.children[1].text") == label
        runtime.keys("R", settle=2200)
        assert runtime.js("mainStackView.depth") == 2
        assert runtime.js("mainStackView.currentItem.item.pageName") == page
        assert runtime.js("!!mainStackView.currentItem.item.pageItem"), page + " not loaded"
        runtime.js("mainStackView.currentItem.item.pageItem.back()")
        runtime.wait(2200)
        assert runtime.js("mainStackView.depth") == 1, "back did not return to the vendor carousel"
        runtime.keys(f"{downs}U")
    assert not [entry for entry in runtime.adapter_warnings() if "C100XMenu" in entry]


def menu_entries_retry_without_polling(work, skin):
    """A failed read keeps the entries hidden and is retried; a good read is not repeated."""
    state = {"reads": 0, "home": True, "alarm": True, "fail": 2}
    runtime = Runtime(work, skin, {"/ui/state": state_route(state)})
    check_menu(runtime, None, False, False, "failed read")
    assert state["reads"] == 1
    runtime.wait(1300)
    assert state["reads"] == 2, "no retry after one second"
    check_menu(runtime, None, False, False, "second failed read")
    runtime.wait(2300)
    check_menu(runtime, None, True, True, "retry")
    reads = state["reads"]
    runtime.wait(4500)
    assert state["reads"] == reads == 3, "polling in the working state"
    # Waking the display reads once more: a new Alarmo setup shows up without a restart.
    state["alarm"] = False
    runtime.js("global.screenState.state = 1")
    runtime.wait(100)
    assert state["reads"] == reads
    runtime.js("global.screenState.state = 2")
    runtime.wait(200)
    assert state["reads"] == reads + 1
    check_menu(runtime, None, True, False, "wake")
    # Six failed retries (63 s) end the attempt; shortened here by exhausting the counter.
    state["fail"] = 99
    runtime.js("c100xHost.refreshEntries(); c100xHost.entryRetries = 6")
    runtime.wait(300)
    runtime.js("c100xHost.readEntries()")
    runtime.wait(300)
    check_menu(runtime, None, False, False, "unreachable")
    assert not runtime.adapter_warnings(), runtime.adapter_warnings()


if __name__ == "__main__":
    globals()[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]), *sys.argv[4:])
    sys.stdout.write(sys.argv[1] + ": passed\n")
