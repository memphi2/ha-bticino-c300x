from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize(
    ("case", "user_reason", "overall_ok"),
    [
        ("no_device_user", "homeassistant_user_ok", True),
        ("with_device_user", "homeassistant_user_ok", True),
        ("missing_ha_user", "homeassistant_user_missing", False),
        ("missing_domain", "media_identity_missing", False),
        ("bad_internal_route", "homeassistant_routes_inconsistent", False),
        ("ha_in_external_route", "homeassistant_routes_inconsistent", False),
        ("missing_account", "homeassistant_routes_inconsistent", False),
        ("missing_routing_patch", "homeassistant_user_ok", False),
        ("unreadable_users", "device_user_status_unavailable", False),
    ],
)
def test_native_self_test_evaluates_media_setup_not_literal_device_user(
    tmp_path: Path, case: str, user_reason: str, overall_ok: bool
) -> None:
    paths = {
        "FLEXISIP_CONFIG_FILE": tmp_path / "flexisip.conf",
        "FLEXISIP_DOMAIN_FILE": tmp_path / "domain-registration.conf",
        "FLEXISIP_USERS_DIR": tmp_path,
        "FLEXISIP_USERS_FILE": tmp_path / "users.db.txt",
        "FLEXISIP_ACCOUNTS_FILE": tmp_path / "accounts.txt",
        "FLEXISIP_ROUTE_INT_FILE": tmp_path / "route_int.conf",
        "FLEXISIP_ROUTE_EXT_FILE": tmp_path / "route_ext.conf",
        "FLEXISIP_ROUTE_ACTIVE_FILE": tmp_path / "route.conf",
    }
    domain = "device.example"
    ha_user = f"homeassistant-local@{domain}"
    users = f"version:1\napp-local@{domain} md5:fixture\n{ha_user} md5:fixture\n"
    if case == "with_device_user":
        users += f"c300x@{domain} md5:fixture\n"
    elif case == "missing_ha_user":
        users = f"version:1\napp-local@{domain} md5:fixture\n"
    elif case == "missing_domain":
        users = "version:1\n"
    paths["FLEXISIP_USERS_FILE"].write_text(users, encoding="utf-8")
    if case == "unreadable_users":
        paths["FLEXISIP_USERS_FILE"].unlink()
        paths["FLEXISIP_USERS_FILE"].mkdir()
    paths["FLEXISIP_CONFIG_FILE"].write_text("", encoding="utf-8")
    paths["FLEXISIP_DOMAIN_FILE"].write_text("", encoding="utf-8")
    paths["FLEXISIP_ACCOUNTS_FILE"].write_text(
        "" if case == "missing_account" else "Home Assistant|homeassistant\n", encoding="utf-8"
    )
    route = f"<sip:alluser@{domain}> <sip:{ha_user}>\n"
    paths["FLEXISIP_ROUTE_INT_FILE"].write_text(
        "" if case == "bad_internal_route" else route, encoding="utf-8"
    )
    paths["FLEXISIP_ROUTE_EXT_FILE"].write_text(
        route if case == "ha_in_external_route" else "", encoding="utf-8"
    )
    paths["FLEXISIP_ROUTE_ACTIVE_FILE"].symlink_to(paths["FLEXISIP_ROUTE_INT_FILE"])
    firewall = tmp_path / "firewall.conf"
    firewall.write_text(
        "# c300x-native-agent firewall begin\n# c300x-native-agent firewall end\n",
        encoding="utf-8",
    )
    binary = tmp_path / "self-test-user"
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            *(f"-D{name}={json.dumps(str(path))}" for name, path in paths.items()),
            str(NATIVE / "test/self_test_user_test.c"),
            str(NATIVE / "src/self_test.c"),
            str(NATIVE / "src/device_user.c"),
            str(NATIVE / "src/string_util.c"),
            "-o", str(binary),
        ], check=True, capture_output=True, text=True,
    )
    originals = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (*paths.values(), firewall) if path.is_file()
    }

    result = subprocess.run(
        [str(binary), str(firewall), "0" if case == "missing_routing_patch" else "1"],
        check=True, capture_output=True, text=True,
    )

    payload = json.loads(result.stdout)
    status = payload["self_test"]
    user = status["checks"]["homeassistant_user"]
    assert user["reason"] == user_reason
    assert user["ok"] is (user_reason == "homeassistant_user_ok")
    assert user["device_user_present"] is (case == "with_device_user")
    assert status["ok"] is overall_ok
    if overall_ok:
        assert payload["identity_available"] is True
    if case == "missing_routing_patch":
        assert status["checks"]["device_routing"]["reason"] == "device_routing_missing"
    for path, original in originals.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original
