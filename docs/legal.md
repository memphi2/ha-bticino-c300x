# Legal and Asset Hygiene

This repository is an independent community project for local Home Assistant
use with compatible BTicino Classe 300X / C300X devices.

## License

The project code and project documentation are released under the Apache
License, Version 2.0. See [../LICENSE](../LICENSE) and [../NOTICE](../NOTICE).

The Apache License, Version 2.0 applies only to files that are part of this
repository. It does not grant rights to BTicino/Legrand firmware, assets,
applications, protocols, trademarks, or third-party projects.

## Trademark notice

BTicino, Classe 300X, Legrand, Home Assistant, HACS, Nabu Casa, OpenAI, Codex,
Anthropic, Claude and other referenced names are trademarks or names of their
respective owners.
They are used only for compatibility, attribution, and descriptive reference.

This project is not affiliated with, endorsed by, sponsored by, or certified by
BTicino, Legrand, Home Assistant, Nabu Casa, HACS, OpenAI, or the referenced
community projects.

## Project-owned assets

The integration brand images under
`custom_components/bticino_c300x/brand/` are project-owned generic artwork. They
use a simple house, display, and network-node motif to describe the integration
concept. They are not BTicino, Legrand, Home Assistant, HACS, Nabu Casa, or
third-party logos, and they are not copied from firmware, APKs, product images,
or controller repositories.

`icon.png` and `logo.png` currently contain the same 256x256 PNG artwork. Their
SHA-256 hash is:

```text
cd64c8c333ae2cfde2f32a8681054c1a5755a2edafadec1183501cd774088834
```

## No firmware or APK payloads

The repository must not contain:

- BTicino/Legrand firmware images or extracted firmware trees.
- Android APKs or extracted mobile-application payloads.
- Local device backups.
- Runtime artifacts, network traces, logs with private data, or local secrets.
- Generated native build artifacts except the explicit release-bundle agent
  payload under `custom_components/bticino_c300x/device_agent/`.

The root/firmware-patching topic is intentionally external. Users with stock
devices need a separate legal rooting or SSH-enablement workflow before this
integration can install the native agent.

## No vendored third-party controller code

The project acknowledges and builds on public community research, especially
SlyOldFox's `c300x-controller`, but it must not vendor or copy third-party
controller source trees into this repository.

Thanks to SlyOldFox for the public C300X groundwork and original community
controller work.

Third-party project references belong in documentation, tests, or issue
discussion. Runtime code should stay project-owned and should not embed copied
controller implementation files.

## Media codecs and patents

The C300X media path transports device-provided media through the user's local
Home Assistant runtime/browser media stack. The project does not ship codec
binaries, FFmpeg binaries, OpenH264/x264 binaries, or copied codec
implementation source code.

The Apache-2.0 license for this repository does not grant any third-party codec
patent licenses. Users and distributors are responsible for codec availability
and any jurisdiction-specific patent or licensing requirements.

## Repository gate

`scripts/check_repo.py` is the local and CI gate for this policy. It rejects
common firmware/archive payloads, foreign runtime directories, tracked stock QML
pages, private values, and third-party reference markers in runtime code.

The current local provenance evidence is retained under
[docs/audits/current-legal-provenance.md](audits/current-legal-provenance.md).
That file is a technical audit snapshot, not a live legal opinion.
