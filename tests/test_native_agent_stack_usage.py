from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_stack_usage_module():
    spec = importlib.util.spec_from_file_location(
        "check_stack_usage",
        ROOT / "scripts" / "check_stack_usage.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_stack_usage_parser_accepts_static_gcc_records(tmp_path: Path) -> None:
    module = _load_stack_usage_module()
    stack_file = tmp_path / "http.su"
    stack_file.write_text(
        "src/http.c:123:5:handle_diagnostics_get\t256\tstatic\n",
        encoding="utf-8",
    )

    records = module.collect_stack_usage(tmp_path)

    assert len(records) == 1
    assert records[0].function == "handle_diagnostics_get"
    assert records[0].bytes_used == 256


@pytest.mark.parametrize(
    "line",
    [
        "src/http.c:123:5:bad_vla\t256\tdynamic\n",
        "src/http.c:123:5:bad_alloca\t256\tdynamic,bounded\n",
        "src/http.c:123:5:missing_qualifier\t256\n",
    ],
)
def test_stack_usage_parser_rejects_non_static_records(
    tmp_path: Path,
    line: str,
) -> None:
    module = _load_stack_usage_module()
    stack_file = tmp_path / "http.su"
    stack_file.write_text(line, encoding="utf-8")

    with pytest.raises(ValueError):
        module.collect_stack_usage(tmp_path)


def test_validate_workflow_runs_armhf_stack_check() -> None:
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    validate_script = (ROOT / "scripts" / "check_validate.py").read_text(
        encoding="utf-8"
    )

    assert "gcc-arm-linux-gnueabihf" in workflow
    assert "binutils-arm-linux-gnueabihf" in workflow
    assert "python scripts/check_validate.py" in workflow
    assert '"make", "-C", "native_agent", "armhf-stack-check"' in validate_script
    assert "C300X_DEVICE_SYSROOT" in validate_script
    assert '"make", "-C", "native_agent", "armhf-abi-check"' in validate_script
