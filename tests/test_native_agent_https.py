"""Exercise the real native TLS transport against a local HTTPS server."""

from __future__ import annotations

import contextlib
import http.server
import os
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory):
    directory = tmp_path_factory.mktemp("callback-tls")
    key = directory / "key.pem"
    ca = directory / "ca.pem"
    _run(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(key),
        "-out",
        str(ca),
        "-days",
        "2",
        "-subj",
        "/CN=Callback test CA",
    )
    for name, hostname, days in (
        ("valid", "localhost", "1"),
        ("wrong", "wrong.invalid", "1"),
        ("expired", "localhost", "-1"),
    ):
        csr = directory / f"{name}.csr"
        ext = directory / f"{name}.ext"
        ext.write_text(f"subjectAltName=DNS:{hostname}\nbasicConstraints=CA:FALSE\n")
        _run(
            "openssl",
            "req",
            "-new",
            "-key",
            str(key),
            "-out",
            str(csr),
            "-subj",
            f"/CN={hostname}",
        )
        if name == "expired":
            (directory / "index").write_text("")
            (directory / "serial").write_text("1000\n")
            config = directory / "ca.cnf"
            config.write_text(
                f"[ca]\ndefault_ca=test\n[test]\ndatabase={directory}/index\n"
                f"serial={directory}/serial\nnew_certs_dir={directory}\n"
                "default_md=sha256\npolicy=policy\n[policy]\ncommonName=supplied\n"
            )
            _run(
                "openssl",
                "ca",
                "-batch",
                "-config",
                str(config),
                "-keyfile",
                str(key),
                "-cert",
                str(ca),
                "-in",
                str(csr),
                "-extfile",
                str(ext),
                "-startdate",
                "20200101000000Z",
                "-enddate",
                "20200102000000Z",
                "-out",
                str(directory / f"{name}.pem"),
            )
        else:
            _run(
                "openssl",
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(ca),
                "-CAkey",
                str(key),
                "-set_serial",
                str(len(name)),
                "-days",
                days,
                "-extfile",
                str(ext),
                "-out",
                str(directory / f"{name}.pem"),
            )
    _run(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(directory / "unknown.key"),
        "-out",
        str(directory / "unknown.pem"),
        "-days",
        "2",
        "-subj",
        "/CN=localhost",
    )
    return directory


def _build(directory: Path, ca: Path, library: str | None = None) -> Path:
    binary = directory / ("missing-client" if library else "https-client")
    command = [
        "cc",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-pthread",
        f'-DC300X_CALLBACK_CA_FILE="{ca}"',
    ]
    if library:
        command.append(f'-DC300X_CURL_LIBRARY="{library}"')
    elif sys.platform == "darwin":
        command.append('-DC300X_CURL_LIBRARY="/usr/lib/libcurl.4.dylib"')
    if sys.platform != "darwin":
        command.append("-ldl")
    command.extend(
        [
            str(ROOT / "native_agent/test/https_client_test.c"),
            str(ROOT / "native_agent/src/https_client.c"),
            "-o",
            str(binary),
        ]
    )
    subprocess.run(command, check=True, capture_output=True, text=True)
    return binary


@pytest.fixture(scope="module")
def client(tls_files):
    return _build(tls_files, tls_files / "ca.pem")


@contextlib.contextmanager
def _server(
    directory: Path, certificate="valid", *, status=200, body=b'{"ok":true}', delay=0
):
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.path,
                    self.headers.get("X-Test-Token"),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            time.sleep(delay)
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Location", "/redirect-target")
                self.end_headers()
                self.wfile.write(body)
            except BrokenPipeError, ConnectionResetError, ssl.SSLError:
                pass

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(
        directory / f"{certificate}.pem",
        directory / ("unknown.key" if certificate == "unknown" else "key.pem"),
    )
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://localhost:{server.server_port}/callback", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _request(client, url, timeout=1500):
    env = {
        **os.environ,
        "https_proxy": "http://127.0.0.1:1",
        "HTTPS_PROXY": "http://127.0.0.1:1",
        "ALL_PROXY": "http://127.0.0.1:1",
        "no_proxy": "",
        "NO_PROXY": "",
    }
    return subprocess.run(
        [str(client), url, str(timeout)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    ).stdout


def test_native_https_delivers_json_without_environment_proxy(client, tls_files):
    with _server(tls_files) as (url, received):
        result = _request(client, url)
    assert "available=1 ok=1 status=200 error=none" in result
    assert '{"ok":true}' in result
    assert received == [("/callback", "test-token", b'{"test":true}')]


@pytest.mark.parametrize("certificate", ["unknown", "wrong", "expired"])
def test_native_https_rejects_invalid_certificates(client, tls_files, certificate):
    with _server(tls_files, certificate) as (url, received):
        result = _request(client, url)
    assert "ok=0" in result
    assert received == []


@pytest.mark.parametrize("status", [302, 401, 500])
def test_native_https_rejects_errors_and_does_not_follow_redirects(
    client, tls_files, status
):
    with _server(tls_files, status=status) as (url, received):
        result = _request(client, url)
    assert f"ok=0 status={status}" in result
    assert len(received) == 1


def test_native_https_bounds_response_size(client, tls_files):
    with _server(tls_files, body=b"x" * 1000) as (url, _):
        result = _request(client, url)
    assert "ok=0" in result


def test_native_https_times_out(client, tls_files):
    with _server(tls_files, delay=1) as (url, _):
        started = time.monotonic()
        result = _request(client, url, timeout=150)
        assert time.monotonic() - started < 0.8
    assert "ok=0" in result


def test_native_https_reports_missing_library(tls_files):
    client = _build(tls_files, tls_files / "ca.pem", "/nonexistent/libcurl.so")
    result = _request(client, "https://localhost:1/callback")
    assert "available=0 ok=0 status=0 error=https_unavailable" in result


def test_native_https_uses_arm_pthread_compatibility(tmp_path):
    obj = tmp_path / "https.o"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-D__arm__",
            "-c",
            str(ROOT / "native_agent/src/https_client.c"),
            "-o",
            str(obj),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["nm", "-u", str(obj)], check=True, capture_output=True, text=True
    )
    symbols = {
        line.split()[-1].lstrip("_")
        for line in result.stdout.splitlines()
        if line.split()
    }
    assert "c300x_pthread_once" in symbols
    assert "pthread_once" not in symbols
