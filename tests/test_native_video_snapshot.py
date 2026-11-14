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
    assert "handle_doorbell_snapshot(client_fd);" in source[route:route + 180]
