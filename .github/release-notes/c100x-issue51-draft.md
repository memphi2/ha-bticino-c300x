# C100X 1.5.8 Complete Test ZIP: Issue Attachment Draft

**For the agreed issue #51 test only. No tag, release or HACS publication.**
This is not a C300X stable update or the firmware-3.0.6 beta. Use a separate HA
test instance: the integration domain is shared and cannot coexist as a second
version on a production HA instance.

The attachment contains the complete HA integration, freshly built ARM agent,
all generated device assets and current Lovelace card modules. "Agent-only"
describes the initial hardware test, not the ZIP contents. Before posting this
draft, add the final source commit, ZIP filename, SHA256 and successful full-gate/
browser results. The user uploads that exact ZIP directly to issue #51.

This first test covers C100X agent installation/startup, authenticated status,
identity and discovery, while preserving the official app's provisioned accounts
and existing Companion configuration. Routing/media changes and MQTT migration
are not part of first-test acceptance.

- Complete-file identity checks protect routing restoration; C100X restoration
  skips the unsupported C300X GUI-label operation.
- Removal verifies agent termination before restoration, retains startup recovery
  through cleanup, and leaves startup disabled if partial deletion changes the
  agent tree. Failed removal never schedules a reboot; external recovery remains
  necessary for already deleted files and unknown pre-test modifications.
- C100X-only package guards reject C300X targets before supported HA uploads or
  SSH writes, including missing/invalid manifest cases. The new native updater
  adds its own check; old updaters do not.
- The bundled card registers locally with content-hashed resource URLs. Missing
  or unavailable media cannot start a stream or request the microphone. The
  first test does not authorize media, Home Call or door/light actions.
- Additional display pages, key navigation, silent/wake Notify and read-only
  text memos are implemented offline but **not enabled in this test**.
- GUI activation/restart, ringer mute and key tone remain unavailable. Notify
  sound, voice/mutating memo operations and TTS are not advertised as supported.

Offline tests and original-firmware compilation are not device validation.
Supervised GUI startup/readiness/runtime rollback remain unfinished. This build
does not claim stable operation, successful hardware recovery or full C100X parity.

Read the [installation, recovery and test checklist](../../docs/c100x-test-release.md)
before any separately authorized installation. Keep the approved artifact hash
and exact pre-test recovery files. Do not force unsupported toggles, replace
provisioned SIP accounts, or remove recovery backups after an error.

Delivery checklist: verify the final commit, complete gate and artifact checksum;
attach the complete ZIP; post the detailed manual HA/card installation, private
backup, rollback and diagnostics instructions from the linked checklist. Retain
the public-release block. No device installation or hardware validation is implied.
