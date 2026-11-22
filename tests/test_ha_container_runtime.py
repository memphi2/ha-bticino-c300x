"""The official HA image is a required, version-matched runtime gate."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ha_container_runtime", ROOT / "scripts/check_ha_container_runtime.py"
)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


@pytest.mark.parametrize("workflow", ["validate.yml"])
def test_container_gate_uses_same_resolved_ha_version_and_cannot_skip(workflow):
    config = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    job = config["jobs"]["validate"]
    assert {item["name"] for item in job["strategy"]["matrix"]["include"]} == {
        "min-ha", "current-ha"
    }
    step = next(s for s in job["steps"] if s.get("name") == "Home Assistant container runtime")
    assert step["env"]["HA_VERSION"] == "${{ steps.ha-version.outputs.version }}"
    assert "ghcr.io/home-assistant/home-assistant:$HA_VERSION" in step["run"]
    assert '--expect-ha "$HA_VERSION"' in step["run"]
    assert "--network none --read-only" in step["run"]
    assert "--entrypoint python" in step["run"]
    assert "if" not in step
    assert not step.get("continue-on-error")


def test_container_gate_rejects_wrong_ha_version_before_running_tools(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["runtime", "--expect-ha", "0.0.0"])
    with pytest.raises(RuntimeError, match="Expected HA 0.0.0"):
        runtime.main()


def test_container_gate_preserves_and_translates_real_ha_event_attributes(capsys):
    runtime.check_events()
    output = capsys.readouterr().out
    for language in ("en", "de", "fr", "it"):
        for cls, key in (
            ("C300XDoorbellEventEntity", "ring"),
            ("C300XDeviceAgentEventEntity", "door_unlock_started"),
            ("C300XDeviceAgentEventEntity", "display_touch_tone_changed"),
        ):
            assert f"{language}/{cls}: event_type={key}, label=" in output


@pytest.mark.parametrize("entity_key", ["doorbell_event", "agent_event"])
def test_container_gate_rejects_old_event_translation_layout(tmp_path, monkeypatch, entity_key):
    translations = tmp_path / "custom_components" / "bticino_c300x" / "translations"
    translations.mkdir(parents=True)
    for source in (ROOT / "custom_components" / "bticino_c300x" / "translations").glob("*.json"):
        catalog = json.loads(source.read_text())
        event = catalog["entity"]["event"][entity_key]
        event["state"] = event.pop("state_attributes")["event_type"]["state"]
        (translations / source.name).write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="event type .* not translated"):
        runtime.check_events()


def test_container_gate_does_not_hide_native_tool_errors(monkeypatch):
    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(runtime.subprocess, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        runtime.run("ffmpeg", "-version")
