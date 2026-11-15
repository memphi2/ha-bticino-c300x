from __future__ import annotations

import subprocess
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


def test_read_only_framebuffer_snapshot(tmp_path: Path) -> None:
    binary = tmp_path / "video-snapshot-test"
    subprocess.run(
        [
            "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            str(NATIVE / "test/video_snapshot_test.c"), "-pthread", "-o", str(binary),
        ], check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_snapshot_route_is_behind_api_authentication() -> None:
    source = (NATIVE / "src/http.c").read_text()
    route = source.index('strcmp(request->path, "/api/v1/video/doorbell/snapshot")')
    assert source.rfind("if (!api_request_authorized(config, request))", 0, route) != -1
    assert "handle_doorbell_snapshot(client_fd, request);" in source[route:route + 180]


def test_snapshot_route_takes_only_a_complete_size_the_display_can_deliver() -> None:
    """Home Assistant asks for the exact image size. The agent refuses a size
    outside the display, one that is not a plain number, and a width without a
    height, instead of delivering something else than was asked for."""

    source = (NATIVE / "src/http.c").read_text()
    handler = source[source.index("static int snapshot_dimension("):]
    handler = handler[:handler.index("static void handle_doorbell_video_activate(")]
    assert 'snapshot_dimension(request->query, "width", C300X_SNAPSHOT_MAX_WIDTH, &width)' in handler
    assert 'snapshot_dimension(request->query, "height", C300X_SNAPSHOT_MAX_HEIGHT, &height)' in handler
    assert "(width == 0) != (height == 0)" in handler
    assert "parsed < C300X_SNAPSHOT_MIN_SIZE || parsed > maximum" in handler
    assert "*end != '\\0'" in handler
    assert handler.index("invalid_snapshot_size") < handler.index("c300x_video_snapshot(&data, &size, width, height)")
    header = (NATIVE / "src/video_snapshot.h").read_text()
    assert "#define C300X_SNAPSHOT_MAX_WIDTH 800U" in header
    assert "#define C300X_SNAPSHOT_MAX_HEIGHT 480U" in header
