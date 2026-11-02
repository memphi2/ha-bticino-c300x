#!/usr/bin/env python3
"""Read-only privacy triage; network access requires an explicit CLI opt-in."""

from __future__ import annotations

import argparse
import io
import ipaddress
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile

MAX_INPUT = 16 * 1024 * 1024
MAX_MEMBER = 8 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_TOTAL = 128 * 1024 * 1024
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
COMPRESSED_SIGNATURES = (b"\x1f\x8b", b"\xfd7zXZ\x00", b"7z\xbc\xaf\x27\x1c", b"BZh")
PATTERNS = {
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "github-token": rb"(?:github_pat_[a-zA-Z0-9_]{20,}|gh[pousr]_[a-zA-Z0-9]{30,})",
    "bearer-token": rb"(?i)\bBearer\s+[a-zA-Z0-9._~+/-]{24,}",
    "url-credentials": rb"(?i)https?://[^\s/:]+:[^\s/@]+@",
    "personal-home-path": rb"(?:/(?:home|Users)/|[A-Z]:\\Users\\)[a-zA-Z0-9_.-]+",
}
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        # RFC 1918/link-local ranges, not installation-specific host literals.
        (0x0A000000, 8),
        (0xAC100000, 12),
        (0xC0A80000, 16),
        (0xA9FE0000, 16),
        "fc00::/7",
        "fe80::/10",
    )
)
ADDRESS = re.compile(
    rb"(?<![\w:])(?:\d{1,3}(?:\.\d{1,3}){3}|[fF][cCdDeE][0-9a-fA-F:]*:[0-9a-fA-F:]+)(?![\w:])"
)
SECRET_VALUE = re.compile(
    rb'(?i)["\']?(?:password|api_token|shared_secret|authorization)["\']?\s*[:=]\s*["\']([^"\'\r\n]{8,})["\']'
)


class AuditError(Exception):
    """Fixed, non-sensitive reason for an incomplete audit."""


class SafeRedirect(HTTPRedirectHandler):
    """Allow GitHub asset redirects but never forward API credentials."""

    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if (
            parts.scheme != "https"
            or parts.hostname
            not in {
                "api.github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
        ):
            raise AuditError("unsafe-redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


def scan_text(data: bytes) -> set[str]:
    findings = {name for name, pattern in PATTERNS.items() if re.search(pattern, data)}
    for match in ADDRESS.finditer(data):
        try:
            address = ipaddress.ip_address(match.group().decode("ascii"))
        except ValueError:
            continue
        if any(address in network for network in PRIVATE_NETWORKS):
            findings.add("private-network-address")
    if SECRET_VALUE.search(data):
        findings.add("credential-shaped-value")
    return findings


def scan_zip(data: bytes) -> set[str]:
    """Inspect bounded members in memory; never extract untrusted archives."""
    findings = set()
    if len(data) > MAX_INPUT:
        raise AuditError("input-size-limit")
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if (
                len(members) > MAX_MEMBERS
                or sum(item.file_size for item in members) > MAX_EXPANDED
            ):
                raise AuditError("archive-size-limit")
            for item in members:
                name = item.filename.replace("\\", "/")
                path = PurePosixPath(name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or re.match(r"^[a-zA-Z]:", name)
                    or stat.S_ISLNK(item.external_attr >> 16)
                ):
                    findings.add("unsafe-archive-path")
                if item.is_dir():
                    continue
                if item.flag_bits & 1:
                    raise AuditError("encrypted-archive-member")
                if item.file_size > MAX_MEMBER:
                    raise AuditError("archive-member-size-limit")
                if (
                    path.name == ".env"
                    or ".storage" in path.parts
                    or path.name in {"secrets.yaml", "config.json"}
                ):
                    findings.add("private-config-path")
                if path.suffix.lower() in {
                    ".pcap",
                    ".pcapng",
                    ".har",
                    ".apk",
                    ".fwz",
                    ".img",
                }:
                    findings.add("capture-or-firmware-payload")
                if path.suffix.lower() in {".zip", ".gz", ".xz", ".7z", ".tar", ".tgz"}:
                    raise AuditError("nested-archive-not-inspected")
                findings.update(scan_text(name.encode("utf-8")))
                with archive.open(item) as member:
                    content = member.read(MAX_MEMBER + 1)
                if len(content) > MAX_MEMBER:
                    raise AuditError("archive-member-size-limit")
                if content.startswith(ZIP_SIGNATURES + COMPRESSED_SIGNATURES):
                    raise AuditError("nested-archive-not-inspected")
                findings.update(scan_text(content))
    except (BadZipFile, OSError, RuntimeError, NotImplementedError) as err:
        raise AuditError("invalid-or-unsupported-archive") from err
    return findings


class Audit:
    def __init__(self):
        self.findings = []
        self.errors = []
        self.scanned = 0
        self.bytes_read = 0

    def inspect(self, source: str, data: bytes, *, archive=False):
        self.bytes_read += len(data)
        if len(data) > MAX_INPUT or self.bytes_read > MAX_TOTAL:
            raise AuditError("input-size-limit")
        if data.startswith(COMPRESSED_SIGNATURES) or data[257:262] == b"ustar":
            raise AuditError("unsupported-asset-archive")
        kinds = (
            scan_zip(data)
            if archive or data.startswith(ZIP_SIGNATURES)
            else scan_text(data)
        )
        self.findings.extend({"source": source, "kind": kind} for kind in sorted(kinds))
        self.scanned += 1

    def report(self):
        return {
            "complete": not self.errors,
            "scanned": self.scanned,
            "findings": self.findings,
            "errors": self.errors,
            "scope": "Supplied files, or bounded GitHub release/issue/PR text and release assets",
            "limitations": "Heuristic triage, not secret or legal clearance. No image OCR, linked attachments, Git history or discussions.",
        }


class GitHub:
    def __init__(self, repository: str):
        if not re.fullmatch(
            r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*", repository
        ):
            raise AuditError("invalid-repository")
        self.base = f"https://api.github.com/repos/{repository}"
        self.opener = build_opener(SafeRedirect())
        self.bytes_read = 0
        self.requests = 0

    def get(self, path: str, *, binary=False):
        self.requests += 1
        if self.requests > 100:
            raise AuditError("request-limit")
        headers = {
            "Accept": "application/octet-stream"
            if binary
            else "application/vnd.github+json",
            "User-Agent": "c300x-public-privacy-audit",
        }
        if token := os.environ.get("GH_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        request = Request(self.base + path, headers=headers, method="GET")
        with self.opener.open(request, timeout=15) as response:
            data = response.read(MAX_INPUT + 1)
        self.bytes_read += len(data)
        if len(data) > MAX_INPUT or self.bytes_read > MAX_TOTAL:
            raise AuditError("response-size-limit")
        return data if binary else json.loads(data)

    def items(self, path: str, pages: int):
        for page in range(1, pages + 1):
            separator = "&" if "?" in path else "?"
            items = self.get(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(items, list) or not all(
                isinstance(item, dict) for item in items
            ):
                raise AuditError("unexpected-api-response")
            yield from items
            if len(items) < 100:
                return
        raise AuditError("pagination-limit")


def positive_id(value):
    if type(value) is not int or value < 1:
        raise AuditError("unexpected-api-id")
    return value


def audit_github(audit, github, pages):
    metadata = github.get("")
    if not isinstance(metadata, dict) or metadata.get("private") is not False:
        raise AuditError("repository-not-public")
    # Issues includes PR title/body; these comment endpoints also cover closed PRs.
    for path, label in (
        ("/issues?state=all", "issue-or-pr"),
        ("/issues/comments", "comment"),
        ("/pulls/comments", "review-comment"),
        ("/releases", "release"),
    ):
        for item in github.items(path, pages):
            source = f"{label}:{positive_id(item.get('id'))}"
            audit.inspect(source, json.dumps(item).encode())
            if label == "issue-or-pr" and "pull_request" in item:
                number = positive_id(item.get("number"))
                for review in github.items(f"/pulls/{number}/reviews", pages):
                    audit.inspect(
                        f"review:{positive_id(review.get('id'))}",
                        json.dumps(review).encode(),
                    )
            if label == "release":
                for asset in github.items(
                    f"/releases/{positive_id(item['id'])}/assets", pages
                ):
                    asset_id = positive_id(asset.get("id"))
                    audit.inspect(
                        f"asset-metadata:{asset_id}", json.dumps(asset).encode()
                    )
                    suffix = Path(str(asset.get("name", ""))).suffix.lower()
                    if suffix in {".gz", ".xz", ".7z", ".tar", ".tgz"}:
                        raise AuditError("unsupported-asset-archive")
                    if (
                        type(asset.get("size")) is not int
                        or not 0 <= asset["size"] <= MAX_INPUT
                    ):
                        raise AuditError("asset-size-limit")
                    data = github.get(f"/releases/assets/{asset_id}", binary=True)
                    audit.inspect(
                        f"asset:{asset_id}",
                        data,
                        archive=str(asset.get("name", "")).lower().endswith(".zip"),
                    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--repository")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--max-pages", type=int, default=3)
    args = parser.parse_args(argv)
    if not 1 <= args.max_pages <= 10 or len(args.file) > 100:
        parser.error("Use 1..10 pages and at most 100 files")
    if bool(args.repository) != args.allow_network or (
        not args.file and not args.repository
    ):
        parser.error("Supply --file, or both --repository and --allow-network")
    audit = Audit()
    try:
        for index, path in enumerate(args.file, 1):
            with path.open("rb") as source:
                data = source.read(MAX_INPUT + 1)
            audit.inspect(f"file:{index}", data, archive=path.suffix.lower() == ".zip")
        if args.repository:
            audit_github(audit, GitHub(args.repository), args.max_pages)
    except AuditError as err:
        audit.errors.append({"kind": str(err)})
    except Exception:  # noqa: BLE001 - never print API bodies, signed URLs or private paths
        audit.errors.append({"kind": "read-or-parse-failed"})
    sys.stdout.write(json.dumps(audit.report(), indent=2) + "\n")
    return 2 if audit.errors else (1 if audit.findings else 0)


if __name__ == "__main__":
    sys.exit(main())
