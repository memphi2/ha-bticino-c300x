# BTicino Classe 300X and Classe 100X for Home Assistant (Unofficial)

[![Validate](https://img.shields.io/badge/checks-local%20%2B%20CI-2ea44f?style=flat-square)](.github/workflows/validate.yml)
[![Quality](https://img.shields.io/badge/HA%20Quality%20Scale-Self%20assessment-0366d6?style=flat-square)](docs/dev/quality-scale.md)
[![Release](https://img.shields.io/badge/release-v3.0.0-0366d6?style=flat-square)](CHANGELOG.md)
[![Marketplace](https://img.shields.io/badge/Home_Assistant-Marketplace-41BDF5?style=flat-square)](https://contributors.home-assistant.io/marketplace/)
[![License Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

Connects a BTicino Classe 300X or Classe 100X video door station to Home
Assistant over your local network. A small agent on the station talks to Home
Assistant; nothing goes through a cloud. The integration is called
**BTicino C300X/C100X** for both models.

Stable: **3.0.0**, one package for the Classe 300X and the Classe 100X
(Classe 100X experimental). Beta: **3.1.0b1**, every outdoor unit as its own
device ([changelog](CHANGELOG.md)).

<p align="center">
  <img src="docs/images/readme/ha-doorbell-card-en.webp" alt="BTicino Doorbell Call Card in Home Assistant with a saved visitor image, play, call, door and light buttons" width="420">
</p>

## Which Device Do I Have?

| Model | Firmware | Status |
| --- | --- | --- |
| Classe 300X (C300X, `344642` or `344643`) | `1.7.x`, `2.0.2`, `3.0.6` | Supported. Every release is tested on `1.7.19`; on `2.0.2` and `3.0.6` most of it is checked offline only. |
| Classe 100X (C100X) | `1.5.8` | Experimental, in test in [issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51). |
| Classe 300X2 (C3X2) | `1.2.x` | Not supported yet. Setup recognises it and installs nothing on it. |

You need:

- Home Assistant `2026.10.0` or newer.
- Home Assistant and the station in a trusted local network.
- SSH access on the station
  ([Classe 300X](docs/classe-300x/1-setup.md#enable-ssh-on-the-station),
  [Classe 100X](docs/classe-100x/1-setup.md#enable-ssh-on-the-station)).

## Start Here

The guide has five steps per model. Read them in order; every page ends with
a link to the next step.

| Step | Classe 300X | Classe 100X |
| --- | --- | --- |
| 1 | **[Setup](docs/classe-300x/1-setup.md)** | **[Setup](docs/classe-100x/1-setup.md)** |
| 2 | [Use](docs/classe-300x/2-use.md) | [Use](docs/classe-100x/2-use.md) |
| 3 | [Station display](docs/classe-300x/3-display.md) | [Station display](docs/classe-100x/3-display.md) |
| 4 | [Troubleshooting](docs/classe-300x/4-troubleshooting.md) | [Troubleshooting](docs/classe-100x/4-troubleshooting.md) |
| 5 | [Update and removal](docs/classe-300x/5-update-and-removal.md) | [Update and removal](docs/classe-100x/5-update-and-removal.md) |

## Features

- Live video, ring calls and talking to the door in one card.
- Every outdoor unit as its own device, with its ring, door, call state and
  last visitor.
- Door unlock, stair light and extra locks or actuators as buttons, also those
  the station is set up with.
- One saved image of every visitor.
- Home Assistant pages on the station's own display: lights, covers, climate,
  energy, calendars, Alarmo and more.
- Notices on the station display; on the Classe 300X also spoken by the
  station.
- Blueprints for phone alerts, ring recordings and calendar reminders.

What each model can do: [Models and features](docs/reference.md#models-and-features).

### On the Station Display

<p align="center">
  <img src="docs/images/readme/display-energy-flow-en.webp" alt="Classe 300X display, Energy page: power flow between grid, solar, battery and home" width="260">
  <img src="docs/images/readme/display-alarmo-en.webp" alt="Classe 300X display, Alarm page: Alarmo with Away and Night modes and a PIN keypad" width="260">
  <img src="docs/images/readme/display-lights-en.webp" alt="Classe 300X display, Lights page: eight lights with on/off switches and brightness" width="260">
</p>

All display pages: [Classe 300X](docs/classe-300x/3-display.md) |
[Classe 100X](docs/classe-100x/3-display.md).

## More

[Reference](docs/reference.md) | [Support](SUPPORT.md) |
[Security](SECURITY.md) | [Privacy](PRIVACY.md) | [Legal](docs/legal.md) |
[Changelog](CHANGELOG.md) | [Developer docs](docs/dev/architecture.md)

## Status and Legal

Independent community project, not affiliated with, endorsed or certified by
BTicino, Legrand, Home Assistant, Nabu Casa or HACS. It ships no firmware,
APKs or vendor files and does not root a station. Use it at your own risk and
without warranty. License: Apache-2.0. Developed with AI assistance, including
Codex and Claude. Quality scale: a
[self-assessment](docs/dev/quality-scale.md), not an awarded tier.

### Support the Test Device

Every release is tested on one Classe 300X with firmware `1.7.19`. A
contribution towards a second unit, or a used or defective Classe 300X
(`344642` or `344643`), is welcome in a
[discussion](https://github.com/memphi2/ha-bticino-c300x/discussions/new?category=general).
It is voluntary; support and features stay open to everyone.

<p align="center">
  <a href="https://ko-fi.com/oliver7557"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support me on Ko-fi"></a>
</p>
