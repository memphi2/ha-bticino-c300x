"""RTSP host and URL helpers for C300X media paths."""

from __future__ import annotations

from typing import Any


def agent_host_for_socket(host: Any) -> str:
    """Return an agent host in a form accepted by socket APIs."""

    text = str(host or "").strip()
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    return text.replace("%25", "%")


def agent_host_for_url(host: Any) -> str:
    """Return an agent host in a form accepted in RTSP URLs."""

    text = agent_host_for_socket(host)
    if ":" in text and not text.startswith("["):
        text = text.replace("%", "%25")
        return f"[{text}]"
    return text


def normalize_rtsp_path(value: Any, *, default_path: str) -> str:
    """Return an RTSP path with a leading slash."""

    path = str(value or "").strip() or default_path
    return path if path.startswith("/") else f"/{path}"


def build_rtsp_url(
    *,
    host: Any,
    port: int,
    path: Any,
    default_path: str,
    allow_absolute_url: bool = False,
) -> str:
    """Build a C300X RTSP URL from host, port and path values."""

    text_path = str(path or "").strip()
    if allow_absolute_url and text_path.startswith("rtsp://"):
        return text_path
    normalized_path = normalize_rtsp_path(text_path, default_path=default_path)
    return f"rtsp://{agent_host_for_url(host)}:{port}{normalized_path}"
