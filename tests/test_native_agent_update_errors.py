"""Update error responses use transaction state, not errno or rollback guesses."""

import json
import subprocess
from http.client import HTTPConnection

import pytest
from native_build import default_host_build
from test_native_media_control_offload import NATIVE, TOKEN, Lab
from test_native_media_control_offload import lab as lab


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    objects = sorted((default_host_build(tmp_path_factory) / "host").glob("*.o"))
    target = tmp_path_factory.mktemp("update-errors-build") / "agent-with-update-errors"
    result = subprocess.run([
        "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
        str(NATIVE / "test/media_bridge_hold_stub.c"),
        str(NATIVE / "test/agent_update_http_stub.c"),
        *(str(path) for path in objects if path.name != "media_bridge.o"),
        "-Wl,--wrap=apply_agent_update_files", "-pthread", "-ldl", "-o", str(target),
    ], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return target


@pytest.mark.parametrize("lab", [{"maintenance": {"enabled": True, "adminToken": "update-admin"}}], indirect=True)
@pytest.mark.parametrize("error,status,code", [
    (0, 500, "update_apply_failed"),
    (1, 409, "update_root_already_writable"),
    (2, 500, "update_root_readonly_failed"),
])
def test_update_failure_http_contract(lab: Lab, error, status, code):
    staged = lab.root / ".update/device_agent/bundle.json"
    staged.parent.mkdir(parents=True)
    content = json.dumps({"bundle_hash": "sha256:test"})
    staged.write_text(content)
    (lab.root / "update-error").write_text(str(error))
    body = json.dumps({"confirm": "update_agent", "bundle_hash": "sha256:test"})
    for authorized in (False, True):
        headers = {"Authorization": "Bearer " + TOKEN}
        if authorized:
            headers["X-Bticino-C300X-Maintenance-Token"] = "update-admin"
        conn = HTTPConnection("127.0.0.1", lab.api_port, timeout=5)
        try:
            conn.request("POST", "/api/v1/maintenance/update/apply", body=body, headers=headers)
            response = conn.getresponse()
            payload = json.loads(response.read())
            assert response.status == (status if authorized else 403), payload
            assert payload == {"ok": False, "error": code if authorized else "maintenance_unauthorized"}
        finally:
            conn.close()
        assert staged.read_text() == content
        assert lab.process.poll() is None
