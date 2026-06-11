from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTTP_C = ROOT / "native_agent" / "src" / "http.c"


def test_native_agent_reads_firmware_from_stock_webserver_db() -> None:
    source = HTTP_C.read_text(encoding="utf-8")

    assert '#define C300X_FIRMWARE_INFO_XML "/home/bticino/sp/dbfiles_ws.xml"' in source
    assert 'const char *open_tag = "<ver_webserver>";' in source
    assert 'const char *close_tag = "</ver_webserver>";' in source
    assert "read_bounded_text_file(C300X_FIRMWARE_INFO_XML" in source


def test_native_agent_uses_configured_firmware_before_stock_fallback() -> None:
    source = HTTP_C.read_text(encoding="utf-8")
    resolver_start = source.index("static void resolve_device_firmware(")
    resolver_end = source.index("static int path_parent_inplace", resolver_start)
    resolver = source[resolver_start:resolver_end]

    configured_index = resolver.index("config->device_firmware[0] != '\\0'")
    fallback_index = resolver.index("read_firmware_from_webserver_db(out, out_len)")

    assert configured_index < fallback_index
    assert "c300x_copy_string(out, out_len, config->device_firmware);" in resolver


def test_capabilities_escapes_resolved_firmware_value() -> None:
    source = HTTP_C.read_text(encoding="utf-8")

    assert "char firmware_value[C300X_MAX_VERSION_LEN];" in source
    assert "resolve_device_firmware(config, firmware_value, sizeof(firmware_value));" in source
    assert "json_escape_string(firmware_value, device_firmware, sizeof(device_firmware));" in source
