"""The C100X display shows no memos and asks the agent for none (owner decision 2026-11-24)."""

from test_c100x_qml_adapter import ROOT, builder
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original


def test_original_firmware_has_no_memo_page_to_read_a_text_memo_on():
    original("c100x-1.5.8")
    root = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino"
    # The vendor store exists, but the station's own display has no page for it.
    assert b"/home/bticino/cfg/extra/47/memos_text" in (root / "bin/bt_answering_machine").read_bytes()
    assert not (root / "bin/gui/skins/default/MemoPage.qml").exists()


def test_adapter_ships_no_memo_page_script_or_request(tmp_path):
    assert not (ROOT / "device_qml/c100x/C100XMemos.qml").exists()
    assert not (ROOT / "device_qml/c100x/js/c100x_memos.js").exists()
    builder.build(tmp_path)
    delivered = sorted(path for path in tmp_path.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    assert len(delivered) > 20
    for path in delivered:
        assert "memo" not in path.name.lower(), path
        text = path.read_text()
        assert "/ui/memos" not in text and "C100XMemos" not in text and "c300x_memos" not in text, path
    manifest = (tmp_path / "SHA256SUMS").read_text()
    assert "memo" not in manifest.lower()
