"""Keep shared HA validation aliases and exception types stable across tests."""

import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import homeassistant.components.camera  # noqa: F401
import homeassistant.const  # noqa: F401
import homeassistant.exceptions  # noqa: F401
import homeassistant.helpers.aiohttp_client  # noqa: F401
import homeassistant.helpers.selector  # noqa: F401
import pytest


def _curl_include_dir() -> str | None:
    """Resolve the libcurl headers exactly as native_agent/Makefile does."""

    configured = os.environ.get("CURL_INCLUDE_DIR", "").strip()
    if configured:
        return configured
    pkg_config = shutil.which("pkg-config")
    if pkg_config is None:
        return None
    result = subprocess.run(
        [pkg_config, "--variable=includedir", "libcurl"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def _compiler_finds_curl_header() -> bool:
    """Report whether the compiler already resolves curl/curl.h on its own."""

    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        return False
    probe = subprocess.run(
        [compiler, "-fsyntax-only", "-xc", "-"],
        input="#include <curl/curl.h>\n",
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


def _export_curl_include_path() -> None:
    """Let the in-test C compiles find curl/curl.h without a system dev package.

    native_agent/Makefile resolves the directory from CURL_INCLUDE_DIR, falling
    back to pkg-config, but the tests that compile https_client.c assemble their
    own command lines and would miss it. CPATH reaches every one of them,
    present and future, without repeating include flags at each call site.

    The Makefile applies the directory with -idirafter, so it only ever acts as
    a fallback behind the system include path. CPATH instead behaves like -I and
    would take precedence, which would let the suite validate a different curl
    ABI than the shipped build compiles against. The probe below keeps the two
    paths equivalent: when the compiler already finds the header, nothing is
    exported and the system headers win here too.
    """

    if _compiler_finds_curl_header():
        return
    directory = _curl_include_dir()
    if directory is None:
        return
    if not os.path.exists(os.path.join(directory, "curl", "curl.h")):
        # pkg-config answers from libcurl.pc, which can outlive the headers. A
        # stale answer is usually a plain system directory, and putting one of
        # those on CPATH makes GCC warn that it is changing the search order for
        # a system directory and drop it from the system chain - which under the
        # tests' -Werror would fail every native compile far from the cause.
        return
    parts = [part for part in os.environ.get("CPATH", "").split(os.pathsep) if part]
    if directory not in parts:
        os.environ["CPATH"] = os.pathsep.join([*parts, directory])


_export_curl_include_path()

_HA_EXCEPTIONS = homeassistant.exceptions
_ERROR_TYPES = (
    _HA_EXCEPTIONS.HomeAssistantError,
    _HA_EXCEPTIONS.ServiceValidationError,
)


@pytest.fixture
def entity_ha_boundary(monkeypatch):
    """Replace only HA I/O for entity unit tests, never HA modules or classes."""
    from homeassistant.helpers import dispatcher, entity_registry, event, issue_registry

    from custom_components.bticino_c300x.entity import C300XEntity

    monkeypatch.setattr(C300XEntity, "async_write_ha_state", lambda self: setattr(self, "wrote_state", True))
    monkeypatch.setattr(C300XEntity, "async_on_remove", lambda self, cancel: setattr(self, "_remove_callback", cancel))
    monkeypatch.setattr(dispatcher, "async_dispatcher_connect", lambda *_: lambda: None)
    monkeypatch.setattr(dispatcher, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(event, "async_call_later", lambda *_: lambda: None)
    monkeypatch.setattr(issue_registry, "async_create_issue", lambda *args, **kwargs: None)
    monkeypatch.setattr(issue_registry, "async_delete_issue", lambda *args, **kwargs: None)
    monkeypatch.setattr(entity_registry, "async_get", lambda _: SimpleNamespace(async_get=lambda _: None))
    for name in (
        "entity", "binary_sensor", "button", "number", "select", "sensor",
        "switch", "services", "agent_diagnostics", "use_cases.common",
    ):
        module = sys.modules.get(f"custom_components.bticino_c300x.{name}")
        if module is None:
            continue
        for attr, replacement in (
            ("async_dispatcher_connect", lambda *_: lambda: None),
            ("async_dispatcher_send", lambda *_: None),
            ("async_call_later", lambda *_: lambda: None),
        ):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, replacement)


@pytest.fixture(autouse=True)
def stable_home_assistant_exceptions():
    """Legacy entity stubs must not replace shared exception classes."""
    _check_exception_types()
    yield
    _check_exception_types()


def _check_exception_types():
    assert sys.modules["homeassistant.exceptions"] is _HA_EXCEPTIONS
    assert (
        _HA_EXCEPTIONS.HomeAssistantError,
        _HA_EXCEPTIONS.ServiceValidationError,
    ) == _ERROR_TYPES
