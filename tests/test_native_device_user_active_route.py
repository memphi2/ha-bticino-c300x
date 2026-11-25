"""Known forwarding modes versus foreign/Companion active routes, without devices."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
OFFICIAL = "<sip:alluser@plant.example> <sip:app@plant.example>, <sip:companion@plant.example>\n"
HA = "homeassistant-11111111-1111-1111-1111-111111111111@plant.example"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def active_route_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("active-route") / "probe"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run([
        "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
        str(NATIVE / "test/device_user_active_route_test.c"),
        *(str(NATIVE / "src" / name) for name in (
            "http_device_user.c", "device_user_label.c", "http_maintenance.c", "http_auth.c", "command_job.c",
            "string_util.c", "json_util.c", "json_parse.c", "time_util.c")),
        "-o", str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


def run(binary, path, action):
    return subprocess.run([str(binary), str(path), action], capture_output=True, text=True, timeout=10)


def snapshot(path):
    return {p.name: (p.read_bytes() if p.exists() else None,
                     str(p.readlink()) if p.is_symlink() else None)
            for p in path.iterdir()}


@pytest.mark.parametrize("mode", [
    "internal", "external", "internal_dot", "internal_absolute", "external_absolute", "regular", "regular_ha",
    "unknown", "unknown_missing", "missing", "internal_missing", "external_missing",
])
@pytest.mark.parametrize("existing", [False, True])
def test_active_route_modes(active_route_binary, tmp_path, mode, existing):
    users = tmp_path / "users"
    users.mkdir()
    (users / "users.db.txt").write_text(
        "version:1\nc100x@plant.example md5:synthetic ;\ncompanion@plant.example md5:synthetic ;\n"
        + (f"{HA} md5:synthetic ;\n" if existing else ""))
    (users / "accounts.txt").write_text(
        "App|app\nCompanion|companion\n" + ("Home Assistant|homeassistant\n" if existing else ""))
    (users / "route_int.conf").write_text(
        OFFICIAL.rstrip() + (f", <sip:{HA}>" if existing else "") + "\n")
    (users / "route_ext.conf").write_text(OFFICIAL)
    active = users / "route.conf"
    if mode in {"regular", "regular_ha"}:
        active.write_text(OFFICIAL + (f"<sip:other@plant.example> <sip:{HA}>\n" if mode == "regular_ha" else ""))
    elif mode.startswith("unknown"):
        active.symlink_to("companion.conf")
        if mode == "unknown":
            (users / "companion.conf").write_text(OFFICIAL)
    elif mode != "missing":
        target = "route_ext.conf" if mode.startswith("external") else "route_int.conf"
        active.symlink_to(users / target if mode.endswith("absolute")
                          else ("./" if mode == "internal_dot" else "") + target)
        if mode.endswith("missing"):
            (users / target).unlink()
    before = snapshot(users)
    status = run(active_route_binary, tmp_path, "status")
    assert status.returncode == 0, status.stderr
    assert snapshot(users) == before
    blocked = mode.startswith(("regular", "unknown"))
    if blocked:
        assert "supported=0 consistent=0" in status.stdout
        assert "status_error=unsupported_active_route" in status.stdout
    elif existing and mode in {"internal", "external", "internal_dot", "internal_absolute", "external_absolute"}:
        assert "supported=1 consistent=1" in status.stdout
    result = run(active_route_binary, tmp_path, "ensure")
    if blocked:
        assert result.returncode == 1, result.stdout + result.stderr
        assert "error=unsupported_active_route" in result.stdout
        assert snapshot(users) == before
        response = run(active_route_binary, tmp_path, "http")
        assert response.returncode == 0, response.stdout + response.stderr
        assert snapshot(users) == before
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert "supported=1 consistent=1" in result.stdout
    assert f"active_ha={0 if mode.startswith('external') else 1}" in result.stdout
    assert active.is_symlink()
    for name, (content, _) in before.items():
        if name == "route.conf" or content is None:
            continue
        after = (users / name).read_text()
        # Provisioning retains official/Companion users, labels and destinations.
        for token in ("companion@plant.example", "Companion|companion", "app@plant.example", "App|app"):
            if token.encode() in content:
                assert token in after
    assert "homeassistant" not in (users / "route_ext.conf").read_text()
    ensured = snapshot(users)
    assert run(active_route_binary, tmp_path, "ensure").returncode == 0
    assert snapshot(users) == ensured
