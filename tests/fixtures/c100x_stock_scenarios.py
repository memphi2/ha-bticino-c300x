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


FIND = ("(function find(item, name) { if (!item) return null; if (item.objectName === name) return item; "
        "var kids = item.children || []; for (var i = 0; i < kids.length; i++) { var hit = find(kids[i], name); "
        "if (hit) return hit } return null })")
ACTIONS = "controls().actions"
TOPS = ("(function() { var out = []; var list = controls().actions; for (var i = 0; i < list.length; i++) "
        "out.push(list[i].mapToItem(page, 0, 0).y); return out })()")


class Page:
    """The adapter page on top of the vendor stack, addressed in its own QML context."""

    def __init__(self, runtime):
        self.runtime = runtime

    def js(self, code):
        return self.runtime.js(code, self.runtime.js("mainStackView.currentItem.item.pageItem"))

    def shown(self, name):
        """Whether any item of that name is on the screen."""
        return self.js("(function any(item) { if (!item || !item.visible) return false; "
                       "if (item.objectName === '%s') return true; var kids = item.children || []; "
                       "for (var i = 0; i < kids.length; i++) if (any(kids[i])) return true; return false })(page)"
                       .replace("%s", name))

    def selected(self):
        """Name, and position on the screen, of the control that carries the selection."""
        return self.js(
            "(function() { var item = selectedAction; if (!item) return null; var at = item.mapToItem(page, 0, 0); "
            "return {name: item.objectName, top: at.y, bottom: at.y + item.height, left: at.x, "
            "marked: item.keyboardSelected, switch: item.checked !== undefined, editing: item.keyboardEditing} })()")


def page_warnings(runtime):
    """Adapter warnings, without two notes of the host's newer Qt and the vendor context ending first on close."""
    known = ("restoreMode has not been set", "Cannot read property 'screenState' of null")
    return [entry for entry in runtime.adapter_warnings() if not any(note in entry for note in known)]


def open_dashboard(work, skin, **data):
    from c100x_dashboard_data import build
    runtime = Runtime(work, skin, build(**data))
    runtime.wait(300)
    return runtime


def dashboard_navigation(work, skin):
    """Pages are a carousel with dots and a last EXIT; Return enters a page, focus moves and scrolls."""
    runtime = open_dashboard(work, skin)
    runtime.keys("D R", settle=2400)
    page = Page(runtime)
    assert page.js("headerLabel") == "Home Assistant" and page.js("pageCount") == 4
    # No tab bar, no More list, no pager, no back box: the station has dots and EXIT.
    assert page.js("count") == 5 and page.js("currentIndex") == 0 and page.shown("c100xDots")
    assert not page.js("tabBar.visible") and not page.js("pagerRow.visible") and not page.js("morePagesOpen")
    # The start page has nothing to operate: the page itself is selected.
    assert not page.js("inside") and page.shown("c100xPageMark") and page.selected() is None
    runtime.keys("D")
    assert page.js("currentPageIndex") == 1 and page.js("currentIndex") == 1 and page.js("headerLabel") == "Rooms"
    assert not page.js("inside") and page.shown("c100xPageMark")
    runtime.keys("R")
    first = page.selected()
    assert page.js("inside") and first["marked"] and not page.shown("c100xPageMark"), first
    count = page.js(ACTIONS + ".length")
    tops = page.js(TOPS)
    assert count >= 12 and first["top"] == min(tops), (count, first, tops)
    assert max(tops) > 440, "the Rooms page must go below the fold for this check"
    assert page.shown("c100xMoreBelow") and not page.shown("c100xMoreAbove")
    assert not page.js("scroll.c100xAction === true"), "scrolling must not be a mode of its own"
    for step in range(1, count):
        runtime.keys("D", settle=250)
        now = page.selected()
        assert now and now["marked"] and now["top"] >= 56 and now["bottom"] <= 440, (step, now)
    assert page.js("scroll.contentY") > 0 and page.shown("c100xMoreAbove") and not page.shown("c100xMoreBelow")
    # Past the last control the selection goes back to the page; the next Down is the next page.
    runtime.keys("D")
    assert not page.js("inside") and page.selected() is None and page.js("currentPageIndex") == 1
    runtime.keys("D")
    assert page.js("headerLabel") == "Agenda" and page.js("currentIndex") == 2
    # A page without controls scrolls with the same keys and shows where more is.
    assert page.shown("c100xMoreBelow")
    runtime.keys("R")
    assert page.js("inside") and page.selected() is None
    runtime.keys("2D", settle=250)
    assert page.shown("c100xMoreAbove")
    for _ in range(8):
        runtime.keys("D", settle=250)
        if not page.js("inside"):
            break
    assert not page.js("inside") and page.js("headerLabel") == "Agenda"
    assert not page.shown("c100xMoreBelow") and page.shown("c100xMoreAbove")
    # EXIT is the last entry, as in the station's own menus; no key is a back key.
    runtime.keys("2D")
    assert page.js("exitSelected") and page.js("currentIndex") == 4 and page.shown("c100xExit")
    assert not page.shown("c100xBody")
    runtime.keys("D")
    assert page.js("currentPageIndex") == 0 and not page.js("exitSelected")
    runtime.keys("U")
    assert page.js("exitSelected")
    runtime.keys("R", settle=2400)
    assert runtime.js("mainStackView.depth") == 1, "EXIT did not leave"
    assert runtime.stack(ORDER).split("|")[runtime.stack("currentIndex")] == "C100XHome.svg"
    assert not page_warnings(runtime), page_warnings(runtime)


def detail_controls(work, skin):
    """A light opens on its switch; brightness is set like a vendor regulation: Return, Up/Down, Return."""
    runtime = open_dashboard(work, skin)
    runtime.keys("D R", settle=2400)
    page = Page(runtime)
    runtime.keys("D R")
    tile = page.selected()
    runtime.keys("R")
    assert page.js("detailOpen") and page.js("view") == "d" and page.js("headerLabel").endswith("Kitchen light")
    assert page.js("count") == 2 and page.js("currentIndex") == 0
    first = page.selected()
    assert first and first["switch"] and first["marked"], first
    assert page.js(ACTIONS + ".length") == 2, "switch and slider only: no minus and plus stops"
    runtime.keys("D")
    slider = page.selected()
    assert slider["name"] == "c100xNumericSlider" and not slider["editing"], slider
    assert page.js("selectedAction.keyboardConfirming") is None, "no Cancel/Apply prompt any more"
    runtime.keys("R")
    assert page.selected()["editing"]
    before = [url for method, url, body in runtime.requests if "brightness" in url]
    runtime.keys("3D", settle=200)
    assert page.selected()["editing"] and not [url for method, url, body in runtime.requests if "brightness" in url][len(before):]
    runtime.keys("R")
    sent = [url for method, url, body in runtime.requests if "brightness" in url][len(before):]
    assert len(sent) == 1 and "light.kitchen%3Abrightness&option=74" in sent[0], sent
    assert not page.selected()["editing"]
    # Past the last control comes EXIT; it closes the detail and the tile is selected again.
    runtime.keys("D")
    assert page.js("exitSelected") and page.shown("c100xExit") and page.js("currentIndex") == 1
    runtime.keys("U")
    assert not page.js("exitSelected") and page.selected()["name"] == "c100xNumericSlider"
    runtime.keys("D R")
    assert not page.js("detailOpen") and page.js("view") == ""
    runtime.wait(400)
    again = page.selected()
    assert again and again["marked"] and (again["top"], again["left"]) == (tile["top"], tile["left"]), (tile, again)
    assert not page_warnings(runtime), page_warnings(runtime)


def alarmo_page(work, skin):
    """Alarmo opens on its first control, is called Alarmo, and leaves through EXIT."""
    runtime = open_dashboard(work, skin, pin=True)
    runtime.keys("2D R", settle=2400)
    page = Page(runtime)
    assert page.js("headerLabel") == "Alarmo" and page.js("icon") == "C100XAlarm.svg"
    first = page.selected()
    assert page.js("inside") and first and first["marked"], first
    tops = page.js(TOPS)
    assert first["top"] == min(tops) and min(tops) >= 56, "no back box in the header"
    runtime.keys("U")
    assert page.js("exitSelected") and page.shown("c100xExit")
    runtime.keys("R", settle=2400)
    assert runtime.js("mainStackView.depth") == 1
    assert not page_warnings(runtime), page_warnings(runtime)


def alert_runtime(work, skin):
    """The dashboard agent; its notice request sleeps until send_alert answers it."""
    from c100x_dashboard_data import build
    runtime = Runtime(work, skin, build())
    runtime.wait(600)
    return runtime


def send_alert(runtime, message="The garage door is open.", settle=900):
    """Answer the sleeping notice request, as the agent does when Home Assistant sends one."""
    import time
    now = int(time.time() * 1000)
    reply = runtime.sleeping.pop("/ui/alerts/next", None)
    try:
        if reply is None or reply.isFinished():
            return False
    except RuntimeError:
        # The page dropped the request; Qt has deleted the reply.
        return False
    reply.answer({"id": "a" * 32, "notification_id": "garage_door", "revision": "b" * 32, "wake_duration": 30,
                  "sound_duration": 0, "expires_in": 600, "remaining_ms": 4000, "expires": now + 600000,
                  "message_expires": now + 600000, "severity": "warning", "title": "Garage door", "message": message})
    runtime.wait(settle)
    return True


def alert_shown(runtime):
    return bool(runtime.js("(function() { var button = FIND(c100xAlerts.item, 'alertAcknowledge'); "
                           "return !!button && button.parent.visible })()".replace("FIND", FIND)))


def acknowledged(runtime):
    return [url for method, url, body in runtime.requests if "notification.garage_door" in url]


def vendor_keys(runtime, where):
    """Up, Down and Return reach the vendor's current page: the window's active focus is inside it."""
    assert runtime.js("(function() { var item = window.activeFocusItem; var page = mainStackView.currentItem; "
                      "while (item && item !== page) item = item.parent; return !!item })()"), where + ": focus lost"


def main_menu_keys(runtime, where):
    vendor_keys(runtime, where)
    assert runtime.js("mainStackView.depth") == 1, where
    index, count = runtime.stack("currentIndex"), runtime.stack("count")
    runtime.keys("D")
    assert runtime.stack("currentIndex") == (index + 1) % count, where + ": Down is dead in the main menu"
    runtime.keys("U")
    assert runtime.stack("currentIndex") == index, where + ": Up is dead in the main menu"


def start_call(runtime):
    depth = runtime.js("mainStackView.depth")
    runtime.js("global.cctv.callInProgress = true; global.cctv.incomingCall()")
    runtime.wait(600)
    assert runtime.js("mainStackView.depth") == depth + 1, "the vendor did not push its call page"
    assert runtime.js("mainStackView.currentItem.menuVisible") is False


def call_menu_keys(runtime, where):
    """Any key shows the call menu, Down moves in it, Return on its Exit closes it."""
    vendor_keys(runtime, where)
    assert runtime.js("mainStackView.currentItem.activeFocus"), where + ": call page without active focus"
    runtime.keys("D", settle=600)
    assert runtime.js("mainStackView.currentItem.menuVisible"), where + ": Down did not show the call menu"
    index = runtime.js("mainStackView.currentItem.currentIndex")
    runtime.keys("D", settle=600)
    assert runtime.js("mainStackView.currentItem.currentIndex") == index + 1, where + ": Down is dead in the call menu"
    runtime.keys("U", settle=600)
    assert runtime.js("mainStackView.currentItem.currentIndex") == index, where + ": Up is dead in the call menu"
    count = runtime.js("mainStackView.currentItem.count")
    runtime.keys(f"{count - 1 - index}D", settle=600)
    runtime.keys("R", settle=600)
    assert runtime.js("mainStackView.currentItem.menuVisible") is False, where + ": Return is dead in the call menu"


def end_call(runtime):
    """The vendor ends a call by turning the screen off, which pops every page; then a key wakes the station."""
    runtime.js("global.cctv.callInProgress = false; global.cctv.callEnded(); global.screenState.state = 1")
    runtime.wait(800)
    assert runtime.js("mainStackView.depth") == 1
    runtime.js("global.screenState.state = 2")
    runtime.wait(1500)


def alert_covers_the_screen(work, skin):
    """A notice fills the screen and shows that Return marks it read."""
    runtime = alert_runtime(work, skin)
    assert send_alert(runtime, "The garage door has been open for 15 minutes. " * 10)
    panel = runtime.js(
        "(function() { var button = FIND(c100xAlerts.item, 'alertAcknowledge'); if (!button) return null; "
        "var bar = FIND(button, 'alertFocusBar'); var scroll = FIND(c100xAlerts.item, 'alertMessageScroll'); "
        "var at = button.parent.mapToItem(null, 0, 0); "
        "return {shown: button.parent.visible, x: at.x, y: at.y, width: button.parent.width, "
        "height: button.parent.height, bar: !!bar && bar.visible && bar.height >= 5, "
        "more: scroll.contentHeight > scroll.height} })()".replace("FIND", FIND))
    assert panel and panel["shown"], panel
    assert (panel["x"], panel["y"], panel["width"], panel["height"]) == (0, 0, 800, 480), panel
    assert panel["bar"], "Mark read does not show that Return acts on it"
    assert panel["more"] and runtime.js(FIND + "(c100xAlerts.item, 'c100xMoreBelow').visible")
    runtime.keys("D", settle=300)
    assert runtime.js(FIND + "(c100xAlerts.item, 'c100xMoreAbove').visible")
    runtime.keys("R", settle=600)
    assert acknowledged(runtime), "not acknowledged"
    assert not runtime.adapter_warnings(), runtime.adapter_warnings()


def mark_read(runtime, where):
    assert alert_shown(runtime), where + ": no notice"
    runtime.keys("R", settle=800)
    assert acknowledged(runtime) and not alert_shown(runtime), where + ": Return did not mark the notice read"


def alert_dismissed_returns_the_keys(work, skin, start):
    """Mark read on the main menu or on the Home Assistant page: what is under the notice has the keys again."""
    runtime = alert_runtime(work, skin)
    if start == "page":
        runtime.keys("D R", settle=2400)
        page = Page(runtime)
        assert page.js("currentPageIndex") == 0
    index = runtime.stack("currentIndex")
    assert send_alert(runtime)
    assert alert_shown(runtime)
    runtime.keys("D", settle=300)
    assert runtime.stack("currentIndex") == index, "a key went to the page under the notice"
    mark_read(runtime, start)
    if start == "page":
        vendor_keys(runtime, "page after Mark read")
        runtime.keys("D")
        assert page.js("currentPageIndex") == 1, "Down is dead on the Home Assistant page"
        runtime.keys("U U")
        assert page.js("exitSelected"), "Up is dead on the Home Assistant page"
        runtime.keys("R", settle=2400)
    main_menu_keys(runtime, "after Mark read")
    assert not page_warnings(runtime), page_warnings(runtime)


def alert_then_call(work, skin, start):
    """A call takes the screen from a notice: the call menu and afterwards the main menu have the keys."""
    runtime = alert_runtime(work, skin)
    if start == "page":
        runtime.keys("D R", settle=2400)
        assert runtime.js("mainStackView.currentItem.item.pageName") == "HomeAssistant.qml"
    assert send_alert(runtime)
    assert alert_shown(runtime), "no notice on the " + start
    start_call(runtime)
    assert not alert_shown(runtime), "notice over a call"
    call_menu_keys(runtime, "call after a notice")
    end_call(runtime)
    main_menu_keys(runtime, "after the call")
    assert not page_warnings(runtime), page_warnings(runtime)


def alert_screen_off_on_page(work, skin):
    """The screen goes off under a notice on the Home Assistant page; the vendor pops to the main menu."""
    runtime = alert_runtime(work, skin)
    runtime.keys("D R", settle=2400)
    assert send_alert(runtime)
    assert alert_shown(runtime) and runtime.js("mainStackView.depth") == 2
    runtime.js("global.screenState.state = 1")
    runtime.wait(800)
    assert runtime.js("mainStackView.depth") == 1
    runtime.js("global.screenState.state = 2")
    runtime.wait(1500)
    if alert_shown(runtime):
        mark_read(runtime, "after screen off and on")
    main_menu_keys(runtime, "after screen off and on")
    assert not page_warnings(runtime), page_warnings(runtime)


def alert_adapter_stops(work, skin):
    """The adapter stops under a notice (bridge unloaded): the notice goes and the main menu has the keys."""
    runtime = alert_runtime(work, skin)
    assert send_alert(runtime)
    assert alert_shown(runtime)
    runtime.js("c100xHost.running = false")
    runtime.wait(600)
    assert runtime.js("c100xAlerts.item === null")
    main_menu_keys(runtime, "after the adapter stopped")
    assert not page_warnings(runtime), page_warnings(runtime)


def alert_during_call(work, skin):
    """During a call no notice is fetched and none takes a key; afterwards it shows and gives the keys back."""
    runtime = alert_runtime(work, skin)
    start_call(runtime)
    assert not send_alert(runtime), "a notice request stayed open during the call"
    assert not alert_shown(runtime)
    call_menu_keys(runtime, "during a call")
    end_call(runtime)
    runtime.wait(1500)
    assert send_alert(runtime), "no notice request after the call"
    mark_read(runtime, "after the call")
    main_menu_keys(runtime, "after the call and Mark read")
    assert not page_warnings(runtime), page_warnings(runtime)


if __name__ == "__main__":
    globals()[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]), *sys.argv[4:])
    sys.stdout.write(sys.argv[1] + ": passed\n")
