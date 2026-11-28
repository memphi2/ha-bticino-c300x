"""Offline cross-checks for issue #51 comment 7084550618, not hardware tests."""

import hashlib
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relative,digest", [
    ("home/bticino/bin/bt_answering_machine", "cc53dd834361e8a76268b108ce2562b8447d597798dd2f136ce4707142485e12"),
    ("home/bticino/bin/bt_av_media", "5464f8636b9dfc4d0603034c1e7f117b02c86733c77e94bf7b7f4fc0b48a1bb2"),
    ("lib/libc-2.27.so", "c3cfae14cc52a2bbf62cfc62797da688908dbca60ab9c18202cd9c082b7b4480"),
])
def test_reported_binary_hash_matches_original_firmware(relative, digest):
    original("c100x-1.5.8")
    path = FIRMWARE_ROOT / "rootfs-c100x-1.5.8" / relative
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_framebuffer_virtual_size_is_not_the_logical_page_size():
    original("c100x-1.5.8")
    firmware = FIRMWARE_ROOT / "rootfs-c100x-1.5.8"
    main = (firmware / "home/bticino/bin/gui/skins/default/main.qml").read_text()
    wrapper = (firmware / "home/bticino/bin/BtClass100_qws").read_text()
    assert "width: 800" in main and "height: 480" in main
    assert "QT_QPA_EGLFS_FB=/dev/fb1" in wrapper
    assert "FB_MULTI_BUFFER=3" in wrapper
    # A command-v failure with an unknown shell PATH is not proof of absence.
    assert (firmware / "sbin/start-stop-daemon").readlink() == Path("/bin/busybox.nosuid")
    assert (firmware / "usr/sbin/start-stop-daemon").is_file()


def test_reported_ringer_values_and_companion_route_preservation(tmp_path):
    binary = tmp_path / "field-report"
    subprocess.run([
        "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE",
        "-D_POSIX_C_SOURCE=200809L", "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
        str(ROOT / "tests/fixtures/c100x_field_report.c"),
        str(ROOT / "native_agent/src/ringer_protocol.c"),
        str(ROOT / "native_agent/src/string_util.c"), "-o", str(binary),
    ], check=True, capture_output=True, text=True, timeout=30)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)


def test_original_vendor_provisioning_exists_independently_of_companion():
    original("c100x-1.5.8")
    firmware = FIRMWARE_ROOT / "rootfs-c100x-1.5.8"
    assert (firmware / "etc/flexisip").readlink() == Path("/home/bticino/cfg/extra/90/flexisip")
    config = (firmware / "home/bticino/cfg/flexisip.conf").read_text()
    assert "datasource=/etc/flexisip/users/users.db.txt" in config
    assert "static-records-file=/etc/flexisip/users/route.conf" in config
    cloud = (firmware / "home/bticino/bin/bt_eliot").read_bytes()
    for marker in (b"sipAccounts", b"START ask sip users", b"Sip user result: %s (%d)", b"/var/tmp/user_list.txt"):
        assert b"\0" + marker + b"\0" in cloud
    # Static handoff markers document the vendor path, not a particular
    # reported account's author or a successful live provisioning session.
    for version, identity in (("c100x-1.5.8", b"c100x"), ("1.7.19", b"c300x")):
        original(version)
        binary = (FIRMWARE_ROOT / ("rootfs-" + version) / "home/bticino/bin/bt_answering_machine").read_bytes()
        for marker in (identity, b"SipUsers", b"Refresh sip user list", b"/var/tmp/user_list.txt",
                       b"/etc/flexisip/users/users.db.txt", b"/etc/flexisip/users/accounts.txt",
                       b"/etc/flexisip/users/route_int.conf", b"/etc/flexisip/users/route_ext.conf"):
            assert b"\0" + marker + b"\0" in binary


def test_own_and_scs_servers_are_in_original_firmware():
    original("c100x-1.5.8")
    firmware = FIRMWARE_ROOT / "rootfs-c100x-1.5.8"
    config = ET.parse(firmware / "home/bticino/cfg/stack_open.xml")
    names = {node.text for node in config.findall(".//bt_daemon/stackopen/*/name")}
    assert {"openserver", "scsserver"} <= names
    assert config.find(".//scsserver/port").text == "20001"
    assert "20000" in {node.text for node in config.findall(".//port_open")}
    for name in ("openserver", "scsserver"):
        assert (firmware / "home/bticino/bin" / name).read_bytes().startswith(b"\x7fELF")
