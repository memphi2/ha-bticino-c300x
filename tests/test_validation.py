"""Keep the local validation gate complete without repeating the test suite."""

from types import SimpleNamespace

import pytest

from scripts import check_coverage, check_validate


@pytest.mark.parametrize("pytest_result", [0, 1, 2])
def test_validation_runs_pytest_once_with_coverage(monkeypatch, pytest_result):
    commands = []
    steps = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=pytest_result)

    def run_step(step):
        steps.append(step.name)
        if "scripts/check_coverage.py" in step.command:
            return check_coverage.main()
        if "pytest" in step.command:
            return run(step.command).returncode
        return 0

    monkeypatch.setattr(check_validate, "_native_agent_abi_step", lambda: None)
    monkeypatch.setattr(check_validate, "_run_step", run_step)
    monkeypatch.setattr(check_coverage.subprocess, "run", run)

    assert check_validate.main() == pytest_result
    assert len(commands) == 1
    command = list(commands[0])
    assert command[:3] == [check_validate.sys.executable, "-m", "pytest"]
    assert "--numprocesses=logical" in command
    assert "--dist=worksteal" in command
    assert "--cov=custom_components/bticino_c300x" in command
    assert f"--cov-fail-under={check_coverage.MINIMUM_COVERAGE}" in command
    assert check_coverage.MINIMUM_COVERAGE == 95
    assert ("Python typing ratchet" in steps) is (pytest_result == 0)
    for name in ("TurboJPEG runtime", "Repository checks", "Legal/provenance audit", "Native agent ARMHF stack check", "Quality scale checks", "Ruff"):
        assert name in steps


def test_validation_fails_before_suite_on_missing_turbojpeg(monkeypatch):
    steps = []

    def run_step(step):
        steps.append(step)
        return 1

    monkeypatch.setattr(check_validate, "_run_step", run_step)
    assert check_validate.main() == 1
    assert len(steps) == 1
    assert steps[0].command == (check_validate.sys.executable, "scripts/check_turbojpeg.py")


def test_armhf_checks_compile_on_every_cpu(monkeypatch, tmp_path):
    (tmp_path / "lib").mkdir()
    monkeypatch.setenv("C300X_DEVICE_SYSROOT", str(tmp_path))
    steps = []

    def run_step(step):
        steps.append(step)
        return 0

    monkeypatch.setattr(check_validate, "_run_step", run_step)
    monkeypatch.setattr(check_coverage, "main", lambda: 0)
    assert check_validate.main() == 0
    make = [step.command for step in steps if step.command[0] == "make"]
    jobs = f"-j{check_validate.os.cpu_count() or 1}"
    assert jobs == check_validate.MAKE_JOBS
    assert make == [
        ("make", "-C", "native_agent", "armhf-stack-check", jobs),
        ("make", "-C", "native_agent", "armhf-abi-check", jobs),
    ]
