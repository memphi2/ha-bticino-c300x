"""Exercise the production bootstrap client against a local legacy SSH server."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from pathlib import Path

import asyncssh
import pytest

from custom_components.bticino_c300x import device_installer as installer


@pytest.fixture(params=["diffie-hellman-group14-sha1", "diffie-hellman-group1-sha1"])
def ssh_server(monkeypatch, request):
    ready = concurrent.futures.Future()
    failures = []
    state = {}

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return True

        def password_auth_supported(self):
            return True

        def validate_password(self, username, password):
            return username == "test-user" and password == "test-password"

    async def process_handler(process):
        assert process.term_type is None
        if process.command == "hang":
            await process.stdin.read()
            await state["stop"].wait()
            return
        child = await asyncio.create_subprocess_shell(
            process.command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
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
            server_host_keys=[asyncssh.generate_private_key("ssh-rsa", key_size=2048)],
            signature_algs=["ssh-rsa"], kex_algs=[request.param],
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

    with pytest.raises(installer.C300XDeviceInstallError, match="device_install_failed"):
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
