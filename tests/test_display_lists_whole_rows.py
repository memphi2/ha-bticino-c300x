"""Lists on the display never rest on a half row.

Agenda, "Leave home" and Situations filled whatever height the page gave
them, which is no multiple of a row, so the last visible row was cut in half
and "All off" under the checks was cut as well. Each list is now as high as
a whole number of rows, stops on a row, shows a thin scroll bar while there
is more, and the Leave-home buttons stay fixed under the checks.
"""

import re
from pathlib import Path

DEVICE = Path(__file__).resolve().parents[1] / "device_qml"
BAR = (
    "    Rectangle {\n"
    "        anchors.right: parent.right\n"
    "        y: %slist.visibleArea.yPosition * list.height\n"
    "        width: 3\n"
    "        height: list.visibleArea.heightRatio * list.height\n"
    "        visible: list.contentHeight > list.height\n"
    '        color: "white"\n'
    "        opacity: 0.6\n"
    "    }\n"
)
SNAP = "onMovementEnded: contentY = Math.max(0, Math.min(contentHeight - height, Math.round(contentY / 52) * 52))"


def read(name):
    return (DEVICE / name).read_text(encoding="utf-8")


def test_check_rows_have_the_pitch_the_lists_count_with():
    checks = read("C300XChecks.qml")
    assert "    spacing: 8\n" in checks and "            height: 44\n" in checks


def test_agenda_shows_whole_rows():
    agenda = read("C300XAgenda.qml")
    assert "            height: 70\n" in agenda
    assert "        height: Math.floor(Math.max(0, root.height - errorLabel.height) / 70) * 70\n" in agenda
    assert "        snapMode: ListView.SnapToItem\n" in agenda
    assert "anchors.bottom: parent.bottom\n        width: parent.width\n        clip: true" not in agenda
    assert BAR % "list.y + " in agenda


def test_situations_show_whole_rows():
    situations = read("C300XSituations.qml")
    assert "        height: Math.floor((root.height + 8) / 52) * 52 - 8\n" in situations
    assert SNAP in situations and BAR % "" in situations
    for height in range(60, 420):
        visible = (height + 8) // 52 * 52 - 8
        assert visible <= height and (visible + 8) % 52 == 0


def test_leave_home_keeps_its_buttons_under_whole_rows():
    leave = read("C300XLeaveHome.qml")
    assert "    property bool pinned: buttons.height + 60 <= height\n" in leave
    assert (
        "        height: root.pinned ? Math.floor(Math.max(0, root.height - buttons.height) / 52) * 52 - 8 : root.height\n"
    ) in leave
    assert SNAP in leave and BAR % "" in leave
    column = leave[leave.index("    Column {\n        id: buttons\n"):]
    assert "        parent: root.pinned ? root : content\n" in column
    assert "        y: root.pinned ? root.height - height : checkList.height + 8\n" in column
    # Alarm row and every action are in the fixed block, not in the scrolling part.
    assert "id: alarmMouse" in column and "model: root.actions" in column
    scrolling = leave[leave.index("    Flickable {"):leave.index("    Column {\n        id: buttons\n")]
    assert "BeepingMouseArea" not in scrolling
    for height, buttons in ((302, 116), (302, 178), (230, 116), (300, 54)):
        visible = max(0, height - buttons) // 52 * 52 - 8
        assert visible + buttons <= height and (visible + 8) % 52 == 0


def test_no_list_page_fills_a_height_that_is_no_row_multiple():
    for name in ("C300XAgenda.qml", "C300XSituations.qml", "C300XLeaveHome.qml"):
        source = read(name)
        head = re.search(r"\n    (?:ListView|Flickable) \{\n((?:        \S.*\n){5})", source).group(1)
        assert "anchors.fill: parent" not in head and "anchors.bottom: parent.bottom" not in head, name
        assert re.search(r"        height: .*Math\.floor\(", head), name
