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


if __name__ == "__main__":
    globals()[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
    sys.stdout.write(sys.argv[1] + ": passed\n")
