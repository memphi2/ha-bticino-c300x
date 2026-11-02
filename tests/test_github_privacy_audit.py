"""Offline tests only: no GitHub calls or real secrets."""

from __future__ import annotations

import importlib.util
import io
import ipaddress
import json
import stat
from pathlib import Path
from urllib.request import Request
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

SPEC = importlib.util.spec_from_file_location(
    "privacy_audit",
    Path(__file__).resolve().parents[1] / "scripts/audit_github_privacy.py",
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def archive(members):
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as zip_file:
        for name, value in members.items():
            zip_file.writestr(name, value)
    return output.getvalue()


@pytest.mark.parametrize(
    "text,kind",
    [
        (b"ghp_" + b"a" * 36, "github-token"),
        (b"-----BEGIN PRIVATE KEY-----", "private-key"),
        (b"Bearer " + b"a" * 32, "bearer-token"),
        (b"https://demo:synthetic-password@example.invalid", "url-credentials"),
        (b"/home/synthetic/config", "personal-home-path"),
        (str(ipaddress.IPv4Address(0xC0A81718)).encode(), "private-network-address"),
        (b"fd12:3456::1", "private-network-address"),
        (b'{"password": "synthetic-secret"}', "credential-shaped-value"),
    ],
)
def test_detects_sensitive_shapes_without_echoing_content(text, kind):
    result = audit.Audit()
    result.inspect("fixture:1", text)
    assert {"source": "fixture:1", "kind": kind} in result.findings
    assert text.decode() not in json.dumps(result.report())


def test_documentation_addresses_and_public_urls_are_not_private():
    assert (
        audit.scan_text(
            b"https://github.com/example/repo 192.0.2.1 198.51.100.1 203.0.113.1 2001:db8::1"
        )
        == set()
    )


def test_zip_checks_paths_and_contents_without_extraction():
    result = audit.scan_zip(
        archive({"../private/.env": "Bearer " + "x" * 32, "sample.pcap": "synthetic"})
    )
    assert {
        "unsafe-archive-path",
        "private-config-path",
        "bearer-token",
        "capture-or-firmware-payload",
    } <= result


def test_archive_limits_fail_closed(monkeypatch):
    monkeypatch.setattr(audit, "MAX_MEMBER", 10)
    with pytest.raises(audit.AuditError, match="archive-member-size-limit"):
        audit.scan_zip(archive({"large.txt": "x" * 11}))
    with pytest.raises(audit.AuditError, match="nested-archive-not-inspected"):
        audit.scan_zip(archive({"nested.zip": ""}))
    with pytest.raises(audit.AuditError, match="invalid-or-unsupported-archive"):
        audit.scan_zip(b"not a zip")


def test_redirect_drops_auth_and_rejects_non_github_hosts():
    request = Request(
        "https://api.github.com/repos/example/repo/releases/assets/1",
        headers={"Authorization": "Bearer synthetic"},
    )
    handler = audit.SafeRedirect()
    redirected = handler.redirect_request(
        request,
        None,
        302,
        "",
        {},
        "https://release-assets.githubusercontent.com/example",
    )
    assert not redirected.has_header("Authorization")
    for url in (
        "http://api.github.com/a",
        "https://example.invalid/a",
        "https://api.github.com@evil.invalid/a",
        "https://api.github.com:8443/a",
    ):
        with pytest.raises(audit.AuditError, match="unsafe-redirect"):
            handler.redirect_request(request, None, 302, "", {}, url)


def test_network_requires_explicit_opt_in(monkeypatch, tmp_path, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline audit tried network access")

    monkeypatch.setattr(audit, "GitHub", forbidden)
    path = tmp_path / "synthetic.json"
    path.write_text('{"ok": true}')
    assert audit.main(["--file", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["complete"] is True
    with pytest.raises(SystemExit):
        audit.main(["--repository", "example/repo"])


def test_read_errors_never_print_private_paths(tmp_path, capsys):
    path = tmp_path / "synthetic-private-secret"
    assert audit.main(["--file", str(path)]) == 2
    result = capsys.readouterr()
    assert str(path) not in result.out + result.err
    assert "synthetic-private-secret" not in result.out + result.err


def test_pagination_limit_is_not_reported_as_complete(monkeypatch):
    client = audit.GitHub("example/repo")
    monkeypatch.setattr(client, "get", lambda *args: [{"id": 1}] * 100)
    with pytest.raises(audit.AuditError, match="pagination-limit"):
        list(client.items("/issues?state=all", 1))


def test_all_remote_surfaces_are_covered_with_synthetic_responses():
    class FakeGitHub:
        def __init__(self):
            self.paths = []

        def items(self, path, pages):
            self.paths.append(path)
            if path == "/issues?state=all":
                return [{"id": 1, "number": 2, "pull_request": {}, "body": "safe"}]
            if path == "/releases":
                return [{"id": 3, "body": "safe"}]
            if path == "/releases/3/assets":
                return [{"id": 4, "name": "bundle.zip", "size": 100}]
            return [{"id": 5, "body": "Bearer " + "x" * 32}]

        def get(self, path, *, binary=False):
            if path == "":
                return {"private": False}
            assert path == "/releases/assets/4" and binary
            return archive({"fixture.txt": "safe"})

    client = FakeGitHub()
    result = audit.Audit()
    audit.audit_github(result, client, 1)
    assert set(client.paths) == {
        "/issues?state=all",
        "/issues/comments",
        "/pulls/comments",
        "/pulls/2/reviews",
        "/releases",
        "/releases/3/assets",
    }
    assert len(result.findings) == 3
    assert result.scanned == 7


def test_zip_symlinks_and_windows_paths_are_flagged():
    stream = io.BytesIO()
    with ZipFile(stream, "w") as zip_file:
        link = ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zip_file.writestr(link, "../outside")
        zip_file.writestr("C:\\private\\file", "safe")
    assert "unsafe-archive-path" in audit.scan_zip(stream.getvalue())


def test_archive_signatures_cannot_hide_behind_text_filenames():
    result = audit.Audit()
    result.inspect("fixture:1", archive({"key.txt": "-----BEGIN PRIVATE KEY-----"}))
    assert result.findings == [{"source": "fixture:1", "kind": "private-key"}]
    with pytest.raises(audit.AuditError, match="nested-archive-not-inspected"):
        audit.scan_zip(archive({"disguised.txt": archive({"hidden.txt": "safe"})}))
    with pytest.raises(audit.AuditError, match="unsupported-asset-archive"):
        result.inspect("fixture:2", b"\x1f\x8bsynthetic")


def test_total_byte_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(audit, "MAX_TOTAL", 5)
    result = audit.Audit()
    result.inspect("fixture:1", b"1234")
    with pytest.raises(audit.AuditError, match="input-size-limit"):
        result.inspect("fixture:2", b"56")


def test_http_response_limits_and_method_without_network(monkeypatch):
    monkeypatch.setattr(audit, "MAX_INPUT", 4)
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    client = audit.GitHub("example/repo")

    def response(request, *, timeout):
        assert request.get_method() == "GET"
        assert request.full_url.startswith("https://api.github.com/repos/example/repo/")
        assert request.get_header("Authorization") == "Bearer synthetic-token"
        assert timeout == 15
        return io.BytesIO(b"too-long")

    monkeypatch.setattr(client.opener, "open", response)
    with pytest.raises(audit.AuditError, match="response-size-limit"):
        client.get("/releases", binary=True)
    client.requests = 100
    with pytest.raises(audit.AuditError, match="request-limit"):
        client.get("/releases")


@pytest.mark.parametrize(
    "repository",
    ["../repo", "owner/../repo", "https://example.invalid/repo", "owner/repo?secret=x"],
)
def test_repository_cannot_inject_a_url(repository):
    with pytest.raises(audit.AuditError, match="invalid-repository"):
        audit.GitHub(repository)


def test_api_failures_are_redacted(monkeypatch, capsys):
    def failed(*args):
        raise ValueError("synthetic-token signed-download-url private-body")

    monkeypatch.setattr(audit, "audit_github", failed)
    assert audit.main(["--repository", "example/repo", "--allow-network"]) == 2
    output = capsys.readouterr()
    assert "synthetic-token" not in output.out + output.err
    assert json.loads(output.out)["complete"] is False


def test_private_repository_is_not_scanned():
    class PrivateGitHub:
        def get(self, path):
            assert path == ""
            return {"private": True}

    with pytest.raises(audit.AuditError, match="repository-not-public"):
        audit.audit_github(audit.Audit(), PrivateGitHub(), 1)


def test_cli_findings_return_one_without_secret_values(tmp_path, capsys):
    path = tmp_path / "fixture.json"
    secret = "synthetic-" + "x" * 32
    path.write_text(json.dumps({"api_token": secret}))
    assert audit.main(["--file", str(path)]) == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert json.loads(output.out)["findings"] == [
        {"source": "file:1", "kind": "credential-shaped-value"}
    ]
