"""The agent proves it holds the API token, bound to the address HA reached."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
from collections.abc import Iterator
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import TOKEN, free_tcp_ports, wait_for_health

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"
PROOF = "/api/v1/identity/proof"
STRONG_TOKEN = "identity-proof-test-token-with-enough-length"
NONCE = "0123456789abcdef" * 4


def test_hmac_matches_rfc4231_vectors(tmp_path: Path) -> None:
    executable = tmp_path / "hmac"
    subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
         "-I", str(NATIVE / "src"), str(NATIVE / "test/hmac_sha256_test.c"),
         str(NATIVE / "src/sha256.c"), "-o", str(executable)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(executable)], check=True, timeout=5)


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("identity-build")
    subprocess.run(["make", "-C", str(NATIVE), f"BUILD_DIR={build}", "-j2", "all"],
                   check=True, capture_output=True, text=True)
    return build / "host/c300x-agent-native"


@pytest.fixture
def agent(binary: Path, tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[int]:
    port, ui_port, own = free_tcp_ports(3)
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": port, "uiPort": ui_port},
        "api": request.param,
        "openwebnet": {"host": "127.0.0.1", "port": own, "timeoutMs": 100},
        "activations": {"enabled": False, "autoDiscover": False},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
        "video": {"enabled": False}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    env = {**os.environ, "C300X_QML_DYNAMIC_HOME_PAGE": "0"}
    with (tmp_path / "agent.log").open("w") as log:
        process = subprocess.Popen([str(binary), "--config", str(path)], cwd=tmp_path,
                                   stdout=log, stderr=log, env=env)
        try:
            wait_for_health(port)
            yield port
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            assert process.returncode == 0, (tmp_path / "agent.log").read_text()


def ask(port: int, body: object, method: str = "POST") -> tuple[int, dict[str, object]]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, PROOF, body=None if body is None else json.dumps(body),
                     headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def expected_proof(token: str, device_id: str, endpoint: str, nonce: str) -> str:
    message = f"c300x-identity-v1\n{device_id}\n{endpoint}\n{nonce}"
    return hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()


@pytest.mark.parametrize("agent", [{"token": STRONG_TOKEN}], indirect=True)
def test_proof_needs_no_token_and_is_bound_to_the_reached_endpoint(agent: int) -> None:
    status, reply = ask(agent, {"nonce": NONCE})

    assert status == 200
    assert reply["ok"] is True
    device_id = reply["id"]
    assert isinstance(device_id, str) and device_id
    assert reply["proof"] == expected_proof(STRONG_TOKEN, device_id, f"127.0.0.1:{agent}", NONCE)
    # A relay that forwards HA's nonce gets a proof for this endpoint, not its own.
    assert reply["proof"] != expected_proof(STRONG_TOKEN, device_id, f"127.0.0.2:{agent}", NONCE)
    assert STRONG_TOKEN not in json.dumps(reply)


@pytest.mark.parametrize("agent", [{"token": STRONG_TOKEN}], indirect=True)
@pytest.mark.parametrize("body", [
    {}, {"nonce": NONCE[:-1]}, {"nonce": NONCE + "0"}, {"nonce": NONCE.upper()},
    {"nonce": "g" * 64}, {"nonce": 5}, {"nonce": None},
])
def test_proof_rejects_anything_but_a_64_hex_nonce(agent: int, body: dict[str, object]) -> None:
    assert ask(agent, body) == (400, {"ok": False, "error": "invalid_nonce"})


@pytest.mark.parametrize("agent", [{"token": STRONG_TOKEN}], indirect=True)
def test_proof_route_accepts_only_post(agent: int) -> None:
    assert ask(agent, None, "GET") == (405, {"ok": False, "error": "method_not_allowed"})


@pytest.mark.parametrize("agent", [{"token": TOKEN}, {"noAuth": True}], indirect=True)
def test_no_proof_without_a_strong_token(agent: int) -> None:
    # A short token would let anyone on the LAN guess it offline from one proof.
    assert len(TOKEN) < 32
    assert ask(agent, {"nonce": NONCE}) == (
        404, {"ok": False, "error": "identity_proof_unavailable"})


def test_proof_route_runs_before_the_auth_gate_and_is_not_a_home_assistant_contact() -> None:
    text = (NATIVE / "src" / "http.c").read_text(encoding="utf-8")
    start = text.index("static void handle_api_request(")
    body = text[start:text.index("\n}\n", start)]
    route = body.index("c300x_http_identity_route(client_fd, config, request)")
    gate = body.index("if (!api_request_authorized(config, request)) {\n        send_auth_required")
    assert route < gate < body.index("runtime->home_assistant_request_ms")
