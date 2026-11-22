"""Credential selection with fake SSH only; the firmware check is offline."""

import asyncio
import hmac
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x.device_installer import (
    C300XDeviceInstallRequest,
    _AsyncSshDeviceSshClient,
)
from custom_components.bticino_c300x.factory_login import (
    factory_login_candidates,
    factory_ssh_login,
    login_model,
    ssh_login,
    uses_factory_login,
)


class Refused(Exception):
    pass


def request(model="", automatic=True, manual=False):
    username, password = ("operator", "typed") if manual else factory_ssh_login(model)
    return C300XDeviceInstallRequest(host="unused.invalid", ssh_username=username,
                                    ssh_password=password, factory_login=automatic, device_model=model)


@pytest.mark.parametrize("model,count", [("", 2), ("C100X", 1), ("C300X", 1)])
def test_factory_candidates_are_bounded_and_model_specific(model, count):
    candidates = factory_login_candidates(model)
    assert len(candidates) == count
    assert len(set(candidates)) == count
    assert candidates[0] == factory_ssh_login(model)


@pytest.mark.parametrize("input", [
    {"user": "operator", "password": "typed"},
    {"user": "root", "password": ""},
    {"user": "", "password": "typed"},
])
def test_partial_or_complete_explicit_credentials_never_trigger_defaults(input):
    assert not uses_factory_login(input, "user", "password")
    assert ssh_login(input, "user", "password", "C100X") == (input["user"], input["password"])


def test_known_model_and_credential_repr_do_not_guess_or_leak():
    assert login_model({"device": {"model": "C100X"}}) == "C100X"
    assert login_model({"hostname": "C100X.local"}) == ""
    assert login_model(None) == ""
    assert uses_factory_login(None, "user", "password")
    assert request("C100X").ssh_password not in repr(request("C100X"))


@pytest.mark.parametrize("model,automatic,manual,outcome,count", [
    ("", True, False, "success", 1),
    ("", True, False, "second", 2),
    ("", True, False, "refused", 2),
    ("C100X", True, False, "refused", 1),
    ("C300X", True, False, "refused", 1),
    ("", False, False, "refused", 1),
    ("", False, True, "refused", 1),
    ("", True, True, "refused", 1),
    ("", True, False, "timeout", 1),
    ("", True, False, "network", 1),
])
def test_connect_retries_only_automatic_unknown_model_after_auth_refusal(
    model, automatic, manual, outcome, count
):
    connected = object()
    effects = {"success": [connected], "second": [Refused(), connected],
               "refused": [Refused(), Refused()], "timeout": [TimeoutError()],
               "network": [OSError()]}
    connect = AsyncMock(side_effect=effects[outcome])
    client = object.__new__(_AsyncSshDeviceSshClient)
    client._asyncssh = SimpleNamespace(connect=connect, PermissionDenied=Refused)
    req = request(model, automatic, manual)
    if outcome in {"success", "second"}:
        assert asyncio.run(client._connect(req)) is connected
    else:
        with pytest.raises((Refused, OSError)):
            asyncio.run(client._connect(req))
    assert connect.await_count == count
    assert connect.call_args_list[0].kwargs["password"] == req.ssh_password
    if count == 2:
        assert connect.call_args_list[1].kwargs["password"] == factory_ssh_login("C100X")[1]


def test_c100x_default_matches_original_158_shadow_offline():
    from test_native_routing_firmware_restore import FIRMWARE_ROOT
    shadow = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/etc/shadow"
    if not shadow.is_file() or not shutil.which("openssl"):
        pytest.skip("Optional original firmware / openssl absent")
    stored = next(line.split(":")[1] for line in shadow.read_text().splitlines()
                  if line.startswith("root:"))
    assert stored.startswith("$6$")
    result = subprocess.run(["openssl", "passwd", "-6", "-salt", stored.split("$")[2], "-stdin"],
                            input=factory_ssh_login("C100X")[1] + "\n", capture_output=True,
                            text=True, check=True, timeout=5)
    matches = hmac.compare_digest(result.stdout.strip(), stored)
    assert matches
