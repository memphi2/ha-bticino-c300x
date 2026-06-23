#!/usr/bin/env python3
"""Run the same validation gates as the main CI job."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ValidationStep:
    """One ordered validation command."""

    name: str
    command: tuple[str, ...]
    cwd: Path = ROOT


def main() -> int:
    """Run the full local validation sequence."""

    steps: list[ValidationStep] = [
        ValidationStep("Repository checks", (sys.executable, "scripts/check_repo.py")),
        ValidationStep("Native agent ARMHF stack check", ("make", "-C", "native_agent", "armhf-stack-check")),
    ]

    abi_step = _native_agent_abi_step()
    if abi_step is not None:
        steps.append(abi_step)
    else:
        _write("Skipping ARMHF ABI check: C300X_DEVICE_SYSROOT is not available.")

    steps.extend(
        [
            ValidationStep("Quality scale checks", (sys.executable, "scripts/check_quality_scale.py")),
            ValidationStep("Ruff", (sys.executable, "-m", "ruff", "check", ".")),
            ValidationStep("Python tests", (sys.executable, "-m", "pytest")),
            ValidationStep("Python coverage ratchet", (sys.executable, "scripts/check_coverage.py")),
            ValidationStep("Python typing ratchet", (sys.executable, "scripts/check_typing.py")),
        ]
    )

    for step in steps:
        returncode = _run_step(step)
        if returncode:
            return returncode
    _write("Validation passed")
    return 0


def _native_agent_abi_step() -> ValidationStep | None:
    sysroot = os.environ.get("C300X_DEVICE_SYSROOT", "")
    if not sysroot:
        return None
    if not (Path(sysroot) / "lib").is_dir():
        return None
    return ValidationStep(
        "Native agent ARMHF ABI check",
        ("make", "-C", "native_agent", "armhf-abi-check"),
    )


def _run_step(step: ValidationStep) -> int:
    _write(f"\n==> {step.name}")
    _write(f"$ {_format_command(step.command)}")
    return subprocess.run(step.command, cwd=step.cwd, check=False).returncode


def _format_command(command: Sequence[str]) -> str:
    return " ".join(command)


def _write(message: str) -> None:
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
