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
        ("c100x_device_user", "homeassistant_user_ok", True),
        ("c300x_user_on_c100x", "homeassistant_user_ok", True),
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
    c100x = case in {"c100x_device_user", "c300x_user_on_c100x"}
    if case in {"with_device_user", "c300x_user_on_c100x"}:
        users += f"c300x@{domain} md5:fixture\n"
    elif case == "c100x_device_user":
        users += f"c100x@{domain} md5:fixture\n"
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
    webserver_db = tmp_path / "dbfiles_ws.xml"
    c100x_display = tmp_path / "BtClass100"
    if c100x:
        c100x_display.write_bytes(b"")
    binary = tmp_path / "self-test-user"
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            *(f"-D{name}={json.dumps(str(path))}" for name, path in paths.items()),
            f"-DC300X_FIRMWARE_INFO_XML={json.dumps(str(webserver_db))}",
            f"-DC300X_C100X_DISPLAY_MARKER={json.dumps(str(c100x_display))}",
            str(NATIVE / "test/self_test_user_test.c"),
            str(NATIVE / "src/self_test.c"),
            str(NATIVE / "src/device_user.c"),
            str(NATIVE / "src/string_util.c"),
            str(NATIVE / "src/device_detect.c"),
            str(NATIVE / "src/file_io.c"),
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
    assert user["device_user_present"] is (case in {"with_device_user", "c100x_device_user"})
    assert status["ok"] is overall_ok
    if overall_ok:
        assert payload["identity_available"] is True
    if case == "missing_routing_patch":
        assert status["checks"]["device_routing"]["reason"] == "device_routing_missing"
    for path, original in originals.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original
    if case == "no_device_user":
        def family(configured: str) -> str:
            answer = subprocess.run(
                [str(binary), str(firewall), "1", configured], check=True, capture_output=True, text=True,
            )
            return json.loads(answer.stdout)["self_test"]["firmware_family"]

        families = {"1.5.8": "1.5.x", "1.7.19": "1.7.x", "2.0.2": "2.0.x", "3.0.6": "3.0.x", "4.0.0": "unknown"}
        for firmware, expected in families.items():
            assert family(firmware) == expected, firmware
        # The installer writes no firmware into the config: the device's own
        # web server database tells it, as for the capabilities.
        assert family("") == "unknown"
        webserver_db.write_text("<x><ver_webserver> 1.5.8 </ver_webserver></x>", encoding="utf-8")
        assert family("") == "1.5.x"
        assert family("3.0.6") == "3.0.x"


def test_native_account_line_is_added_to_a_file_without_a_final_newline(tmp_path: Path) -> None:
    """The line that is added needs the newline that ends the last account too.

    The output buffer was sized for the old content plus the new line, so a
    file whose last line had no newline was refused as too large and the
    Home Assistant account could not be provisioned on that device.
    """

    binary = tmp_path / "device-user-accounts"
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            f"-DFLEXISIP_ACCOUNTS_FILE={json.dumps(str(tmp_path / 'accounts.txt'))}",
            str(NATIVE / "test/device_user_accounts_test.c"),
            str(NATIVE / "src/string_util.c"),
            str(NATIVE / "src/device_detect.c"),
            str(NATIVE / "src/file_io.c"),
            str(NATIVE / "src/sha256.c"),
            "-o", str(binary),
        ], check=True, capture_output=True, text=True,
    )

    result = subprocess.run([str(binary)], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines() == [
        "unterminated:Alice|alice",
        "Bob|bob",
        "Home Assistant|homeassistant",
        "terminated:Alice|alice",
        "Bob|bob",
        "Home Assistant|homeassistant",
        "empty:Home Assistant|homeassistant",
    ]
