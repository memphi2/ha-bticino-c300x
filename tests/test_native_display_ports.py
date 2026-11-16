"""The native loopback lab must not select ports held by its own services."""

import errno
import json
import socket
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler

import pytest
import test_native_display_roundtrip as native_lab


def assert_bound(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        with pytest.raises(OSError) as caught:
            probe.bind(("127.0.0.1", port))
        assert caught.value.errno == errno.EADDRINUSE


def test_native_ports_are_reserved_together_and_exclude_bound_mocks():
    with native_lab._mock_servers(BaseHTTPRequestHandler) as (own, callback):
        mock_ports = [own.server_address[1], callback.server_address[1]]
        with native_lab._reserved_listener_ports() as native_ports:
            assert len({*mock_ports, *native_ports}) == 4
            for port in (*mock_ports, *native_ports):
                assert_bound(port)
        # Releasing native reservations must not release the mocks.
        for port in native_ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
        for port in mock_ports:
            assert_bound(port)
    assert own.socket.fileno() == callback.socket.fileno() == -1


def test_failed_second_reservation_closes_both_sockets(monkeypatch):
    sockets = []
    original_socket = socket.socket

    class FailingSecondSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sockets.append(self)

        def bind(self, address):
            if len(sockets) == 2 and self is sockets[1]:
                with original_socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    with pytest.raises(OSError) as caught:
                        probe.bind(sockets[0].getsockname())
                    assert caught.value.errno == errno.EADDRINUSE
                raise OSError(errno.EADDRINUSE, "synthetic second bind failure")
            return super().bind(address)

    monkeypatch.setattr(native_lab.socket, "socket", FailingSecondSocket)
    with (
        pytest.raises(OSError, match="synthetic second bind failure"),
        native_lab._reserved_listener_ports(),
    ):
        pytest.fail("The failed reservation must not yield")
    assert len(sockets) == 2
    assert all(sock.fileno() == -1 for sock in sockets)


def test_mock_cleanup_runs_when_lab_setup_fails(monkeypatch):
    threads = []
    original_thread = native_lab.threading.Thread

    def track_thread(*args, **kwargs):
        thread = original_thread(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(native_lab.threading, "Thread", track_thread)
    with (
        pytest.raises(RuntimeError, match="synthetic setup failure"),
        native_lab._mock_servers(BaseHTTPRequestHandler) as (own, callback),
    ):
        raise RuntimeError("synthetic setup failure")
    assert own.socket.fileno() == callback.socket.fileno() == -1
    assert len(threads) == 2
    assert all(not thread.is_alive() for thread in threads)


def test_lab_binds_mocks_before_reservations_and_cleans_up_failed_process_start(monkeypatch, tmp_path):
    servers = []
    reserved_ports = []
    original_mocks = native_lab._mock_servers
    original_reservations = native_lab._reserved_listener_ports

    @contextmanager
    def track_mocks(handler):
        with original_mocks(handler) as mocks:
            servers.extend(mocks)
            yield mocks

    @contextmanager
    def check_reservations():
        assert len(servers) == 2
        with original_reservations() as ports:
            reserved_ports.extend(ports)
            for port in (*ports, *(server.server_address[1] for server in servers)):
                assert_bound(port)
            yield ports

    def fail_start(*args, **kwargs):
        config = json.loads((tmp_path / "config.json").read_text())
        assert reserved_ports == [config["listen"]["apiPort"], config["listen"]["uiPort"]]
        assert len({*reserved_ports, *(server.server_address[1] for server in servers)}) == 4
        for port in reserved_ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
        for server in servers:
            assert_bound(server.server_address[1])
        raise RuntimeError("synthetic process start failure")

    monkeypatch.setattr(native_lab, "_mock_servers", track_mocks)
    monkeypatch.setattr(native_lab, "_reserved_listener_ports", check_reservations)
    monkeypatch.setattr(native_lab.subprocess, "Popen", fail_start)
    fixture = native_lab.lab.__wrapped__(tmp_path / "unused-native-binary", tmp_path, {})
    with pytest.raises(RuntimeError, match="synthetic process start failure"):
        next(fixture)
    assert all(server.socket.fileno() == -1 for server in servers)
