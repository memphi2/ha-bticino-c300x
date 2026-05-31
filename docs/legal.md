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

BTicino, Classe 300X, Legrand, Home Assistant, HACS, Nabu Casa, OpenAI, Codex
and other referenced names are trademarks or names of their respective owners.
They are used only for compatibility, attribution, and descriptive reference.

This project is not affiliated with, endorsed by, sponsored by, or certified by
BTicino, Legrand, Home Assistant, Nabu Casa, HACS, OpenAI, or the referenced
community projects.

## No firmware or APK payloads

The repository must not contain:

- BTicino/Legrand firmware images or extracted firmware trees.
- Android APKs or extracted app payloads.
- Local device backups.
- Runtime captures, packet captures, logs with private data, or local secrets.
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

## Repository gate

`scripts/check_repo.py` is the local and CI gate for this policy. It rejects
common firmware/archive payloads, foreign runtime directories, tracked stock QML
pages, private values, and third-party reference markers in runtime code.
