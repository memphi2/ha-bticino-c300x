"""Bounded factory-login selection; explicit credentials always take priority.

Factory credentials may have been changed. Encoding is not secret storage.
The C100X credential was supplied by the user and verified offline against
the root hash of original firmware 1.5.8, not by contacting a device.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_BOOTSTRAP_SSH_KEY,
    CONF_BOOTSTRAP_SSH_KEY_PASSPHRASE,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
)

_KEY = b"c300x-factory"
_USERNAME = "EVxfRA=="
_PASSWORD = "IAAAACBPEggAHQEd"
_C100X_PASSWORD = "IAIAACBPEggAHQEd"

# Why an install with the factory login failed: the device refused it.
LOGIN_REFUSED = "ssh_login_refused"


def _decode(value: str) -> str:
    data = base64.b64decode(value)
    return bytes(byte ^ _KEY[index % len(_KEY)] for index, byte in enumerate(data)).decode()


def factory_ssh_login(model: str = "") -> tuple[str, str]:
    """Select only a known model; keep the existing C300X default unchanged."""

    if model.upper() == "C100X":
        return _decode(_USERNAME), _decode(_C100X_PASSWORD)
    return _decode(_USERNAME), _decode(_PASSWORD)


def factory_login_candidates(model: str = "") -> tuple[tuple[str, str], ...]:
    """An unknown bootstrap model permits at most two distinct credentials."""
    if model.upper() in {"C100X", "C300X"}:
        return (factory_ssh_login(model),)
    return factory_ssh_login(), factory_ssh_login("C100X")


def login_model(agent_info: object) -> str:
    """Use agent-reported model metadata, never a hostname guess."""
    if not isinstance(agent_info, Mapping):
        return ""
    device = agent_info.get("device")
    # Setup data carries the model at the top; a raw capabilities reply under "device".
    model = str((device if isinstance(device, Mapping) else agent_info).get("model") or "").upper()
    return model if model in {"C100X", "C300X"} else ""


def uses_factory_login(user_input: dict[str, object] | None, username_key: str, password_key: str) -> bool:
    values = user_input or {}
    return not str(values.get(username_key, "") or "").strip() and not values.get(password_key)


def ssh_login(user_input: dict[str, object] | None, username_key: str, password_key: str,
              model: str = "") -> tuple[str, str]:
    """The login typed into the form, or the factory login where none was typed."""

    username = str((user_input or {}).get(username_key, "") or "").strip()
    password = str((user_input or {}).get(password_key, "") or "")
    if not username and not password:
        return factory_ssh_login(model)
    return username, password


def install_login(user_input: dict[str, Any] | None, model: str = "") -> dict[str, Any]:
    """The SSH login fields of an install request from a credential form.

    Nothing typed: the factory login. A private key logs in as the typed
    user, else as the factory user, with the typed password as its fallback
    and never with the factory password.
    """

    values = user_input or {}
    keys = (CONF_BOOTSTRAP_SSH_USERNAME, CONF_BOOTSTRAP_SSH_PASSWORD)
    key = str(values.get(CONF_BOOTSTRAP_SSH_KEY, "") or "").strip()
    factory = uses_factory_login(values, *keys)
    username, password = ssh_login(values, *keys, model)
    return {
        "ssh_username": username,
        "ssh_password": "" if key and factory else password,
        "ssh_private_key": key,
        "ssh_key_passphrase": str(values.get(CONF_BOOTSTRAP_SSH_KEY_PASSPHRASE, "") or "") if key else "",
        "factory_login": factory and not key,
        "device_model": model,
    }
