"""Which station an installer's SSH session reached, read without the agent.

An entry is named after its station: the agent derives that name from the
MAC address of a network interface, or from the host name when no interface
has one (native_agent/src/mdns.c, c300x_mdns_device_id). The installer reads
the same facts over SSH, so a reinstall for an entry finds out before any
write whether the address now leads to another station, also when the agent
there is missing or broken.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .const import DOMAIN
from .discovery import discovery_matches_entry

# The installer's refusal of a station that is not the entry's.
WRONG_STATION = "wrong_device"
_PREFIX = "c300x-"
# The agent's name when the station gives it neither a MAC address nor a host name.
_FALLBACK = "c300x-agent"
_MAC_NAME = re.compile(r"^c300x[0-9a-f]{12}$")
# Each interface but the loopback one, then the host name, one line each.
_READ = (
    'for f in /sys/class/net/*/address; do n="${f%/address}"; n="${n##*/}"; '
    '[ "$n" = lo ] && continue; echo "mac $(cat "$f" 2>/dev/null)"; done; '
    'echo "host $(cat /proc/sys/kernel/hostname 2>/dev/null)"'
)


@dataclass(frozen=True, slots=True)
class StationNames:
    """The names the agent can give this station."""

    macs: frozenset[str]
    host: str | None


def _mac_name(raw: str) -> str | None:
    digits = "".join(ch for ch in raw if ch in "0123456789abcdefABCDEF")[:12].lower()
    if len(digits) != 12 or set(digits) == {"0"}:
        return None
    return _PREFIX + digits


def _host_name(raw: str) -> str | None:
    # The agent reads at most 63 bytes and keeps 47 of them.
    clean = "".join("-" if ch == "." or not 32 <= ord(ch) < 127 else ch for ch in raw[:63])[:47]
    return _PREFIX + clean if clean else None


def read_station_names(run: Callable[[str], str]) -> StationNames:
    """The station's own facts, read over SSH; nothing is written."""

    macs: set[str] = set()
    host: str | None = None
    for line in run(_READ).splitlines():
        kind, _, value = line.partition(" ")
        if kind == "mac" and (name := _mac_name(value.strip())):
            macs.add(name)
        elif kind == "host":
            host = _host_name(value.strip())
    return StationNames(frozenset(macs), host)


def station_is_another(entry_unique_id: str | None, names: StationNames) -> bool:
    """True only when the station is proven not to be the entry's.

    An entry without a station name (one set up by address, or under the
    agent's fallback name) proves nothing, nor does a station whose facts
    could not be read: the reinstall then goes ahead.
    """

    expected = str(entry_unique_id or "")
    if (
        not expected
        # Set up by address: the name is the address, not the station.
        or expected == DOMAIN or expected.startswith(f"{DOMAIN}:")
        or discovery_matches_entry(_FALLBACK, expected)
    ):
        return False
    candidates = set(names.macs) | ({names.host} if names.host else set())
    if any(discovery_matches_entry(name, expected) for name in candidates):
        return False
    if _MAC_NAME.match(expected.replace(":", "").replace("-", "").lower()):
        # Named after a MAC address: proven only by the station's own ones.
        return bool(names.macs)
    return names.host is not None
