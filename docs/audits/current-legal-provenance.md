# Current Legal and Provenance Audit Snapshot

Checked: 2026-11-02. Source line: local integration and native agent `1.9.11`,
based on `9fc3944` with the local audit changes. This report covers the
repository, not a newly published release.

This is a technical provenance and packaging review, not a legal opinion,
authorship proof, patent clearance, or a current vulnerability assessment.

## Verified Scope

The local `scripts/check_legal_audit.py` gate passed against 552 tracked files.
It checks forbidden payloads and directories, required license/privacy/security
documents, runtime dependency declarations, reference markers, and the expected
project artwork hash. It is a policy check, not a source-similarity detector.

The repository contains its Apache-2.0 `LICENSE`, project `NOTICE`, trademark
and non-affiliation notices, and a privacy notice. No tracked firmware images,
APKs, packet captures, device backups, or native library binaries were found by
the gate. Builds and device-specific inputs remain outside tracked source.

The prior 1.7.0 snapshot dated 2026-07-05 is superseded; its full text remains in
Git history. Its search results and release-artifact checks are not evidence for
the current code or a future release.

## Dependencies and Distribution

The integration manifest has no mandatory Python requirements. This does not
mean every optional workflow is dependency-free: the SSH installer explicitly
requests `paramiko==3.5.1` through Home Assistant's requirement installer when
that workflow is used. Normal agent operation does not require that installer.

PyAV and the Home Assistant media stack provide media processing. The native
agent uses system libraries supplied by its runtime, including optional device
libraries loaded at runtime. These dependencies are not copied into the source
repository and are not relicensed by the repository's Apache-2.0 declaration.

The development requirement files contain direct version pins, not complete
transitive lockfiles. An installed development environment is not authoritative
evidence of the dependencies on a user's Home Assistant or C300X.

Release SBOMs must distinguish packaged files from external runtime dependencies.
Unknown device-library versions must remain unknown rather than borrowing the
version installed on the build machine. A source/artifact attestation identifies
build provenance; it does not certify legal ownership or absence of vulnerabilities.

## Privacy and Accepted Risks

The legacy SSH installer and plaintext local transports have explicitly
documented limitations in `SECURITY.md`. They are not general security approval
for externally reachable deployments. No change to the accepted legacy SSH
compatibility policy was made by this audit.

`PRIVACY.md` describes the local data flow, bounded RAM-only media cache, Recorder
exclusions for new memo text entries, and the independent retention of old
history, exports, recordings, and backups.

## Not Verified Here

- No new internet source-similarity, trademark, patent, or advisory search.
- No legal clearance for third-party codecs, libraries, or trademarks.
- No device access, installation, firmware modification, or live load measurement.
- No final release ZIP, release signatures, or remote attestations checked.

## Repeatable Checks

Run `scripts/check_legal_audit.py` and `scripts/check_repo.py` from the repository
Python environment after source changes. For an actual release, rebuild and
validate the archive, checksums, SPDX document, and attestations for that exact
commit. Do not promote this source snapshot to release evidence without those
checks.
