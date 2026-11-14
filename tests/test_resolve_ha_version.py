"""CI must test newest stable HA, never a compatible older or preview release."""

import sys
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_ha_version as resolver  # noqa: E402


def test_latest_stable_excludes_previews_yanked_and_empty_releases():
    data = {"releases": {
        "2026.10.0": [{"yanked": False}],
        "2026.11.1": [{"yanked": False}],
        "2026.11.2": [{"yanked": True}],
        "2026.12.0b1": [{"yanked": False}],
        "2026.12.0": [],
    }}
    assert resolver.latest_stable(data, "2026.10.0") == "2026.11.1"


def test_latest_stable_orders_numeric_versions():
    data = {"releases": {version: [{}] for version in ("2026.9.4", "2026.10.0", "2026.11.10", "2026.11.9")}}
    assert resolver.latest_stable(data, "2026.10.0") == "2026.11.10"


def test_latest_stable_fails_without_eligible_release():
    with pytest.raises(ValueError, match="no supported"):
        resolver.latest_stable({"releases": {"2026.9.4": [{}]}}, "2026.10.0")


@pytest.mark.parametrize("version", ["2026.11.0b1", "2026.11.0rc1", "2026.13.0", "2026.11.1\nx=y", "latest"])
def test_output_version_rejects_unstable_and_unsafe_values(version):
    with pytest.raises(ValueError):
        resolver.stable_version(version)


def test_minimum_resolution_is_offline_and_does_not_set_current_output(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["resolve", "min-ha"])
    monkeypatch.setattr(resolver, "urlopen", lambda *_args, **_kwargs: pytest.fail("minimum must not use network"))
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert resolver.main() == 0
    assert output.read_text() == "version=2026.10.0\n"


def test_current_resolution_exports_exact_release_version(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["resolve", "current-ha"])
    def fetch(url, *, timeout):
        assert url == resolver.PYPI_URL
        assert timeout == 30
        return BytesIO(b'{"releases": {"2026.12.2": [{"yanked": false}]}}')
    monkeypatch.setattr(resolver, "urlopen", fetch)
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert resolver.main() == 0
    assert output.read_text() == "version=2026.12.2\ncurrent_ha=2026.12.2\n"
