"""In noAuth mode a LAN web page must not reach the API (door, tokens)."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_cross_site_requests(tmp_path, sanitize):
    binary = tmp_path / "origin"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-g", "-Wall", "-Wextra", "-Werror", *flags,
         str(NATIVE / "test/http_origin_test.c"), str(NATIVE / "src/http_origin.c"), "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_every_api_route_after_the_setup_page_is_checked():
    source = (NATIVE / "src/http.c").read_text(encoding="utf-8")
    body = source[source.rindex("static void handle_api_request("):]
    check = body.index("c300x_http_cross_site_safe(request->method, origin, host, content_type)")
    assert body.index("c300x_http_setup_page(client_fd);") < check
    assert check < body.index('"/api/v1/health"')
    assert check < body.index("c300x_http_identity_route(")
