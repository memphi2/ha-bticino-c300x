"""Exercise publication locally with all Git/GitHub operations mocked."""

import importlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def setup_publication(monkeypatch, tmp_path, *, version="2.1.0b1", existing=False,
                      draft=False, corrupt=False, api_failure=False, moved=False):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    publisher = importlib.import_module("publish_release")
    monkeypatch.setattr(publisher, "ROOT", tmp_path)
    monkeypatch.setattr(publisher, "read_integration_version", lambda: version)
    tag = f"v{version}"
    notes = tmp_path / f".github/release-notes/{tag}.md"
    notes.parent.mkdir(parents=True)
    notes.write_text(f"# {tag}\n\nRelease notes\n")
    directory = tmp_path / "assets"
    directory.mkdir()
    for name in publisher.ASSETS:
        (directory / name).write_bytes(f"asset:{name}".encode())
    release = {"tag_name": tag, "prerelease": publisher.is_prerelease(tag),
               "draft": draft, "body": notes.read_text(),
               "assets": [{"name": name} for name in publisher.ASSETS]}
    remote = [release] if existing else []
    calls = []

    def run(*args):
        calls.append(args)
        if args[:2] == ("git", "rev-parse"):
            return "a" * 40
        if args[:2] == ("git", "ls-remote"):
            assert args[3] == "https://github.com/owner/repo.git"
            second_check = sum(call[:2] == ("git", "ls-remote") for call in calls) > 1
            commit = ("b" if moved and second_check else "a") * 40
            return f"{commit}\trefs/tags/{tag}\n"
        if args[:2] == ("gh", "api"):
            if api_failure:
                raise subprocess.CalledProcessError(1, "gh api")
            return json.dumps([remote])
        if args[:3] == ("gh", "release", "create"):
            assert "--draft" in args and "--verify-tag" in args
            release["draft"] = True
            remote.append(release)
        elif args[:3] == ("gh", "release", "download"):
            destination = Path(args[args.index("--dir") + 1])
            for name in publisher.ASSETS:
                (destination / name).write_bytes((directory / name).read_bytes())
            if corrupt:
                (destination / "SHA256SUMS").write_text("corrupt")
        elif args[:3] == ("gh", "release", "edit"):
            assert "--draft=false" in args
            release["draft"] = False
        else:
            pytest.fail(f"Unexpected external command: {args}")
        return ""

    monkeypatch.setattr(publisher, "run", run)
    return publisher, directory, release, calls


@pytest.mark.parametrize("version", ["2.1.0", "2.1.0b1", "2.1.0rc1"])
@pytest.mark.parametrize(("existing", "draft"), [(False, False), (True, True), (True, False)])
def test_publication_channel_and_idempotent_verified_assets(monkeypatch, tmp_path, version, existing, draft):
    publisher, directory, release, calls = setup_publication(
        monkeypatch, tmp_path, version=version, existing=existing, draft=draft)
    publisher.publish("owner/repo", f"v{version}", directory)
    assert release["draft"] is False
    assert not any("upload" in call or "--clobber" in call for call in calls)
    creates = [call for call in calls if call[:3] == ("gh", "release", "create")]
    edits = [call for call in calls if call[:3] == ("gh", "release", "edit")]
    for command in creates + edits:
        assert ("--latest=false" in command) is release["prerelease"]
    for command in creates:
        assert ("--prerelease" in command) is release["prerelease"]
    downloads = [i for i, call in enumerate(calls) if call[:3] == ("gh", "release", "download")]
    assert downloads
    if edits:
        assert downloads[-1] < calls.index(edits[0])
    before = len(calls)
    publisher.publish("owner/repo", f"v{version}", directory)
    assert not any(call[:3] in (("gh", "release", "create"), ("gh", "release", "edit"))
                   for call in calls[before:])


@pytest.mark.parametrize("failure", ["corrupt", "api_failure", "moved"])
def test_failed_verification_never_publishes(monkeypatch, tmp_path, failure):
    publisher, directory, release, calls = setup_publication(monkeypatch, tmp_path, **{failure: True})
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        publisher.publish("owner/repo", "v2.1.0b1", directory)
    assert not any(call[:3] == ("gh", "release", "edit") for call in calls)
    if failure == "api_failure":
        assert not any(call[:3] == ("gh", "release", "create") for call in calls)
    else:
        assert release["draft"] is True


@pytest.mark.parametrize("field", ["prerelease", "body", "assets", "draft"])
def test_conflicting_existing_release_is_never_modified(monkeypatch, tmp_path, field):
    publisher, directory, release, calls = setup_publication(monkeypatch, tmp_path, existing=True)
    release[field] = {"prerelease": False, "body": "different notes", "assets": [], "draft": None}[field]
    with pytest.raises(ValueError, match="differ"):
        publisher.publish("owner/repo", "v2.1.0b1", directory)
    assert not any(call[:2] == ("gh", "release") for call in calls)


@pytest.mark.parametrize(("repo", "tag"), [("owner/repo", "../main"), ("--invalid", "v2.1.0b1"),
                                          ("../repo", "v2.1.0b1"), ("owner/..", "v2.1.0b1"),
                                          ("owner/repo", "v2.1.0b2")])
def test_invalid_identity_stops_before_external_operations(monkeypatch, tmp_path, repo, tag):
    publisher, directory, _, calls = setup_publication(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        publisher.publish(repo, tag, directory)
    assert calls == []


@pytest.mark.parametrize("annotated", [False, True])
def test_remote_tag_verification_handles_lightweight_and_annotated_tags(monkeypatch, tmp_path, annotated):
    publisher, _, _, _ = setup_publication(monkeypatch, tmp_path)
    ref = "refs/tags/v2.1.0b1"
    response = f"{'a' * 40}\t{ref}\n"
    if annotated:
        response = f"{'b' * 40}\t{ref}\n{'a' * 40}\t{ref}^{{}}\n"
    monkeypatch.setattr(publisher, "run", lambda *args: response)
    publisher.verify_source_tag("owner/repo", "v2.1.0b1", "a" * 40)
    with pytest.raises(ValueError, match="does not match"):
        publisher.verify_source_tag("owner/repo", "v2.1.0b1", "c" * 40)


@pytest.mark.parametrize("empty", [False, True])
def test_missing_or_empty_asset_stops_before_external_operations(monkeypatch, tmp_path, empty):
    publisher, directory, _, calls = setup_publication(monkeypatch, tmp_path)
    asset = directory / "ha-bticino-c300x.zip"
    if empty:
        asset.write_bytes(b"")
    else:
        asset.unlink()
    with pytest.raises(ValueError, match="missing or empty"):
        publisher.publish("owner/repo", "v2.1.0b1", directory)
    assert calls == []


def test_duplicate_release_lookup_stops_before_publication(monkeypatch, tmp_path):
    publisher, directory, release, calls = setup_publication(monkeypatch, tmp_path, existing=True)
    original_run = publisher.run

    def duplicate(*args):
        if args[:2] == ("gh", "api"):
            return json.dumps([[release, release]])
        return original_run(*args)

    monkeypatch.setattr(publisher, "run", duplicate)
    with pytest.raises(ValueError, match="multiple releases"):
        publisher.publish("owner/repo", "v2.1.0b1", directory)
    assert not any(call[:2] == ("gh", "release") for call in calls)
