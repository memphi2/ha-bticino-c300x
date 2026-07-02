#!/usr/bin/env python3
"""Extract non-secret C300X media fingerprints from local tcpdump PCAPs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

MEDIA_RE = re.compile(r"m=(audio|video)\s+\d+\s+RTP/SAVP\s+([0-9 ]+)")
RTPMAP_RE = re.compile(r"a=rtpmap:(\d+)\s+([^\r\n]+)")
CRYPTO_RE = re.compile(r"a=crypto:\d+\s+([A-Z0-9_]+)\s+inline:[^\r\n]+")
SIP_REQUEST_RE = re.compile(r"\b(INVITE|ACK|BYE|CANCEL|REGISTER)\s+[^\r\n]+SIP/2\.0")
SIP_STATUS_RE = re.compile(r"\bSIP/2\.0\s+([0-9]{3})\b")
RTSP_PATH_RE = re.compile(
    r"\b(?:DESCRIBE|SETUP|PLAY|TEARDOWN|OPTIONS)\s+"
    r"(?:rtsp://[^/\s]+)?(/[A-Za-z0-9._~/-]+)"
)
EVENT_RE = re.compile(
    r'"(?:event|event_type|type)"\s*:\s*"([a-z0-9_]+\.[a-z0-9_]+|doorbell_[a-z0-9_]+)"'
)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _compact_adjacent(items: list[str]) -> list[str]:
    compacted: list[str] = []
    for item in items:
        if not compacted or compacted[-1] != item:
            compacted.append(item)
    return compacted


def _tcpdump_ascii(pcap_path: Path) -> str:
    try:
        result = subprocess.run(
            ["tcpdump", "-tttt", "-nn", "-A", "-s", "0", "-r", str(pcap_path)],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except FileNotFoundError as err:
        raise SystemExit("tcpdump is required to extract C300X PCAP fingerprints") from err
    if result.returncode != 0 and not result.stdout:
        raise SystemExit(result.stderr.strip() or "tcpdump failed")
    return result.stdout


def parse_tcpdump_ascii(text: str, *, mode: str, source: str) -> dict[str, Any]:
    """Return an anonymized media fingerprint from tcpdump ASCII output."""

    medias = _extract_media_sections(text)
    fingerprint: dict[str, Any] = {
        "schema_version": 1,
        "mode": mode,
        "source": source,
        "sip_sequence": _extract_sip_sequence(text),
        "rtsp_paths": _extract_rtsp_paths(text),
        "events": _extract_events(text),
    }
    offer, answer = _offer_answer_from_media(medias)
    if offer:
        fingerprint["offer"] = offer
    if answer:
        fingerprint["answer"] = answer
    return _drop_empty(fingerprint)


def _extract_sip_sequence(text: str) -> list[str]:
    sequence: list[tuple[int, str]] = []
    sequence.extend((match.start(), match.group(1)) for match in SIP_REQUEST_RE.finditer(text))
    sequence.extend((match.start(), match.group(1)) for match in SIP_STATUS_RE.finditer(text))
    return _compact_adjacent([item for _, item in sorted(sequence)])


def _extract_rtsp_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in RTSP_PATH_RE.finditer(text):
        _append_unique(paths, match.group(1))
    return paths


def _extract_events(text: str) -> list[str]:
    events: list[str] = []
    for match in EVENT_RE.finditer(text):
        _append_unique(events, match.group(1))
    return events


def _extract_media_sections(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    matches = list(MEDIA_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        codecs: list[str] = []
        crypto_suites: list[str] = []
        for codec in RTPMAP_RE.finditer(body):
            _append_unique(codecs, codec.group(2).strip())
        for crypto in CRYPTO_RE.finditer(body):
            _append_unique(crypto_suites, crypto.group(1))
        sections.append(
            {
                "kind": match.group(1),
                "role": _media_role(text, match.start()),
                "payloads": match.group(2).split(),
                "codecs": codecs,
                "crypto_suites": crypto_suites,
            }
        )
    return sections


def _media_role(text: str, position: int) -> str | None:
    role: str | None = None
    role_start = -1
    for match in SIP_REQUEST_RE.finditer(text, 0, position):
        if match.start() > role_start:
            role_start = match.start()
            role = "offer" if match.group(1) == "INVITE" else None
    for match in SIP_STATUS_RE.finditer(text, 0, position):
        if match.start() > role_start:
            role_start = match.start()
            role = "answer" if match.group(1) == "200" else None
    return role


def _offer_answer_from_media(
    medias: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    offer: dict[str, Any] = {}
    answer: dict[str, Any] = {}
    if any(media.get("role") is not None for media in medias):
        for media in medias:
            role = media.get("role")
            kind = str(media["kind"])
            if role == "offer" and kind not in offer:
                offer[kind] = {
                    key: value
                    for key, value in media.items()
                    if key not in {"kind", "role"}
                }
            elif role == "answer" and kind not in answer:
                answer[kind] = {
                    key: value
                    for key, value in media.items()
                    if key not in {"kind", "role"}
                }
        return offer, answer

    seen: dict[str, int] = {"audio": 0, "video": 0}
    for media in medias:
        kind = str(media["kind"])
        target = offer if seen[kind] == 0 else answer if seen[kind] == 1 else None
        seen[kind] += 1
        if target is not None:
            target[kind] = {
                key: value
                for key, value in media.items()
                if key not in {"kind", "role"}
            }
    return offer, answer


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, item in value.items()
            if (cleaned := _drop_empty(item)) not in ({}, [], None)
        }
    if isinstance(value, list):
        return [_drop_empty(item) for item in value if _drop_empty(item) not in ({}, [], None)]
    if isinstance(value, str):
        return IP_RE.sub("<ip>", value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("ring_call", "on_demand", "home_call"))
    parser.add_argument("--pcap", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", default="local_capture_fingerprint")
    args = parser.parse_args()

    fingerprint = parse_tcpdump_ascii(
        _tcpdump_ascii(args.pcap),
        mode=args.mode,
        source=args.source,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fingerprint, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
