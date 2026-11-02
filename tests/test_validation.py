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
    assert "--cov=custom_components/bticino_c300x" in command
    assert f"--cov-fail-under={check_coverage.MINIMUM_COVERAGE}" in command
    assert check_coverage.MINIMUM_COVERAGE == 95
    assert ("Python typing ratchet" in steps) is (pytest_result == 0)
    for name in ("Repository checks", "Legal/provenance audit", "Native agent ARMHF stack check", "Quality scale checks", "Ruff"):
        assert name in steps
