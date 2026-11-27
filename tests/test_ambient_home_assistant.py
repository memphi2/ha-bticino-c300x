"""A Home Assistant object left by one test must not reach the next."""

import os
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent

# Two tests in order on one thread, as pytest-xdist may hand them to a worker:
# the first leaves a Home Assistant whose loop ended during an integration
# load, the second builds a flow form that looks up the current Home Assistant
# for its translations.
MODULE = '''
import asyncio

from homeassistant import loader
from homeassistant.core import HomeAssistant

from custom_components.bticino_c300x.config_flow_forms import async_display_patch_status_text


def test_leaves_a_home_assistant_behind(tmp_path):
    async def make():
        hass = HomeAssistant(str(tmp_path))
        loader.async_setup(hass)
        hass.data[loader.DATA_INTEGRATIONS]["bticino_c300x"] = asyncio.get_running_loop().create_future()

    asyncio.run(make())


def test_a_later_form_text_does_not_wait_for_it():
    async def text():
        return await asyncio.wait_for(async_display_patch_status_text("unknown"), 20)

    assert asyncio.run(text())
'''


def test_a_home_assistant_of_an_earlier_test_does_not_block_a_later_one(tmp_path):
    (tmp_path / "test_order.py").write_text(MODULE)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(TESTS), str(TESTS.parent)])}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:xdist", "-p", "no:cacheprovider",
         "-p", "no:randomly", "--rootdir", str(tmp_path), "-c", os.devnull,
         f"--basetemp={tmp_path / 'run'}", str(tmp_path / "test_order.py")],
        capture_output=True, text=True, timeout=300, env=env, cwd=tmp_path, check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert "2 passed" in result.stdout, result.stdout[-3000:]
