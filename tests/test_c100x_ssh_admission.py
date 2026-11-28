"""Which station the installer serves, with real staged payloads and no remote operations."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from custom_components.bticino_c300x import device_installer as installer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from stage_device_agent_bundle import stage_bundle

    component = tmp_path / "component"
    binary = tmp_path / "agent"
    binary.write_bytes(b"offline admission payload; never executed")
    stage_bundle(component, version="test", skip_build=True, agent_binary=binary)
    monkeypatch.setattr(installer, "COMPONENT_DIR", component)
    return component


class ReadOnlyClient:
    def __init__(self, identity):
        self.identity = identity
        self.closed = False
        self.writes = []

    def run(self, command, input_data=None):
        if "libQt5Core" in command and input_data is None:
            return self.identity
        if command == "test -d /home/bticino && echo station || echo other" and input_data is None:
            return "station\n"
        self.writes.append(command)
        pytest.fail(f"Unexpected device mutation: {command}")

    def put_file(self, *args):
        self.writes.append("upload")
        pytest.fail("Unexpected device upload")

    def close(self):
        self.closed = True


def connect(monkeypatch, identity):
    client = ReadOnlyClient(identity)
    monkeypatch.setattr(installer, "_connect_device_client", lambda _: client)
    monkeypatch.setattr(installer, "_read_remote_config_sync", lambda *_: {})
    return client


def request(*, confirmed=True):
    # A caller-supplied model is not SSH identity evidence.
    return installer.C300XDeviceInstallRequest(
        host="unused.invalid", ssh_username="unused", ssh_password="unused",
        remote_dir="/agent", device_model="C100X", c100x_confirmed=confirmed,
    )


C100X_STATIONS = ["qt5\nc100x\n", "qt5\nc100x\nnamed-C100X\n", "qt4\nc100x\n"]
C300X_STATIONS = ["qt4\nc300x\n", "qt5\nc300x\n", "qt4\nc300x\nnamed-C300X\n", "qt5\nc300x\nnamed-C300X\n", ""]
# The station's own model name and its display program disagree.
MISMATCHED_STATIONS = ["qt5\nc100x\nnamed-C300X\n", "qt4\nc300x\nnamed-C100X\n", "qt5\nc300x\nnamed-C100X\n"]


@pytest.mark.parametrize("identity", C100X_STATIONS)
@pytest.mark.parametrize("damage", [
    "omitted", "deleted", "truncated", "invalid-json", "non-object", "unmarked",
    "not-compatible", "wrong-binary", "missing-binary", "duplicate-manifest", "duplicate-binary",
    "invalid-utf8", "missing-hash", "duplicate-hash",
])
def test_a_c100x_takes_only_a_bound_compatible_package(package, monkeypatch, identity, damage):
    bundle = installer._resolve_bundle("/agent")
    manifest = package / "device_agent/bundle.json"
    document = json.loads(manifest.read_text())
    if damage in {"omitted", "deleted"}:
        manifest.unlink()
        if damage == "omitted":
            bundle = replace(bundle, payload_files=tuple(
                p for p in bundle.payload_files if p.remote_path != "/agent/bundle.json"
            ))
    elif damage == "truncated":
        manifest.write_text(manifest.read_text()[:30])
    elif damage == "invalid-json":
        manifest.write_text("not-json")
    elif damage == "invalid-utf8":
        manifest.write_bytes(b"\xff")
    elif damage == "non-object":
        manifest.write_text("[]")
    elif damage in {"unmarked", "not-compatible"}:
        document.pop("c100x_compatible")
        if damage == "not-compatible":
            document["c100x_compatible"] = False
        manifest.write_text(json.dumps(document))
    elif damage in {"wrong-binary", "missing-binary"}:
        binary = package / "device_agent/armhf/c300x-agent-native"
        if damage == "wrong-binary":
            binary.write_bytes(b"unbound executable")
        else:
            binary.unlink()
    elif damage in {"missing-hash", "duplicate-hash"}:
        entry = next(item for item in document["files"]
                     if item["path"] == "device_agent/armhf/c300x-agent-native")
        if damage == "missing-hash":
            entry.pop("sha256")
        else:
            document["files"].append(entry)
        manifest.write_text(json.dumps(document))
    else:
        path = "/agent/bundle.json" if damage == "duplicate-manifest" else "/agent/c300x-agent-native"
        payload = next(p for p in bundle.payload_files if p.remote_path == path)
        bundle = replace(bundle, payload_files=(*bundle.payload_files, payload))
    client = connect(monkeypatch, identity)
    with pytest.raises(installer.C300XDeviceInstallError, match="device_model_incompatible"):
        installer._install_device_agent_sync(request(), bundle, b"{}")
    assert client.writes == []
    assert client.closed


@pytest.mark.parametrize("claimed_model", ["C300X", "C100X", ""])
def test_missing_packaged_manifest_fails_before_ssh(package, monkeypatch, claimed_model):
    (package / "device_agent/bundle.json").unlink()
    monkeypatch.setattr(installer, "_connect_device_client", lambda _: pytest.fail("SSH attempted"))
    with pytest.raises(installer.C300XDeviceInstallError, match="agent_bundle_missing"):
        asyncio.run(installer.async_install_device_agent(
            replace(request(), device_model=claimed_model),
            api_token="unused", maintenance_token="unused",
        ))


def test_the_joint_package_names_no_single_model(package):
    manifest = json.loads((package / "device_agent/bundle.json").read_text())
    assert manifest["c100x_compatible"] is True
    assert "c100x_only" not in manifest
    assert not (ROOT / "c100x-test-policy.json").exists()


@pytest.mark.parametrize("identity", C100X_STATIONS)
def test_a_c100x_is_refused_before_any_write_until_the_user_confirmed(package, monkeypatch, identity):
    bundle = installer._resolve_bundle("/agent")
    client = connect(monkeypatch, identity)
    with pytest.raises(installer.C300XDeviceInstallError, match="c100x_confirmation_required"):
        installer._install_device_agent_sync(request(confirmed=False), bundle, b"{}")
    assert client.writes == [] and client.closed
    # With the confirmation the complete package is admitted, still without a write.
    client = ReadOnlyClient(identity)
    assert installer._admit_station_sync(client, bundle, "/agent", True) == "qt5_ondisk"
    assert client.writes == []


@pytest.mark.parametrize("identity", MISMATCHED_STATIONS)
@pytest.mark.parametrize("confirmed", [False, True])
def test_a_station_with_a_contradictory_model_is_left_alone(package, monkeypatch, identity, confirmed):
    bundle = installer._resolve_bundle("/agent")
    client = connect(monkeypatch, identity)
    with pytest.raises(installer.C300XDeviceInstallError, match="device_model_incompatible"):
        installer._install_device_agent_sync(request(confirmed=confirmed), bundle, b"{}")
    assert client.writes == [] and client.closed


@pytest.mark.parametrize("identity", C300X_STATIONS)
@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("damage", [None, "deleted", "invalid-json", "unmarked"])
def test_a_c300x_is_admitted_as_before_whatever_the_c100x_marks_say(package, identity, confirmed, damage):
    """Release 2.10.0 had no admission step: a C300X passes without one."""

    bundle = installer._resolve_bundle("/agent")
    manifest = package / "device_agent/bundle.json"
    if damage == "deleted":
        manifest.unlink()
    elif damage == "invalid-json":
        manifest.write_text("not-json")
    elif damage == "unmarked":
        document = json.loads(manifest.read_text())
        document.pop("c100x_compatible")
        manifest.write_text(json.dumps(document))
    client = ReadOnlyClient(identity)
    expected = "qt5_rcc" if identity.startswith("qt5") else "qt4_ondisk"
    assert installer._admit_station_sync(client, bundle, "/agent", confirmed) == expected
    assert client.writes == []
