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


if __name__ == "__main__":
    globals()[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
    sys.stdout.write(sys.argv[1] + ": passed\n")
