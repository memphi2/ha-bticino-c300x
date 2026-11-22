"""Offline adversarial coverage for the release evidence trust boundary."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validation_evidence as evidence  # noqa: E402
import verify_main_validation as verifier  # noqa: E402
import write_release_assets as writer  # noqa: E402

SHA = "a" * 40
REPO = "example/repo"


def archive(payload, filename="validation-evidence.json"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(filename, json.dumps(payload))
    return stream.getvalue()


class FakeGitHub:
    def __init__(self):
        self.now = datetime.now(UTC)
        self.started = (self.now - timedelta(hours=1)).isoformat()
        self.ended = (self.now - timedelta(minutes=30)).isoformat()
        self.repository = {"id": 42, "full_name": REPO, "default_branch": "main"}
        self.main_sha = self.tag_sha = SHA
        self.workflows, self.runs, self.jobs = {}, {}, {}
        self.artifacts, self.archives, self.payloads = [], {}, {}
        self.reads = []
        for number, (filename, required) in enumerate(verifier.REQUIRED_JOBS.items(), 1):
            self.workflows[filename] = {"id": number, "path": f".github/workflows/{filename}", "state": "active"}
            run = {
                "id": number * 100, "run_attempt": 1, "workflow_id": number,
                "path": self.workflows[filename]["path"],
                "repository": self.repository.copy(), "head_repository": self.repository.copy(),
                "head_sha": SHA, "head_branch": "main", "event": "push",
                "status": "completed", "conclusion": "success",
                "run_started_at": self.started, "updated_at": self.ended,
            }
            self.runs[filename] = [run]
            self.jobs[run["id"]] = [
                {"id": number * 1000 + index, "run_id": run["id"], "run_attempt": 1,
                 "head_sha": SHA, "name": name, "status": "completed", "conclusion": "success",
                 "steps": [{"name": "Required check", "status": "completed", "conclusion": "success"}]}
                for index, name in enumerate(sorted(required))
            ]
        for index, target in enumerate(evidence.TARGETS, 1):
            self.payloads[target] = {
                **evidence.identity(REPO, 42, SHA, 100, 1), "target": target,
                "homeassistant": "2026.10.0" if target == "min-ha" else "2026.12.2",
            }
            self.artifacts.append({
                "id": index, "name": f"ha-validation-{target}-1", "expired": False,
                "created_at": self.ended, "expires_at": (self.now + timedelta(days=6)).isoformat(),
                "workflow_run": {"id": 100, "repository_id": 42, "head_repository_id": 42,
                                 "head_branch": "main", "head_sha": SHA},
            })
            self.repack(target)

    def repack(self, target, filename="validation-evidence.json"):
        item = self.artifacts[evidence.TARGETS.index(target)]
        data = archive(self.payloads[target], filename)
        item.update(size_in_bytes=len(data), digest="sha256:" + hashlib.sha256(data).hexdigest())
        self.archives[item["id"]] = data

    def get(self, path):
        self.reads.append(path)
        if path == "":
            return copy.deepcopy(self.repository)
        if path == "/branches/main":
            return {"commit": {"sha": self.main_sha}}
        if path.startswith("/git/ref/tags/"):
            return {"object": {"type": "commit", "sha": self.tag_sha}}
        return copy.deepcopy(self.workflows[path.split("/")[-1]])

    def listing(self, path, key):
        self.reads.append(path)
        if key == "workflow_runs":
            return copy.deepcopy(self.runs[path.split("/")[3]])
        if key == "jobs":
            return copy.deepcopy(self.jobs[int(path.split("/")[3])])
        return copy.deepcopy(self.artifacts)

    def raw(self, path):
        self.reads.append(path)
        return self.archives[int(path.split("/")[3])]


@pytest.fixture
def api():
    return FakeGitHub()


def test_success_uses_actual_versions_and_records_all_trust_bindings(api):
    result = verifier.verify(api, REPO, "v2.8.2", SHA)
    assert result["source_sha"] == SHA
    assert result["homeassistant"] == {"min-ha": "2026.10.0", "current-ha": "2026.12.2"}
    assert set(result["runs"]) == set(verifier.REQUIRED_JOBS)
    for name, run in result["runs"].items():
        assert set(run["jobs"]) == verifier.REQUIRED_JOBS[name]
        assert run["workflow_digest"] == evidence.workflow_digest(f".github/workflows/{name}")
        assert run["workflow_sha"] == SHA
    assert result["runs"]["validate.yml"]["artifacts"]["min-ha"]["digest"] == api.artifacts[0]["digest"]
    assert sum(path == "/branches/main" for path in api.reads) == 2


@pytest.mark.parametrize("filename", verifier.REQUIRED_JOBS)
@pytest.mark.parametrize("field,value", [
    ("head_sha", "b" * 40), ("head_branch", "beta"), ("event", "pull_request"),
    ("event", "workflow_dispatch"), ("path", ".github/workflows/foreign.yml"),
    ("workflow_id", 999), ("conclusion", "failure"), ("conclusion", "cancelled"),
    ("conclusion", "skipped"), ("run_started_at", "2000-01-01T00:00:00Z"),
    ("updated_at", "2099-01-01T00:00:00Z"), ("run_attempt", 0),
])
def test_rejects_noncanonical_failed_or_stale_runs(api, filename, field, value):
    api.runs[filename][0][field] = value
    with pytest.raises(ValueError):
        verifier.verify(api, REPO, "v2.8.2", SHA)


@pytest.mark.parametrize("kind", ["repository", "head_repository"])
def test_fork_run_is_not_authoritative(api, kind):
    api.runs["validate.yml"][0][kind]["id"] = 987
    with pytest.raises(ValueError, match="Foreign run"):
        verifier.verify(api, REPO, "v2.8.2", SHA)


@pytest.mark.parametrize("filename", verifier.REQUIRED_JOBS)
@pytest.mark.parametrize("mutation", [
    lambda jobs: jobs.pop(),
    lambda jobs: jobs.append(jobs[0].copy()),
    lambda jobs: jobs[0].update(conclusion="skipped"),
    lambda jobs: jobs[0].update(conclusion="failure"),
    lambda jobs: jobs[0].update(run_attempt=2),
    lambda jobs: jobs[0].update(run_id=42),
    lambda jobs: jobs[0].update(head_sha="b" * 40),
    lambda jobs: jobs[0]["steps"][0].update(conclusion="skipped"),
    lambda jobs: jobs[0].update(steps=[]),
])
def test_all_jobs_and_steps_are_required_in_same_attempt(api, filename, mutation):
    mutation(api.jobs[api.runs[filename][0]["id"]])
    with pytest.raises(ValueError):
        verifier.verify(api, REPO, "v2.8.2", SHA)


@pytest.mark.parametrize("mutation", [
    lambda api: setattr(api, "main_sha", "b" * 40),
    lambda api: setattr(api, "tag_sha", "b" * 40),
    lambda api: api.workflows["browser.yml"].update(state="disabled_manually"),
    lambda api: api.workflows["browser.yml"].update(path="foreign.yml"),
    lambda api: api.repository.update(default_branch="beta"),
    lambda api: api.artifacts.clear(),
    lambda api: api.artifacts.append(api.artifacts[0].copy()),
    lambda api: api.artifacts[0].update(expired=True),
    lambda api: api.artifacts[0].update(expires_at="2000-01-01T00:00:00Z"),
    lambda api: api.artifacts[0].update(created_at="2000-01-01T00:00:00Z"),
    lambda api: api.artifacts[0].update(digest="sha256:" + "0" * 64),
    lambda api: api.artifacts[0].update(size_in_bytes=999999),
    lambda api: api.artifacts[0]["workflow_run"].update(id=200),
    lambda api: api.artifacts[0]["workflow_run"].update(head_repository_id=666),
    lambda api: api.artifacts[0]["workflow_run"].update(head_sha="b" * 40),
    lambda api: api.repack("min-ha", "../validation-evidence.json"),
])
def test_release_identity_and_artifact_failures_are_closed(api, mutation):
    mutation(api)
    with pytest.raises(ValueError):
        verifier.verify(api, REPO, "v2.8.2", SHA)


@pytest.mark.parametrize("field,value", [
    ("source_sha", "b" * 40), ("workflow_sha", "b" * 40), ("run_id", 101),
    ("run_attempt", 2), ("repository_id", 666), ("repository", "fork/repo"),
    ("workflow_ref", "example/repo/.github/workflows/validate.yml@refs/pull/1/merge"),
    ("workflow_digest", "sha256:" + "0" * 64), ("event", "pull_request"),
    ("target", "current-ha"), ("homeassistant", "2026.10.1"),
    ("homeassistant", "2026.11.0b1"), ("schema", 2), ("extra", "conflict"),
])
def test_valid_archive_digest_does_not_authorize_foreign_payload(api, field, value):
    api.payloads["min-ha"][field] = value
    api.repack("min-ha")
    with pytest.raises(ValueError):
        verifier.verify(api, REPO, "v2.8.2", SHA)


def test_latest_failed_run_cannot_fall_back_to_previous_success(api):
    newer = {**api.runs["validate.yml"][0], "id": 999, "conclusion": "failure"}
    api.runs["validate.yml"].append(newer)
    with pytest.raises(ValueError, match="Unsuccessful workflow"):
        verifier.verify(api, REPO, "v2.8.2", SHA)


@pytest.mark.parametrize("state", ["missing", "in_progress"])
def test_missing_or_running_checks_can_be_waited_for(api, state):
    if state == "missing":
        api.runs["validate.yml"].clear()
    else:
        api.runs["validate.yml"][0]["status"] = state
    with pytest.raises(verifier.Pending):
        verifier.verify(api, REPO, "v2.8.2", SHA)


def test_rerun_during_verification_fails(api, monkeypatch):
    original = api.listing

    def changing(path, key):
        result = original(path, key)
        if key == "workflow_runs" and path.count("validate.yml") and api.reads.count(path) == 2:
            result[0]["run_attempt"] += 1
        return result

    monkeypatch.setattr(api, "listing", changing)
    with pytest.raises(ValueError, match="changed during"):
        verifier.verify(api, REPO, "v2.8.2", SHA)


def test_complete_rerun_binds_only_current_attempt_evidence(api):
    previous_artifacts = copy.deepcopy(api.artifacts)
    for runs in api.runs.values():
        runs[0]["run_attempt"] = 2
        for job in api.jobs[runs[0]["id"]]:
            job["run_attempt"] = 2
            job["id"] += 10000
    for target, artifact in zip(evidence.TARGETS, api.artifacts, strict=True):
        api.payloads[target]["run_attempt"] = 2
        artifact.update(id=artifact["id"] + 100, name=f"ha-validation-{target}-2")
        api.repack(target)
    api.artifacts.extend(previous_artifacts)

    result = verifier.verify(api, REPO, "v2.8.2", SHA)
    for run in result["runs"].values():
        assert run["attempt"] == 2
        assert f"/actions/runs/{run['id']}/attempts/2/jobs" in api.reads
    assert result["runs"]["validate.yml"]["artifacts"]["min-ha"]["id"] == 101
    assert "/actions/artifacts/1/zip" not in api.reads


def test_pagination_consumes_structured_pages_and_rejects_truncation(monkeypatch):
    api = verifier.GitHub(REPO)
    pages = [{"total_count": 2, "jobs": [{"id": 1}]}, {"total_count": 2, "jobs": [{"id": 2}]}]
    monkeypatch.setattr(api, "get", lambda path: pages.pop(0))
    assert api.listing("/jobs?filter=all", "jobs") == [{"id": 1}, {"id": 2}]
    monkeypatch.setattr(api, "get", lambda path: {"total_count": 2, "jobs": []})
    with pytest.raises(ValueError, match="pagination"):
        api.listing("/jobs", "jobs")


@pytest.mark.parametrize("environment", ["CI", "GITHUB_ACTIONS"])
def test_ci_metadata_cannot_guess_versions(monkeypatch, environment):
    monkeypatch.setenv(environment, "true")
    monkeypatch.delenv("C300X_VALIDATION_EVIDENCE", raising=False)
    monkeypatch.setenv("C300X_VALIDATED_CURRENT_HA_VERSION", "2026.12.2")
    with pytest.raises(writer.ReleaseAssetError, match="requires canonical"):
        writer._lts_evidence(tag="v2.8.2", native_agent_reused_from=None)


def test_metadata_consumes_exact_gate_bytes_and_records_run_bindings(api, tmp_path, monkeypatch):
    result = verifier.verify(api, REPO, "v2.8.2", SHA)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(result))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("C300X_VALIDATION_EVIDENCE", str(path))
    monkeypatch.setenv("C300X_VALIDATION_EVIDENCE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setenv("C300X_VALIDATED_CURRENT_HA_VERSION", "2099.1.1")
    monkeypatch.setattr(writer, "_git_output", lambda *args: SHA)
    value = writer._lts_evidence(tag="v2.8.2", native_agent_reused_from=None)
    assert value["current_homeassistant"] == "2026.12.2"
    assert value["validated_homeassistant"] == ["2026.10.0", "2026.12.2"]
    assert value["validation_status"] == "canonical-main-push"
    assert value["validation_evidence"] == result
    assert "browser" in value["validated_jobs"] and "dependabot" in value["validated_jobs"]
    path.write_text(path.read_text() + " ")
    with pytest.raises(writer.ReleaseAssetError, match="digest"):
        writer._lts_evidence(tag="v2.8.2", native_agent_reused_from=None)


def test_workflows_bind_evidence_and_preserve_full_pr_main_checks():
    workflows = {name: yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text()) for name in ("release", "validate", "browser", "codeql")}
    for name in ("validate", "browser", "codeql"):
        assert "pull_request" in workflows[name][True]
        assert "main" in workflows[name][True]["push"]["branches"]
    validate = workflows["validate"]["jobs"]
    assert set(validate) == {"validate", "hacs", "hassfest", "dependabot"}
    steps = validate["validate"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Validation gates") < names.index("Home Assistant container runtime") < names.index("Record validated HA version") < names.index("Upload validated HA evidence")
    upload = steps[names.index("Upload validated HA evidence")]
    assert upload["with"]["name"] == "ha-validation-${{ matrix.name }}-${{ github.run_attempt }}"
    assert upload["with"]["if-no-files-found"] == "error"
    assert not upload["with"].get("overwrite")
    screenshots = next(step for step in workflows["browser"]["jobs"]["browser"]["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert screenshots["with"]["name"] == "synthetic-card-screenshots-${{ github.run_attempt }}"
    jobs = workflows["release"]["jobs"]
    assert set(jobs) == {"main-validation", "publish"}
    assert jobs["publish"]["needs"] == ["main-validation"]
    assert jobs["main-validation"]["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    assert jobs["publish"]["steps"][0]["with"]["ref"] == "${{ needs.main-validation.outputs.commit }}"
    publish = jobs["publish"]["steps"]
    by_name = {step.get("name"): step for step in publish}
    for name in ("Verify canonical validation evidence", "Recheck canonical evidence before publication"):
        step = by_name[name]
        assert '--expect-digest "$EVIDENCE_DIGEST"' in step["run"]
        assert step["env"]["EVIDENCE_DIGEST"] == "${{ needs.main-validation.outputs.evidence-digest }}"
        assert "if" not in step and not step.get("continue-on-error")
    assert publish.index(by_name["Recheck canonical evidence before publication"]) < publish.index(by_name["Publish GitHub Release assets"])
    assert "resolve_ha_version.py" not in str(jobs)


@pytest.mark.parametrize("field,value", [
    (None, None), ("GITHUB_REF", "refs/heads/beta"), ("GITHUB_EVENT_NAME", "pull_request"),
    ("GITHUB_WORKFLOW_SHA", "b" * 40), ("GITHUB_WORKFLOW_REF", "foreign"),
    ("installed", "2026.11.1"), ("checkout", "b" * 40),
])
def test_generator_only_records_actual_installed_main_push_version(tmp_path, monkeypatch, field, value):
    env = {
        "GITHUB_REPOSITORY": REPO, "GITHUB_REPOSITORY_ID": "42", "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main", "GITHUB_WORKFLOW_SHA": SHA,
        "GITHUB_WORKFLOW_REF": f"{REPO}/.github/workflows/validate.yml@refs/heads/main",
    }
    for key, item in env.items():
        monkeypatch.setenv(key, item)
    if field and field.startswith("GITHUB"):
        monkeypatch.setenv(field, value)
    monkeypatch.setattr(evidence.importlib.metadata, "version", lambda name: value if field == "installed" else "2026.12.2")
    monkeypatch.setattr(evidence.subprocess, "check_output", lambda *args, **kwargs: value if field == "checkout" else SHA)
    output = tmp_path / "validation-evidence.json"
    monkeypatch.setattr(sys, "argv", ["generator", "current-ha", "--version", "2026.12.2", "--output", str(output)])
    if field is None:
        evidence.main()
        assert json.loads(output.read_text())["homeassistant"] == "2026.12.2"
    else:
        with pytest.raises(ValueError):
            evidence.main()
        assert not output.exists()


@pytest.mark.parametrize("change", [
    None, "digest", "workflow-sha", "workflow-ref", "run-sha", "run-ref",
    "run-event", "dispatch", "summary-sha", "summary-minimum",
])
def test_release_cli_and_metadata_digest_binding(api, tmp_path, monkeypatch, change):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_SHA", "b" * 40 if change == "run-sha" else SHA)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main" if change == "run-ref" else "refs/tags/v2.8.2")
    monkeypatch.setenv("GITHUB_EVENT_NAME", {"run-event": "pull_request", "dispatch": "workflow_dispatch"}.get(change, "push"))
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", "b" * 40 if change == "workflow-sha" else SHA)
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "foreign" if change == "workflow-ref" else f"{REPO}/.github/workflows/release.yml@refs/tags/v2.8.2")
    monkeypatch.setattr(verifier.subprocess, "check_output", lambda *args, **kwargs: SHA)
    monkeypatch.setattr(verifier, "GitHub", lambda repository: api)
    expected = verifier.verify(api, REPO, "v2.8.2", SHA)
    data = (json.dumps(expected, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    output = tmp_path / "verified.json"
    github_output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setattr(sys, "argv", ["verify", "--tag", "v2.8.2", "--output", str(output), "--expect-digest", "0" * 64 if change == "digest" else digest])
    if change in {"digest", "workflow-sha", "workflow-ref", "run-sha", "run-ref", "run-event"}:
        with pytest.raises(ValueError):
            verifier.main()
        assert not output.exists() and not github_output.exists()
        return
    assert verifier.main() == 0
    assert output.read_bytes() == data
    assert f"evidence-digest={digest}" in github_output.read_text()
    if change == "summary-sha":
        expected["source_sha"] = "b" * 40
    if change == "summary-minimum":
        expected["homeassistant"]["min-ha"] = "2026.10.1"
    output.write_text(json.dumps(expected))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    if change in {"summary-sha", "summary-minimum"}:
        with pytest.raises(ValueError):
            evidence.load_verified_summary(output, digest, SHA, REPO)
    else:
        assert evidence.load_verified_summary(output, digest, SHA, REPO) == expected
