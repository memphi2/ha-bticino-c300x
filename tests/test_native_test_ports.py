"""Grouped native test listeners must never select the same ephemeral port."""

import errno
import socket

import pytest

from native_agent.test import smoke


@pytest.mark.parametrize("count", [1, 2, 3])
def test_group_selection_keeps_every_socket_bound_until_all_addresses_are_read(monkeypatch, count):
    sockets = []
    original_socket = socket.socket

    class TrackedSocket(original_socket):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sockets.append(self)

        def getsockname(self):
            assert len(sockets) == count
            assert all(sock.fileno() >= 0 for sock in sockets)
            assert all(original_socket.getsockname(sock)[1] != 0 for sock in sockets)
            return super().getsockname()

    with original_socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        monkeypatch.setattr(smoke.socket, "socket", TrackedSocket)
        ports = smoke.free_tcp_ports(count)
        assert len(set(ports)) == count
        assert occupied.getsockname()[1] not in ports
        assert all(sock.fileno() == -1 for sock in sockets)


def test_failed_group_bind_closes_successful_and_unused_sockets(monkeypatch):
    sockets = []
    original_socket = socket.socket

    class FailingSocket(original_socket):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sockets.append(self)

        def bind(self, address):
            if self is sockets[1]:
                raise OSError(errno.EADDRINUSE, "synthetic second bind failure")
            return super().bind(address)

    monkeypatch.setattr(smoke.socket, "socket", FailingSocket)
    with pytest.raises(OSError, match="synthetic second bind failure"):
        smoke.free_tcp_ports(3)
    assert len(sockets) == 3
    assert all(sock.fileno() == -1 for sock in sockets)


@pytest.mark.parametrize("count", [0, -1])
def test_empty_or_negative_port_group_is_rejected(count):
    with pytest.raises(ValueError, match="At least one port"):
        smoke.free_tcp_ports(count)
