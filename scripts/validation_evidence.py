#!/usr/bin/env python3
"""Record and validate the small, immutable main-push HA evidence payload."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
from pathlib import Path

from resolve_ha_version import stable_version

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/validate.yml"
TARGETS = ("min-ha", "current-ha")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def workflow_digest(path: str) -> str:
    return "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def identity(repository: str, repository_id: int, sha: str, run_id: int, attempt: int) -> dict:
    return {
        "schema": 1,
        "repository": repository,
        "repository_id": repository_id,
        "source_sha": sha,
        "event": "push",
        "ref": "refs/heads/main",
        "workflow_ref": f"{repository}/{WORKFLOW}@refs/heads/main",
        "workflow_sha": sha,
        "workflow_digest": workflow_digest(WORKFLOW),
        "run_id": run_id,
        "run_attempt": attempt,
    }


def validate_payload(payload: dict, expected: dict, target: str) -> str:
    require(set(payload) == set(expected) | {"target", "homeassistant"}, "Unexpected evidence fields")
    require(all(payload[key] == value for key, value in expected.items()), "Foreign or stale evidence identity")
    require(payload["target"] == target, "Conflicting HA matrix target")
    version = payload["homeassistant"]
    stable_version(version)
    minimum = json.loads((ROOT / "project-versions.json").read_text())["min_homeassistant"]
    require(stable_version(version) >= stable_version(minimum), "HA version below declared minimum")
    if target == "min-ha":
        require(version == minimum, "Validated minimum differs from declared minimum")
    return version


def load_verified_summary(path: Path, digest: str, sha: str, repository: str) -> dict:
    """Consume bytes pinned by the successful release gate, not a self-claim."""
    data = path.read_bytes()
    require(bool(digest) and hashlib.sha256(data).hexdigest() == digest, "Unverified validation evidence digest")
    result = json.loads(data)
    require(result["schema"] == 1 and result["source_sha"] == sha and result["repository"] == repository, "Foreign validation evidence")
    require(set(result["homeassistant"]) == set(TARGETS), "Incomplete HA evidence")
    minimum = json.loads((ROOT / "project-versions.json").read_text())["min_homeassistant"]
    require(result["homeassistant"]["min-ha"] == minimum, "Validated minimum differs from declared minimum")
    require(stable_version(result["homeassistant"]["current-ha"]) >= stable_version(minimum), "Invalid validated current HA")
    require(set(result["runs"]) == {"validate.yml", "browser.yml", "codeql.yml"}, "Incomplete workflow evidence")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = identity(
        os.environ["GITHUB_REPOSITORY"], int(os.environ["GITHUB_REPOSITORY_ID"]),
        os.environ["GITHUB_SHA"], int(os.environ["GITHUB_RUN_ID"]),
        int(os.environ["GITHUB_RUN_ATTEMPT"]),
    )
    for key, env in (
        ("event", "GITHUB_EVENT_NAME"), ("ref", "GITHUB_REF"),
        ("workflow_ref", "GITHUB_WORKFLOW_REF"), ("workflow_sha", "GITHUB_WORKFLOW_SHA"),
    ):
        require(payload[key] == os.environ[env], f"Untrusted evidence context: {env}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(head == payload["source_sha"], "Evidence checkout differs from source SHA")
    require(importlib.metadata.version("homeassistant") == args.version, "Installed HA differs from resolved HA")
    result = {**payload, "target": args.target, "homeassistant": args.version}
    validate_payload(result, payload, args.target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
