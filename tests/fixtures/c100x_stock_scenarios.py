"""Key-driven scenarios on the original C100X main.qml; see c100x_stock_runtime."""

import sys
from pathlib import Path

from c100x_stock_runtime import Runtime

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


if __name__ == "__main__":
    globals()[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
    sys.stdout.write(sys.argv[1] + ": passed\n")
