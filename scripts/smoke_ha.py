#!/usr/bin/env python3
"""Smoke-test the installed integration against a supported HA test host."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DOMAIN = "bticino_c300x"
EXPECTED_HA_VERSION_PREFIXES = tuple(
    prefix.strip()
    for prefix in os.environ.get(
        "HA_EXPECTED_VERSION_PREFIXES",
        "2026.5.,2026.6.",
    ).split(",")
    if prefix.strip()
)
EXPECTED_PYTHON_PREFIXES = tuple(
    prefix.strip()
    for prefix in os.environ.get(
        "HA_EXPECTED_PYTHON_PREFIXES",
        "3.14.",
    ).split(",")
    if prefix.strip()
)
REQUIRED_SERVICES = {
    "activate_doorbell_video",
    "alarm_command",
    "reboot",
    "run_action",
    "stair_light",
    "start_home_call",
    "stop_doorbell_video",
    "stop_home_call",
    "unlock_door",
}
FORBIDDEN_SERVICES = {"start_ssh"}
REQUIRED_ENTITIES = {
    "binary_sensor.bticino_c300x_home_call_active",
    "button.bticino_c300x_reboot",
    "button.bticino_c300x_stop_doorbell_video",
    "camera.bticino_c300x_doorbell_camera",
    "event.bticino_c300x_doorbell_ring_event",
    "sensor.bticino_c300x_device_agent_status",
    "sensor.bticino_c300x_doorbell_state",
    "switch.bticino_c300x_ssh",
}
FORBIDDEN_ENTITIES = {"button.bticino_c300x_start_ssh"}
BAD_STATES = {"disconnected", "unavailable", "unknown"}


def main() -> int:
    base_url = os.environ.get("HA_TEST_URL", "").rstrip("/")
    token = os.environ.get("HA_TEST_ACCESS_TOKEN", "")
    if not base_url or not token:
        sys.stderr.write("FAIL: HA_TEST_URL and HA_TEST_ACCESS_TOKEN are required\n")
        return 2

    client = HaClient(base_url, token)
    failures: list[str] = []

    entry_id = find_config_entry_id(client)
    if not entry_id:
        failures.append("BTicino C300X config entry is missing")
    else:
        failures.extend(check_runtime(client, entry_id))

    failures.extend(check_services(client))
    failures.extend(check_entities(client))

    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1

    sys.stdout.write(
        "HA smoke passed: supported Home Assistant/Python runtime, "
        "BTicino C300X entities/services OK\n"
    )
    return 0


class HaClient:
    """Small stdlib-only HA REST client for CI/local smoke checks."""

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def get_json(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            headers=self._headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"{path} returned HTTP {err.code}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"{path} request failed") from err


def find_config_entry_id(client: HaClient) -> str | None:
    data = client.get_json("/api/config/config_entries/entry")
    entries = data if isinstance(data, list) else data.get("entries", [])
    for entry in entries:
        if isinstance(entry, dict) and entry.get("domain") == DOMAIN:
            entry_id = entry.get("entry_id")
            return str(entry_id) if entry_id else None
    return None


def check_runtime(client: HaClient, entry_id: str) -> list[str]:
    data = client.get_json(f"/api/diagnostics/config_entry/{entry_id}")
    home_assistant = data.get("home_assistant", {})
    version = str(home_assistant.get("version", ""))
    python_version = str(home_assistant.get("python_version", ""))
    failures: list[str] = []
    if not version.startswith(EXPECTED_HA_VERSION_PREFIXES):
        failures.append(
            f"HA version {version or '<missing>'} does not match "
            f"{', '.join(f'{prefix}*' for prefix in EXPECTED_HA_VERSION_PREFIXES)}"
        )
    if not python_version.startswith(EXPECTED_PYTHON_PREFIXES):
        failures.append(
            f"HA Python {python_version or '<missing>'} does not match "
            f"{', '.join(f'{prefix}*' for prefix in EXPECTED_PYTHON_PREFIXES)}"
        )
    return failures


def check_services(client: HaClient) -> list[str]:
    service_payload = client.get_json("/api/services")
    services = {
        item.get("domain"): set((item.get("services") or {}).keys())
        for item in service_payload
        if isinstance(item, dict)
    }
    domain_services = services.get(DOMAIN, set())
    failures: list[str] = []
    missing = sorted(REQUIRED_SERVICES - domain_services)
    if missing:
        failures.append(f"missing BTicino service(s): {', '.join(missing)}")
    forbidden = sorted(FORBIDDEN_SERVICES & domain_services)
    if forbidden:
        failures.append(f"redundant BTicino service(s) still registered: {', '.join(forbidden)}")
    return failures


def check_entities(client: HaClient) -> list[str]:
    states = {
        item.get("entity_id"): item
        for item in client.get_json("/api/states")
        if isinstance(item, dict)
    }
    failures: list[str] = []
    missing = sorted(entity_id for entity_id in REQUIRED_ENTITIES if entity_id not in states)
    if missing:
        failures.append(f"missing BTicino entity/entities: {', '.join(missing)}")
    present_forbidden = sorted(entity_id for entity_id in FORBIDDEN_ENTITIES if entity_id in states)
    if present_forbidden:
        failures.append(
            "redundant BTicino entity/entities still registered: "
            + ", ".join(present_forbidden)
        )
    for entity_id in sorted(REQUIRED_ENTITIES & states.keys()):
        state = str(states[entity_id].get("state", ""))
        if entity_id.startswith("button."):
            continue
        if state in BAD_STATES:
            failures.append(f"{entity_id} is {state}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
