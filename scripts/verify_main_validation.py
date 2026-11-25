#!/usr/bin/env python3
"""Require fresh, complete canonical branch-push checks for the exact release SHA."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from validation_evidence import (
    ROOT,
    TARGETS,
    identity,
    release_branches,
    require,
    validate_payload,
    workflow_digest,
)

REQUIRED_JOBS = {
    "validate.yml": {"dependabot", "hacs", "hassfest", "validate (min-ha)", "validate (current-ha)"},
    "browser.yml": {"browser"},
    "codeql.yml": {f"analyze ({language})" for language in ("actions", "c-cpp", "javascript-typescript", "python")},
}
MAX_AGE = timedelta(days=7)
MAX_ARCHIVE = 65536


class Pending(ValueError):
    """Only missing or still-running checks may be waited for."""


class GitHub:
    def __init__(self, repository: str) -> None:
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None, "Invalid repository")
        self.base = f"/repos/{repository}"

    def raw(self, path: str) -> bytes:
        return subprocess.check_output([
            "gh", "api", "--method", "GET", "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2022-11-28", self.base + path,
        ], timeout=60)

    def get(self, path: str) -> dict:
        return json.loads(self.raw(path))

    def listing(self, path: str, key: str) -> list[dict]:
        items = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 11):
            result = self.get(f"{path}{separator}per_page=100&page={page}")
            items.extend(result[key])
            if len(items) == result["total_count"]:
                require(len({item["id"] for item in items}) == len(items), "Duplicate API records")
                return items
            require(len(items) < result["total_count"] and bool(result[key]), "Inconsistent API pagination")
        raise ValueError("Too many evidence records; refusing truncated results")


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "Missing evidence timezone")
    return result


def check_run(run: dict, workflow: dict, repository: dict, sha: str, now: datetime, branch: str = "main") -> None:
    require(workflow["state"] == "active", "Required workflow disabled")
    require(run["workflow_id"] == workflow["id"] and run["path"] == workflow["path"], "Foreign workflow identity")
    for key in ("repository", "head_repository"):
        require(run[key]["id"] == repository["id"] and run[key]["full_name"] == repository["full_name"], "Foreign run repository")
    require(run["head_sha"] == sha and run["head_branch"] == branch and run["event"] == "push", "Not an exact-SHA canonical branch push")
    require(type(run["id"]) is int and run["id"] > 0 and type(run["run_attempt"]) is int and run["run_attempt"] > 0, "Invalid run identity")
    if run["status"] != "completed":
        raise Pending(f"Workflow {workflow['path']} is {run['status']}")
    require(run["conclusion"] == "success", f"Unsuccessful workflow: {workflow['path']}")
    started, ended = timestamp(run["run_started_at"]), timestamp(run["updated_at"])
    require(now - MAX_AGE <= started <= ended <= now, "Stale or future workflow evidence")


def check_jobs(jobs: list[dict], run: dict, workflow: str) -> None:
    require(len(jobs) == len(REQUIRED_JOBS[workflow]) and {job["name"] for job in jobs} == REQUIRED_JOBS[workflow], "Missing, duplicate or unexpected required jobs (partial rerun)")
    for job in jobs:
        require(job["run_id"] == run["id"] and job["run_attempt"] == run["run_attempt"] and job["head_sha"] == run["head_sha"], "Foreign job identity")
        require(job["status"] == "completed" and job["conclusion"] == "success", f"Unsuccessful required job: {job['name']}")
        require(bool(job["steps"]) and all(step["status"] == "completed" and step["conclusion"] == "success" for step in job["steps"]), f"Skipped or unsuccessful steps: {job['name']}")


def artifact_payload(artifact: dict, archive: bytes, expected: dict, target: str, run: dict, now: datetime) -> str:
    require(artifact["expired"] is False and timestamp(artifact["expires_at"]) > now, "Expired evidence artifact")
    require(timestamp(run["run_started_at"]) <= timestamp(artifact["created_at"]) <= timestamp(run["updated_at"]), "Stale artifact attempt")
    binding = artifact["workflow_run"]
    for key, value in {
        "id": expected["run_id"], "repository_id": expected["repository_id"],
        "head_repository_id": expected["repository_id"], "head_sha": expected["source_sha"], "head_branch": expected["ref"].removeprefix("refs/heads/"),
    }.items():
        require(binding[key] == value, "Foreign artifact run")
    require(0 < len(archive) <= MAX_ARCHIVE and len(archive) == artifact["size_in_bytes"], "Unexpected artifact size")
    require(artifact["digest"] == "sha256:" + hashlib.sha256(archive).hexdigest(), "Artifact digest mismatch")
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        require(zipped.namelist() == ["validation-evidence.json"], "Unexpected evidence archive members")
        require(zipped.infolist()[0].file_size <= MAX_ARCHIVE, "Oversized evidence payload")
        payload = json.loads(zipped.read("validation-evidence.json"))
    return validate_payload(payload, expected, target)


def check_refs(api: GitHub, tag: str, sha: str) -> str:
    branch = None
    for candidate in release_branches(tag):
        refs = api.get(f"/git/matching-refs/heads/{candidate}")
        matches = [ref for ref in refs if ref["ref"] == f"refs/heads/{candidate}"]
        require(len(matches) <= 1, "Conflicting canonical branch references")
        if matches:
            require(matches[0]["object"]["type"] == "commit", "Canonical branch must reference a commit")
            if matches[0]["object"]["sha"] == sha:
                branch = candidate
                break
    require(branch is not None, "Release is not current authorized branch HEAD")
    obj = api.get(f"/git/ref/tags/{quote(tag, safe='')}")["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            require(obj["sha"] == sha, "Release tag differs from checkout/branch")
            return branch
        require(obj["type"] == "tag", "Unexpected release tag object")
        obj = api.get(f"/git/tags/{obj['sha']}")["object"]
    raise ValueError("Excessively nested release tag")


def select_run(api: GitHub, filename: str, sha: str, branch: str = "main") -> dict:
    runs = api.listing(f"/actions/workflows/{filename}/runs?branch={branch}&event=push&head_sha={sha}", "workflow_runs")
    if not runs:
        raise Pending(f"Missing canonical {filename} {branch} push for {sha}")
    # Never fall back to an older successful run when a newer run fails or waits.
    return max(runs, key=lambda run: run["id"])


def verify(api: GitHub, repository_name: str, tag: str, sha: str) -> dict:
    now = datetime.now(UTC)
    branch = check_refs(api, tag, sha)
    repository = api.get("")
    require(repository["full_name"] == repository_name and repository["default_branch"] == "main", "Noncanonical repository")
    result = {"schema": 1, "repository": repository_name, "repository_id": repository["id"], "source_sha": sha, "source_branch": branch, "homeassistant": {}, "runs": {}}
    snapshots = {}
    for filename in REQUIRED_JOBS:
        workflow = api.get(f"/actions/workflows/{filename}")
        path = f".github/workflows/{filename}"
        require(workflow["path"] == path, "Unexpected workflow definition")
        run = select_run(api, filename, sha, branch)
        check_run(run, workflow, repository, sha, now, branch)
        jobs = api.listing(f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", "jobs")
        check_jobs(jobs, run, filename)
        record = {
            "id": run["id"], "attempt": run["run_attempt"], "workflow_id": workflow["id"],
            "workflow_path": path, "workflow_sha": sha, "workflow_digest": workflow_digest(path),
            "jobs": {job["name"]: job["id"] for job in jobs}, "artifacts": {},
        }
        if filename == "validate.yml":
            artifacts = api.listing(f"/actions/runs/{run['id']}/artifacts", "artifacts")
            expected = identity(repository_name, repository["id"], sha, run["id"], run["run_attempt"], branch)
            for target in TARGETS:
                name = f"ha-validation-{target}-{run['run_attempt']}"
                matches = [artifact for artifact in artifacts if artifact["name"] == name]
                require(len(matches) == 1, f"Missing or conflicting evidence artifact: {name}")
                artifact = matches[0]
                require(type(artifact["id"]) is int and artifact["id"] > 0 and 0 < artifact["size_in_bytes"] <= MAX_ARCHIVE, "Invalid evidence artifact identity/size")
                archive = api.raw(f"/actions/artifacts/{artifact['id']}/zip")
                result["homeassistant"][target] = artifact_payload(artifact, archive, expected, target, run, now)
                record["artifacts"][target] = {"id": artifact["id"], "digest": artifact["digest"]}
        result["runs"][filename] = record
        snapshots[filename] = run
    # Re-read after downloads: reject a concurrent rerun or replacement run.
    for filename, previous in snapshots.items():
        current = select_run(api, filename, sha, branch)
        require(all(current[key] == previous[key] for key in ("id", "run_attempt", "status", "conclusion", "updated_at")), "Workflow changed during evidence verification")
    require(check_refs(api, tag, sha) == branch, "Canonical release branch changed during verification")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--expect-digest")
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "Invalid source SHA")
    require(os.environ["GITHUB_SHA"] == sha, "Release run SHA differs from checkout")
    require(os.environ["GITHUB_REF"] == f"refs/tags/{args.tag}", "Release run must use the release tag")
    require(os.environ["GITHUB_EVENT_NAME"] in {"push", "workflow_dispatch"}, "Untrusted release event")
    require(os.environ["GITHUB_WORKFLOW_SHA"] == sha, "Release workflow must come from released source SHA")
    require(os.environ["GITHUB_WORKFLOW_REF"] == f"{os.environ['GITHUB_REPOSITORY']}/.github/workflows/release.yml@refs/tags/{args.tag}", "Untrusted release workflow ref")
    deadline = time.monotonic() + args.wait_seconds
    api = GitHub(os.environ["GITHUB_REPOSITORY"])
    while True:
        try:
            evidence = verify(api, os.environ["GITHUB_REPOSITORY"], args.tag, sha)
            break
        except Pending as err:
            if time.monotonic() >= deadline:
                raise ValueError(f"Timed out: {err}") from err
            sys.stdout.write(f"Waiting: {err}\n")
            time.sleep(min(10, max(0, deadline - time.monotonic())))
    data = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    require(args.expect_digest is None or digest == args.expect_digest, "Validation evidence changed since release gate")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"commit={sha}\nevidence-digest={digest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
