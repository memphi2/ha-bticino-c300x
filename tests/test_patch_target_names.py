"""Binary-patch targets keep the established masked-name convention."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "native_agent/src"


def test_display_patch_assembles_its_target_name() -> None:
    source = (ROOT / "display_touch.c").read_text()
    name = "libQt" + "GuiE.so.4.8.7"
    assert name not in source
    assert 'C300X_DISPLAY_TOUCH_TARGET_MASK "l?bQ?Gu?E.so.4.8.7"' in source
    assert "name[replacements[index].offset] = replacements[index].value" in source


def test_geometry_patch_and_process_lookup_do_not_embed_the_target_name() -> None:
    name = "bt_" + "av_media"
    for filename in ("media_geometry_patch.c", "media_geometry_patch.h", "camera_running.c"):
        assert name not in (ROOT / filename).read_text(), filename
    assert "c300x_media_geometry_process_name" in (ROOT / "camera_running.c").read_text()
