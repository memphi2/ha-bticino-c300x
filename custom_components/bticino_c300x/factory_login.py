"""The C300X factory root login, tried before anybody is asked for one.

The login is the same on every C300X and is no secret. It is kept encoded only
so that it is not plain text in the code; anyone can decode it.
"""

from __future__ import annotations

import base64

_KEY = b"c300x-factory"
_USERNAME = "EVxfRA=="
_PASSWORD = "IAAAACBPEggAHQEd"

# Why an install with the factory login failed: the device refused it.
LOGIN_REFUSED = "ssh_login_refused"


def _decode(value: str) -> str:
    data = base64.b64decode(value)
    return bytes(byte ^ _KEY[index % len(_KEY)] for index, byte in enumerate(data)).decode()


def factory_ssh_login() -> tuple[str, str]:
    """User name and password of the C300X factory root login."""

    return _decode(_USERNAME), _decode(_PASSWORD)


def ssh_login(user_input: dict[str, object] | None, username_key: str, password_key: str) -> tuple[str, str]:
    """The login typed into the form, or the factory login where none was typed."""

    username = str((user_input or {}).get(username_key, "") or "").strip()
    password = str((user_input or {}).get(password_key, "") or "")
    if not username and not password:
        return factory_ssh_login()
    return username, password
