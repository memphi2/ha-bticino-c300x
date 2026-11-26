"""The SSH login of one install: a password, a private key, or both.

The key and its passphrase are used for this one connection only, like the
password: never stored, logged or shown, and never passed in a command.
"""

from __future__ import annotations

import errno
import socket
from collections.abc import Callable
from typing import Any

# The pasted key cannot be read: not a private key, or a wrong passphrase.
INVALID_SSH_KEY = "invalid_ssh_key"
# The login works but has no root rights (a tool's bticino2, uid 1000).
SSH_USER_NOT_ROOT = "ssh_user_not_root"
# Nothing answers on port 22: SSH on the station is off or blocked.
SSH_UNREACHABLE = "ssh_unreachable"
# The station takes keys only (dropbear -s) and no key was given.
SSH_PASSWORD_LOGIN_DISABLED = "ssh_password_login_disabled"
_UNREACHABLE_ERRNOS = frozenset({
    errno.ECONNREFUSED, errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN,
})


def normalized_private_key(text: str) -> str:
    """A pasted key with Unix line ends and one final newline."""

    key = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    return f"{key}\n" if key else ""


def key_login_options(asyncssh: Any, private_key: str, passphrase: str, password: str) -> dict[str, Any]:
    """Connect options of a key login; a typed password stays its fallback.

    Raises ValueError when the key cannot be read. Its message and the
    library's are left out: they can quote the key.
    """

    try:
        key = asyncssh.import_private_key(normalized_private_key(private_key), passphrase or None)
    except Exception:  # noqa: BLE001 - any import failure is an unreadable key
        raise ValueError(INVALID_SSH_KEY) from None
    return {
        "client_keys": [key],
        "public_key_auth": True,
        "password": password or None,
        "password_auth": bool(password),
        "preferred_auth": ["publickey", "password"] if password else ["publickey"],
    }


def logged_in_as_root(run: Callable[[str], str]) -> bool:
    """True when the login's user id is 0, read right after the login."""

    return run("id -u").strip() == "0"


def ssh_unreachable(err: BaseException) -> bool:
    """The connection itself failed: refused, timed out, no route or no such host."""

    if isinstance(err, (ConnectionRefusedError, TimeoutError, socket.gaierror)):
        return True
    return isinstance(err, OSError) and err.errno in _UNREACHABLE_ERRNOS


async def password_login_offered(asyncssh: Any, connect_kwargs: dict[str, Any]) -> bool | None:
    """Ask the station, with the same options, whether it takes passwords at all.

    Runs only after a refused password login. None when it cannot be told.
    """

    probe = getattr(asyncssh, "get_server_auth_methods", None)
    options = getattr(asyncssh, "SSHClientConnectionOptions", None)
    if probe is None or options is None:
        return None
    rest = {key: value for key, value in connect_kwargs.items() if key != "host"}
    try:
        # The probe applies its own algorithm arguments over the options, and
        # its own config argument: left out, it loads the user's ~/.ssh/config
        # (ProxyCommand, ProxyJump) over the options' config=None.
        methods = await probe(
            connect_kwargs["host"], options=options(**rest), kex_algs=rest.get("kex_algs", ()),
            server_host_key_algs=rest.get("server_host_key_algs", ()), config=None,
        )
    except Exception:  # noqa: BLE001 - an unanswered probe tells nothing
        return None
    return "password" in methods
