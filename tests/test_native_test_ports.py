"""Native test listener ports must stay free until the agent binds them."""

import collections
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from native_agent.test import smoke

ROOT = Path(__file__).resolve().parents[1]


def ephemeral_range():
    low, high = Path("/proc/sys/net/ipv4/ip_local_port_range").read_text().split()
    return range(int(low), int(high) + 1)


@pytest.fixture
def held(monkeypatch):
    """Isolate the reservations of one test from the rest of the process."""
    reservations = collections.deque()
    monkeypatch.setattr(smoke, "_held_test_ports", reservations, raising=False)
    monkeypatch.setattr(smoke, "_test_port_cursor", {}, raising=False)
    yield reservations
    while reservations:
        os.close(reservations.popleft()[1])


@pytest.fixture
def private(held, monkeypatch, tmp_path):
    """Ports and locks that neither the kernel nor other test workers use."""
    start = ephemeral_range().stop
    if start + 4 > 65536 or smoke.listener_port_range().start >= start:
        pytest.skip("no ports above the ephemeral range outside the test port range")
    candidates = range(start, start + 4)
    monkeypatch.setattr(smoke, "_test_port_lock_dir", lambda: tmp_path)
    return candidates


@pytest.mark.parametrize("count", [1, 2, 3])
def test_ports_are_distinct_and_never_from_the_kernel_ephemeral_range(held, count):
    ports = (*smoke.free_tcp_ports(count), smoke.free_udp_port())
    # Any client connection on the host may take an ephemeral port before the agent binds it.
    assert not set(ports) & set(ephemeral_range())
    assert len(set(ports)) == count + 1
    assert set(ports) <= set(smoke.listener_port_range())
    assert {port for port, _fd in held} == set(ports)


def test_a_bound_port_is_skipped(private):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", private[0]))
        occupied.listen()
        smoke._test_port_cursor[f"{private.start}-{private.stop}"] = 0
        assert smoke.reserve_test_ports(3, candidates=private) == tuple(private[1:])


def test_a_port_another_test_process_holds_is_skipped(private, held, tmp_path):
    """Another xdist worker's reservation must not be handed out again."""
    pair = range(private.start, private.start + 2)
    code = (
        "import pathlib, sys\n"
        "from native_agent.test import smoke\n"
        f"smoke._test_port_lock_dir = lambda: pathlib.Path({str(tmp_path)!r})\n"
        f"smoke._test_port_cursor['{pair.start}-{pair.stop}'] = 0\n"
        f"print(smoke.reserve_test_ports(1, candidates=range({pair.start}, {pair.stop}))[0], flush=True)\n"
        "sys.stdin.read()\n"
    )
    with subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as other:
        try:
            assert int(other.stdout.readline()) == pair[0]
            smoke._test_port_cursor[f"{pair.start}-{pair.stop}"] = 0
            assert smoke.reserve_test_ports(1, candidates=pair) == (pair[1],)
            with pytest.raises(RuntimeError, match="no 1 free test ports"):
                smoke.reserve_test_ports(1, candidates=pair)
        finally:
            other.stdin.close()
    # A reservation ends with the process that held it.
    while held:
        os.close(held.popleft()[1])
    assert sorted(smoke.reserve_test_ports(2, candidates=pair)) == list(pair)


def test_old_reservations_are_released_and_probes_are_closed(private, held, monkeypatch):
    monkeypatch.setattr(smoke, "TEST_PORTS_HELD", 2)
    probes = []
    original_socket = socket.socket

    class TrackedSocket(original_socket):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            probes.append(self)

    monkeypatch.setattr(smoke.socket, "socket", TrackedSocket)
    first = smoke.reserve_test_ports(2, candidates=private)
    second = smoke.reserve_test_ports(2, candidates=private)
    assert not set(first) & set(second)
    assert [port for port, _fd in held] == list(second)
    # The released ports can be reserved again, the held ones cannot.
    assert set(smoke.reserve_test_ports(2, candidates=private)) == set(first)
    assert probes and all(probe.fileno() == -1 for probe in probes)


@pytest.mark.parametrize("count", [0, -1])
def test_empty_or_negative_port_group_is_rejected(count):
    with pytest.raises(ValueError, match="At least one port"):
        smoke.free_tcp_ports(count)
