"""Check original QtQuick module boundaries which layout mocks cannot prove."""

import os
import re
from pathlib import Path

import pytest

QML = Path(__file__).resolve().parents[1] / "device_qml"


def _missing_imports(source, module, types):
    if re.search(rf"(?m)^import {re.escape(module)} 1\.0\s*$", source):
        return []
    return [name for name in types if re.search(rf"\b{re.escape(name)}\s*\{{", source)]


def test_import_contract_rejects_components_without_styles():
    source = "import QtQuick 1.1\nimport Components 1.0\nUbuntuLightText {}\n"
    assert _missing_imports(source, "Components.Styles", ["UbuntuLightText"]) == ["UbuntuLightText"]
    assert not _missing_imports("import Components.Styles 1.0\n" + source,
                                "Components.Styles", ["UbuntuLightText"])


def test_all_device_text_components_import_their_stock_module():
    for path in QML.glob("*.qml"):
        source = path.read_text()
        assert not _missing_imports(source, "Components.Styles", ["UbuntuLightText", "UbuntuLightTextInput"]), path.name


def test_private_firmware_component_exports_match_device_imports():
    sysroot = os.environ.get("C300X_DEVICE_SYSROOT")
    if not sysroot:
        pytest.skip("Private C300X firmware sysroot not configured")
    skin = Path(sysroot) / "home/bticino/bin/gui/skins/default"
    for module in ("Components", "Components.Styles"):
        declarations = (skin / module.replace(".", "/") / "qmldir").read_text()
        types = re.findall(r"(?m)^(\w+)\s+1\.0\s+\S+\.qml\s*$", declarations)
        assert types
        for path in QML.glob("*.qml"):
            assert not _missing_imports(path.read_text(), module, types), (path.name, module)
