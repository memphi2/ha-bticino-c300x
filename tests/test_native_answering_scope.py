"""The C100X has no answering machine: its routes are refused before any device I/O."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"


def test_c100x_refuses_answering_routes_and_c300x_keeps_them(tmp_path: Path) -> None:
    binary = tmp_path / "answering-scope-test"
    subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
         NATIVE / "src/answering_scope.c", NATIVE / "test/answering_scope_test.c",
         "-Wl,--wrap=c300x_device_model,--wrap=c300x_http_send_json", "-o", binary],
        check=True,
    )
    subprocess.run([binary], check=True, timeout=5)


def test_the_gate_runs_before_every_answering_and_voice_memo_handler() -> None:
    source = (NATIVE / "src/http.c").read_text(encoding="utf-8")
    gate = source.index("if (c300x_answering_route_refused(client_fd, request)) return;")
    for handler in ("handle_answering_get(client_fd", "handle_answering_messages_get(client_fd",
                    "handle_answering_message_video_get(client_fd", "handle_answering_message_delete(client_fd",
                    "handle_memo_audio_get(client_fd", "handle_memos_delete(client_fd",
                    "handle_answering_post(client_fd"):
        calls = [index for index in range(len(source)) if source.startswith(handler, index)]
        assert calls and all(index > gate for index in calls), handler
    assert source.count("c300x_answering_route_refused(") == 1
