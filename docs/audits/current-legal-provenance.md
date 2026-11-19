# Current Legal and Provenance Audit Snapshot

Source review: 2026-11-19. Integration and native agent `2.5.1`, a maintenance
release that adds C300X firmware `2.0.2` to `2.5.0`. Version `2.5.0` is the successor
to `v2.4.1`, adding optional Agenda and Leave home pages, live Consumers,
page navigation and bounded display notifications. This report covers the local source tree, not a newly published
release.

This is a technical provenance and packaging review, not a legal opinion,
authorship proof, patent clearance, or a current vulnerability assessment.

## Verified Scope

The local `scripts/check_legal_audit.py` source-policy gate checks forbidden
payloads and directories, required license/privacy/security
documents, runtime dependency declarations, reference markers, and the expected
project artwork hash. It is a policy check, not a source-similarity detector.

The repository contains its Apache-2.0 `LICENSE`, project `NOTICE`, trademark
and non-affiliation notices, and a privacy notice. No tracked firmware images,
APKs, packet captures, device backups, or native library binaries were found by
the gate. Builds and device-specific inputs remain outside tracked source.

The prior audit dated 2026-11-08 is superseded; its full text remains in
Git history. Its search results and release-artifact checks are not evidence for
the current code or a future release.

## Dependencies and Distribution

The integration manifest has no mandatory Python requirements. This does not
mean every optional workflow is dependency-free: the SSH installer explicitly
requests `asyncssh==2.24.1` through Home Assistant on demand;
Paramiko has been removed from project imports and validation pins. AsyncSSH is
an external dependency under its own license, not bundled or relicensed by this
project. Normal agent operation and supported self-updates do not use SSH.

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
for externally reachable deployments. The 2026-11-07 installer follow-up records
the remaining device-protocol exception as `LEGACY-SSH-001`; changing the client
does not eliminate the legacy cryptography or host-identity limitation.

`PRIVACY.md` describes the local data flow, bounded RAM-only media cache, Recorder
exclusions for new memo text entries, and the independent retention of old
history, exports, recordings, and backups.

Visitor images are enabled by default and stored in HA's configured media
directory. The agent reads an active framebuffer without creating device files.
The integration endpoint checks camera read permission, but HA's standard local
media browser applies its own access rules. Camera restrictions alone do not
protect that archive. Retention and storage limits are documented separately
from backup retention.

Agenda reads only explicitly selected HA calendars into bounded HA RAM caches.
Leave home exposes explicitly selected contacts, lights and actions. Notify
messages are retained in the existing HA notice store; the device keeps the
active alert in RAM, with no queue for a disconnected display. Wake and sound
are supplementary notifications, not certified life-safety alarm functions.
The retired Distribution source is removed on update; the package-only inert
bootstrap file preserves compatibility with the previous updater and is not
part of the new active GUI.

The English display examples are edited from maintainer-provided photographs,
with AI-assisted perspective correction, color matching and localization.
`display-energy-en.webp` instead comes from a read-only screen capture on the
maintainer's C300X on 2026-11-15, before its 2.4.1 update. Its layout and values
were retained, with English labels and colors matched to the other examples.
These are illustrative documentation assets, not extracted firmware files or
pixel-exact runtime captures.

## Not Verified Here

- No new internet source-similarity, trademark, patent, or advisory search.
- No legal clearance for third-party codecs, libraries, or trademarks.
- No device installation, firmware modification, or live load measurement in
  this review. Earlier device tests do not validate this release candidate.
- No final release ZIP, release signatures, or remote attestations checked.

## Repeatable Checks

Run `scripts/check_legal_audit.py` and `scripts/check_repo.py` from the repository
Python environment after source changes. For an actual release, rebuild and
validate the archive, checksums, SPDX document, and attestations for that exact
commit. Do not promote this source snapshot to release evidence without those
checks.
