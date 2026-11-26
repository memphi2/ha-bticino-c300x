"""Exercise the production bootstrap client against a local legacy SSH server."""

from __future__ import annotations

import asyncio
import concurrent.futures
import signal
import threading
import time
from pathlib import Path

import asyncssh
import pytest

from custom_components.bticino_c300x import device_installer as installer


@pytest.fixture
def host_key_type() -> str:
    """The host key of the factory station's Dropbear."""
    return "ssh-rsa"


@pytest.fixture
def station_login() -> dict:
    """What the station's SSH server accepts: the factory Dropbear takes passwords only.

    "keys": public keys of test-user; "password": False is a key-only build (dropbear -s).
    """
    return {"password": True, "keys": []}


@pytest.fixture(params=["diffie-hellman-group14-sha1", "diffie-hellman-group1-sha1"])
def ssh_server(monkeypatch, request, host_key_type, station_login):
    ready = concurrent.futures.Future()
    failures = []
    state = {}

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return True

        def password_auth_supported(self):
            return station_login["password"]

        def validate_password(self, username, password):
            return username == "test-user" and password == "test-password"

        def public_key_auth_supported(self):
            return bool(station_login["keys"])

        def validate_public_key(self, username, key):
            return username == "test-user" and any(
                key.public_data == known.public_data for known in station_login["keys"]
            )

    async def process_handler(process):
        assert process.term_type is None
        state.setdefault("commands", []).append(process.command)
        if process.command == "id -u":
            # The user id of the login: the station's root unless a test says otherwise.
            process.stdout.write(f"{station_login.get('uid', 0)}\n".encode())
            process.exit(0)
            return
        if process.command == "hang":
            await process.stdin.read()
            await state["stop"].wait()
            return
        child = await asyncio.create_subprocess_shell(
            process.command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        # Like the station's SSH server: a "signal" request goes to the
        # command's process alone, and nothing is sent when a channel closes.
        process.signal_received = lambda name: child.send_signal(getattr(signal, f"SIG{name}"))
        try:
            stdout, stderr = await child.communicate(await process.stdin.read())
            process.stdout.write(stdout)
            process.stderr.write(stderr)
            process.exit(child.returncode)
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()

    async def serve():
        state["loop"] = asyncio.get_running_loop()
        state["stop"] = asyncio.Event()
        async with asyncssh.listen(
            "127.0.0.1", 0, server_factory=Server,
            server_host_keys=[asyncssh.generate_private_key(
                host_key_type, **({"key_size": 2048} if host_key_type == "ssh-rsa" else {}),
            )],
            # Only this host key is offered, as by a Dropbear given one key (dropbear -r);
            # user keys sign with the algorithms the station takes besides.
            signature_algs=[host_key_type, *station_login.get("sig_algs", [])], kex_algs=[request.param],
            encryption_algs=["aes128-cbc"], process_factory=process_handler,
            encoding=None,
        ) as server:
            ready.set_result(server.get_port())
            await state["stop"].wait()

    def serve_thread():
        try:
            asyncio.run(serve())
        except BaseException as err:
            failures.append(err)
            if not ready.done():
                ready.set_exception(err)

    thread = threading.Thread(target=serve_thread, daemon=True)
    thread.start()
    port = ready.result(timeout=10)
    original = installer._asyncssh_connect_kwargs

    def connection_options(value):
        return {**original(value), "port": port}

    monkeypatch.setattr(installer, "_asyncssh_connect_kwargs", connection_options)
    station_login["commands"] = state.setdefault("commands", [])
    try:
        yield installer.C300XDeviceInstallRequest(
            host="127.0.0.1", ssh_username="test-user", ssh_password="test-password",
        )
    finally:
        state["loop"].call_soon_threadsafe(state["stop"].set)
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert not failures


def test_legacy_login_commands_binary_input_and_close(ssh_server):
    client = installer._connect_device_client(ssh_server)
    try:
        assert client.run("printf 'ready\\n'") == "ready\n"
        assert client.run("cat", b"payload\x00\xff") == "payload\x00\ufffd"
        payload = b"x" * (2 * 1024 * 1024)
        assert client.run("cat", payload) == payload.decode()
        assert client.run("printf 'out'; printf 'err' >&2") == "out"
    finally:
        client.close()
        client.close()
    with pytest.raises(installer.C300XDeviceInstallError, match="device_install_failed"):
        client.run("true")


@pytest.mark.parametrize("host_key_type", [
    "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521", "ssh-ed25519",
])
def test_a_station_with_only_one_host_key_type_is_reached(ssh_server, host_key_type):
    """Root tools can set up Dropbear with an ECDSA or Ed25519 key only."""
    client = installer._connect_device_client(ssh_server)
    try:
        assert client.run("printf 'ready'") == "ready"
    finally:
        client.close()


def _user_key(key_type: str):
    return asyncssh.generate_private_key(key_type, **({"key_size": 2048} if key_type == "ssh-rsa" else {}))


@pytest.mark.parametrize("host_key_type", ["ssh-rsa"])
@pytest.mark.parametrize(("key_type", "key_format", "passphrase", "sig_algs"), [
    # Dropbear 2017.75 (1.7.19, 2.0.2, C100X 1.5.8): RSA signed with SHA-1, ECDSA.
    ("ssh-rsa", "openssh", "", []),
    ("ssh-rsa", "pkcs1-pem", "", []),
    ("ecdsa-sha2-nistp256", "openssh", "secret phrase", ["ecdsa-sha2-nistp256"]),
    ("ecdsa-sha2-nistp256", "pkcs8-pem", "secret phrase", ["ecdsa-sha2-nistp256"]),
    # Dropbear 2020.81 (3.0.6): also Ed25519 and RSA with SHA-256.
    ("ssh-ed25519", "openssh", "", ["ssh-ed25519"]),
    ("ssh-ed25519", "openssh", "secret phrase", ["ssh-ed25519"]),
    ("ssh-rsa", "openssh", "secret phrase", ["rsa-sha2-256"]),
])
@pytest.mark.parametrize("password", ["", "test-password"])
def test_a_key_only_station_is_reached_with_a_pasted_private_key(
    ssh_server, station_login, host_key_type, key_type, key_format, passphrase, sig_algs, password,
):
    """A root tool can turn password logins off (dropbear -s): the key logs in."""
    from dataclasses import replace

    key = _user_key(key_type)
    station_login.update(password=False, keys=[key], sig_algs=sig_algs)
    pasted = key.export_private_key(key_format, passphrase or None).decode()
    # Pasted into a form: Windows line ends and surrounding blanks.
    pasted = "  " + pasted.replace("\n", "\r\n") + "\n "
    client = installer._connect_device_client(replace(
        ssh_server, ssh_password=password, ssh_private_key=pasted, ssh_key_passphrase=passphrase,
    ))
    try:
        assert client.run("printf 'ready'") == "ready"
    finally:
        client.close()


@pytest.mark.parametrize("host_key_type", ["ssh-rsa"])
def test_a_refused_key_falls_back_to_the_typed_password(ssh_server, station_login):
    from dataclasses import replace

    station_login.update(keys=[_user_key("ecdsa-sha2-nistp256")], sig_algs=["ecdsa-sha2-nistp256"])
    other = _user_key("ecdsa-sha2-nistp256").export_private_key("openssh").decode()
    client = installer._connect_device_client(replace(ssh_server, ssh_private_key=other))
    try:
        assert client.run("printf 'ready'") == "ready"
    finally:
        client.close()
    with pytest.raises(installer.C300XDeviceInstallError, match="ssh_login_refused"):
        installer._connect_device_client(replace(ssh_server, ssh_password="", ssh_private_key=other))


@pytest.mark.parametrize("pasted", [
    "not a key", "PUBLIC",
    "ENCRYPTED",
])
def test_an_unreadable_key_is_named_and_never_quoted(ssh_server, caplog, pasted):
    from dataclasses import replace

    key = _user_key("ssh-ed25519")
    text = {
        "PUBLIC": key.export_public_key("openssh").decode(),
        "ENCRYPTED": key.export_private_key("openssh", "right").decode(),
    }.get(pasted, pasted)
    with pytest.raises(installer.C300XDeviceInstallError) as caught:
        # A wrong passphrase reads like no key at all.
        installer._connect_device_client(replace(ssh_server, ssh_private_key=text, ssh_key_passphrase="wrong"))
    assert caught.value.reason == "invalid_ssh_key"
    # No library message rides along: it could quote the key.
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert text.strip() not in caplog.text and "wrong" not in caplog.text
    assert text.strip() not in repr(replace(ssh_server, ssh_private_key=text))


@pytest.mark.parametrize(("uid", "reason"), [(1000, "ssh_user_not_root"), (0, None)])
def test_the_login_is_checked_for_root_rights_before_any_step(ssh_server, station_login, uid, reason):
    """A tool's second user (bticino2, uid 1000) logs in but cannot install anything."""
    station_login["uid"] = uid
    if reason is not None:
        with pytest.raises(installer.C300XDeviceInstallError) as caught:
            installer._connect_device_client(ssh_server)
        assert caught.value.reason == reason
        # Nothing else ran on the station.
        assert station_login["commands"] == ["id -u"]
        return
    client = installer._connect_device_client(ssh_server)
    try:
        assert station_login["commands"] == ["id -u"]
    finally:
        client.close()


def test_command_failure_does_not_expose_remote_output(ssh_server):
    client = installer._connect_device_client(ssh_server)
    try:
        with pytest.raises(installer.C300XDeviceInstallError) as result:
            client.run("printf 'private-details' >&2; exit 7")
        assert str(result.value) == "device_install_failed"
        assert client.run("true") == ""
    finally:
        client.close()


def test_wrong_password_fails_cleanly(ssh_server):
    from dataclasses import replace

    with pytest.raises(installer.C300XDeviceInstallError, match="ssh_login_refused"):
        installer._connect_device_client(replace(ssh_server, ssh_password="wrong"))


def test_command_timeout_closes_channel(ssh_server, monkeypatch):
    client = installer._connect_device_client(ssh_server)
    monkeypatch.setattr(installer, "_SSH_COMMAND_TIMEOUT", 0.1)
    try:
        with pytest.raises(installer.C300XDeviceInstallError, match="device_install_failed"):
            client.run("hang")
        assert client.run("true") == ""
    finally:
        client.close()


DISPLAY_STAND_IN = """#!/bin/sh
{trap}
[ "$C300X_QML_SOURCE_DIR" = "${{0%/*}}/qml" ] || exit 9
: > "$0.started"
i=0
while [ $i -lt 400 ]; do sleep 0.02; i=$((i + 1)); done
: > "$0.ended"
"""


@pytest.mark.parametrize(("trap", "rolled_back", "grace"), [
    # The grace is far above any scheduling delay: only a client that waits
    # for all of it instead of for the script's end reaches it.
    ("trap 'sleep 0.2; printf rolling >&2; : > \"$0.rolled\"; exit 130' TERM", True, 30.0),
    ("trap '' TERM", False, 1.0),
])
def test_a_display_write_past_its_deadline_is_ended_by_sigterm_and_reported(
    ssh_server, monkeypatch, tmp_path: Path, trap: str, rolled_back: bool,
    grace: float,
) -> None:
    """The display write over SSH gets the agent's job handling: SIGTERM for
    the script itself at the deadline, the channel open while its trap rolls
    back, and an error of its own. A stand-in that ignores the signal costs
    the grace period, no more; it ends by itself."""

    script = tmp_path / "qml_patch.sh"
    script.write_text(DISPLAY_STAND_IN.format(trap=trap))
    script.chmod(0o700)
    monkeypatch.setattr(installer, "_device_display_kind", lambda client: "qt4_ondisk")
    monkeypatch.setattr(installer, "_SSH_DISPLAY_WRITE_TIMEOUT", 0.5, raising=False)
    monkeypatch.setattr(installer, "_SSH_DISPLAY_WRITE_TERM_GRACE", grace, raising=False)
    client = installer._connect_device_client(ssh_server)
    started = time.monotonic()
    try:
        with pytest.raises(installer.C300XDeviceInstallError) as result:
            installer._apply_qml_patch_sync(client, str(tmp_path), "core-apply")
        elapsed = time.monotonic() - started
        assert result.value.reason == "device_display_timeout"
        assert script.with_name("qml_patch.sh.started").exists()
        assert script.with_name("qml_patch.sh.rolled").exists() is rolled_back
        if rolled_back:
            # Back as soon as the trap is done, not after the grace.
            assert elapsed < grace
        else:
            # The whole grace was spent, and the client did not wait for the
            # stand-in's own end eight seconds later.
            assert elapsed >= 0.5 + grace
            assert not script.with_name("qml_patch.sh.ended").exists()
        # The connection is still good for the next step or attempt.
        assert client.run("true") == ""
    finally:
        client.close()


def test_a_display_step_past_its_deadline_on_the_qt5_display_is_ended_the_same_way(
    ssh_server, monkeypatch, tmp_path: Path,
) -> None:
    """Firmware 3.0.x: the display step is the same write, with the same
    command form and limits. Ended at its deadline it is not an owed step (it
    did not finish): the install fails with the display timeout, as on
    1.7.x/2.0.2."""

    script = tmp_path / "qml_patch.sh"
    script.write_text(DISPLAY_STAND_IN.format(
        trap="trap 'sleep 0.2; : > \"$0.rolled\"; exit 130' TERM"))
    script.chmod(0o700)
    grace = 30.0
    monkeypatch.setattr(installer, "_SSH_DISPLAY_WRITE_TIMEOUT", 0.5, raising=False)
    monkeypatch.setattr(installer, "_SSH_DISPLAY_WRITE_TERM_GRACE", grace, raising=False)
    client = installer._connect_device_client(ssh_server)
    started = time.monotonic()
    try:
        with pytest.raises(installer.C300XDeviceInstallError) as result:
            installer._apply_display_step_sync(client, str(tmp_path), "core-apply", qt5=True)
        assert result.value.reason == "device_display_timeout"
        # The stand-in starts only when C300X_QML_SOURCE_DIR arrived.
        assert script.with_name("qml_patch.sh.started").exists()
        assert script.with_name("qml_patch.sh.rolled").exists()
        # Back as soon as the trap is done, not after the grace.
        assert time.monotonic() - started < grace
        assert client.run("true") == ""
    finally:
        client.close()


@pytest.mark.parametrize("refusal", [None, OSError("Channel not open")])
def test_a_display_write_whose_channel_closed_at_the_deadline_is_a_timeout(
    ssh_server, monkeypatch, tmp_path: Path, refusal: OSError | None,
) -> None:
    """The channel can close in the loop pass in which the deadline fires.
    The signal then has nowhere to go: the pinned AsyncSSH drops it silently,
    its documentation announces OSError. Either way the write ran past its
    deadline and its outcome on the station is unknown, which is the display
    time-out and not a general install failure; nothing waits for the grace."""

    script = tmp_path / "qml_patch.sh"
    script.write_text(DISPLAY_STAND_IN.format(trap=""))
    script.chmod(0o700)
    grace = 30.0
    monkeypatch.setattr(installer, "_device_display_kind", lambda client: "qt4_ondisk")
    monkeypatch.setattr(installer, "_SSH_DISPLAY_WRITE_TIMEOUT", 0.5)
    monkeypatch.setattr(installer, "_SSH_DISPLAY_WRITE_TERM_GRACE", grace)
    client = installer._connect_device_client(ssh_server)
    create_process = client._client.create_process
    signalled: list[bool] = []

    async def closing_process(*args, **kwargs):
        process = await create_process(*args, **kwargs)
        terminate = process.terminate

        def closed_then_terminate() -> None:
            # The real channel is closed before the signal is attempted.
            process.close()
            signalled.append(True)
            if refusal is not None:
                raise refusal
            terminate()

        process.terminate = closed_then_terminate
        return process

    client._client.create_process = closing_process
    started = time.monotonic()
    try:
        with pytest.raises(installer.C300XDeviceInstallError) as result:
            installer._apply_qml_patch_sync(client, str(tmp_path), "core-apply")
        assert signalled == [True]
        assert result.value.reason == "device_display_timeout"
        assert time.monotonic() - started < grace
        client._client.create_process = create_process
        assert client.run("true") == ""
    finally:
        client.close()


def test_upload_hash_skip_mode_repair_and_replace(ssh_server, tmp_path: Path):
    source = tmp_path / "source"
    destination = tmp_path / "target with spaces"
    source.write_bytes(b"first\x00payload")
    client = installer._connect_device_client(ssh_server)
    try:
        assert client.put_file(source, str(destination), "600")
        assert destination.read_bytes() == source.read_bytes()
        assert destination.stat().st_mode & 0o777 == 0o600
        assert not client.put_file(source, str(destination), "600")
        assert client.put_file(source, str(destination), "700")
        assert destination.stat().st_mode & 0o777 == 0o700
        source.write_bytes(b"replacement")
        assert client.put_file(source, str(destination), "600")
        assert destination.read_bytes() == b"replacement"
        assert not destination.with_name(destination.name + ".new").exists()
    finally:
        client.close()
