from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_hacs_release.py"


def _load_release_builder():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("build_hacs_release", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_hacs_release_zip_uses_component_root_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builder = _load_release_builder()
    package_root = tmp_path / "package"
    output = tmp_path / "ha-bticino-c300x.zip"

    def stage_bundle_stub(component_dir: Path, *, version: str, skip_build: bool) -> None:
        assert version == "0.2.0"
        assert skip_build is True
        bundle = component_dir / "device_agent" / "bundle.json"
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(builder, "PACKAGE_ROOT", package_root)
    monkeypatch.setattr(builder, "stage_bundle", stage_bundle_stub)

    builder._prepare_package("0.2.0")
    builder._write_zip(output)

    assert (package_root / "manifest.json").exists()
    assert not (package_root / "custom_components").exists()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())

    assert "manifest.json" in names
    assert "__init__.py" in names
    assert "device_agent/bundle.json" in names
    assert not any(name.startswith("custom_components/") for name in names)
