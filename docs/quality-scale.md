# Home Assistant Quality Scale

Reviewed: 2026-11-16

This is a **local self-assessment of a custom integration**, not an official
Home Assistant tier or certification. Platinum remains a development goal, not
an achieved rating. Open requirements exist at several tiers, including Bronze.
The [tracking file](../custom_components/bticino_c300x/quality_scale.yaml) records
all 54 currently published rules. The checker validates that tracking and this
audit agree; it cannot award a tier or prove implementation correctness.

## Sources and Evidence Limits

The official [overview](https://contributors.home-assistant.io/core/quality-scale/),
[rule list](https://contributors.home-assistant.io/core/quality-scale/rules/), and
[file format](https://contributors.home-assistant.io/core/quality-scale/quality-scale-file/)
were checked online on the review date. The current list has 20 Bronze, 10 Silver,
21 Gold and 3 Platinum rules, including `docs-conditions` and `docs-triggers`.
An exemption needs a specific reason; an honest TODO is not a validation failure.

Two coverage requirements must not be conflated:

- Bronze [config-flow-test-coverage](https://contributors.home-assistant.io/core/quality-scale/config-flow-test-coverage/)
  requires 100% of `config_flow.py`, including recovery from errors and entry
  unique-ID assertions. Extracting flow helpers does not remove the need to test
  their behavior.
- Silver [test-coverage](https://contributors.home-assistant.io/core/quality-scale/test-coverage/)
  requires **more than 95% in every integration module**, not an aggregate 95%
  score and not a separate Platinum threshold.

No full-suite coverage run was performed for this audit. Existing `.coverage`
files, earlier full runs and historical release reports are **not current-source
proof**. The local [coverage gate](../scripts/check_coverage.py) enforces an
aggregate 95% floor, not an official HA tier requirement. Both coverage rules
stay TODO pending a fresh per-module report after all concurrent reviews.
Code references below are inspection
evidence; test-module references identify existing checks or the place to add a
missing regression, not a claim that every referenced test ran today.

For this custom integration, documentation statuses refer to the repository's
user documentation. Core submission would additionally require corresponding
home-assistant.io documentation and review. Local brand files likewise do not
establish acceptance into the Home Assistant brands repository.

## Rule Audit

Module names below are relative to
[`custom_components/bticino_c300x`](../custom_components/bticino_c300x/);
test names are relative to [`tests`](../tests/). `todo` identifies a specific
rule mismatch or missing evidence, not necessarily a runtime defect.

| Rule | Tier | Status | Evidence / Remaining Work |
| --- | --- | --- | --- |
| `action-setup` | Bronze | done | `__init__.py:async_setup` registers `services.py:async_setup_services`; entry setup refreshes capability-gated actions. `test_init_runtime.py:test_async_setup_registers_frontend_services_and_websocket`, `test_services.py`. |
| `appropriate-polling` | Bronze | exempt | Device entities are non-polling; state arrives through `events.py` / `webhook.py`. Subscription renewal/backoff, HA agenda/statistics refresh and retention timers still exist; this is not a claim of no timers. `test_events.py`, `test_entity.py`. |
| `brands` | Bronze | todo | `brand/icon.png` and `brand/logo.png` exist locally. No accepted upstream brands submission is evidenced; establish that before core submission. Local asset checks in `scripts/check_repo.py` are not upstream acceptance. |
| `common-modules` | Bronze | done | Shared entity behavior is in `entity.py`, typed runtime state in `data.py` / `entry_types.py`; no polling coordinator is implemented under another name. `test_entity.py`, `test_runtime_data.py`. |
| `config-flow-test-coverage` | Bronze | todo | `test_config_flow_helpers.py`, `test_config_flow_forms.py`, optional-page/activation/energy tests and `test_schema_runtime.py` exercise many paths. No current 100% report or complete error-to-success/unique-ID audit is available. Re-measure the flow and extracted helpers after reviews. |
| `config-flow` | Bronze | done | Manifest enables the UI flow; `config_flow.py`, form helpers and `strings.json` provide setup, options, field help and reconfigure. `test_config_flow_helpers.py`, `test_translations.py`, `test_schema_runtime.py`. Separate validation/reauth rules are not implied. |
| `dependency-transparency` | Bronze | todo | `device_installer.py:INSTALLER_REQUIREMENTS` pins optional `asyncssh==2.24.1` despite empty manifest requirements. [Provenance audit](audits/current-legal-provenance.md) discloses it; `test_device_ssh.py` checks use. Record the exact dependency release tag and public build/publish workflow before claiming this rule. |
| `docs-actions` | Bronze | done | [Service reference](feature-reference.md#service-reference), [display notifications](feature-reference.md#display-notifications) and [blueprints](blueprints.md) describe commands and inputs. `services.yaml`, `test_services_metadata.py` provide the inventory. |
| `docs-conditions` | Bronze | exempt | No custom condition platform or `conditions.yaml` exists. HA state/template conditions in blueprints are built-ins, not a C300X condition API. See the official exception below. |
| `docs-high-level-description` | Bronze | done | [README](../README.md) and [user guide](user-guide.md) identify the Classe 300X, the unofficial integration and its purpose. |
| `docs-installation-instructions` | Bronze | done | [Quickstart](quickstart.md) covers prerequisites, Marketplace/HACS, address entry, explicit bootstrap installation and first-use checks. Field completeness is separate below. |
| `docs-removal-instructions` | Bronze | done | [HA removal guide](advanced-maintenance.md#remove-home-assistant-integration) separates entry/package/device removal and explains retained media, config and backups; Quickstart links it. Official HA/HACS steps checked 2026-11-16; `test_user_documentation.py` guards scope/warnings and links, `test_init_runtime.py` / `test_runtime_data.py` cover cleanup behavior. |
| `docs-triggers` | Bronze | exempt | No custom trigger platform or `triggers.yaml` exists. `event.py` and bundled blueprints use standard event/state triggers; [blueprints](blueprints.md) explains those workflows. See the official exception below. |
| `entity-event-setup` | Bronze | done | `C300XEntity.async_added_to_hass` and platform callbacks register listeners with `async_on_remove`; reconnect work is cancelled on removal. `test_entity.py`, `test_event_entity.py`, `test_binary_sensor.py`. |
| `entity-unique-id` | Bronze | done | `entity.py:entry_entity_unique_id` combines the persistent config-entry ID with each entity key. Activation keys include their configured activation ID. `test_entity.py`, `test_button.py`, `test_event_entity.py`. |
| `has-entity-name` | Bronze | done | `C300XEntity._attr_has_entity_name = True` is inherited by entity platforms. `test_entity.py` and platform tests inspect the entity contract. |
| `runtime-data` | Bronze | done | `entry_types.py` defines the typed entry; `runtime_manager.py` stores `data.py:C300XRuntimeData` on `entry.runtime_data`. Domain service lookup also has an explicit runtime index. `test_runtime_data.py`, `test_init_runtime.py`. |
| `test-before-configure` | Bronze | done | `config_flow_auth.py` validates authenticated reads for manual/discovered setup, installer skip, reconfigure, connection options and final persistence. `test_config_flow_auth.py` rejects invalid access/maintenance keys and offline responses without saving; `test_config_flow_helpers.py` retains bootstrap guards. Focused checks pass on HA 2026.10.0 and 2026.11.1. |
| `test-before-setup` | Bronze | todo | `runtime_manager.py:async_validate_agent` raises `ConfigEntryAuthFailed` on credential rejection. Existing entries deliberately still load unavailable while offline and recover later rather than raising `ConfigEntryNotReady`; the strict HA setup contract therefore remains unresolved. `test_runtime_auth.py` and `test_init_runtime.py` cover this separation, offline-to-auth recovery and cancellation on HA 2026.10.0 and 2026.11.1. |
| `unique-config-entry` | Bronze | done | `config_flow.py` checks stable identity and host/port matches before bootstrap and entry creation, and aborts competing discovery flows. `test_config_flow_helpers.py` duplicate/identity cases and `test_discovery.py`. |
| `action-exceptions` | Silver | done | `use_cases/common.py` and entity actions map API failures to HA exceptions; notification validation uses `ServiceValidationError`. `test_entity_action_errors.py`, `test_services.py`, `test_alarm_service_results.py`. Translation completeness is separate. |
| `config-entry-unloading` | Silver | done | `__init__.py:async_unload_entry`, runtime resource cleanup and Notify teardown release callbacks/tasks. `test_runtime_data.py`, `test_webhook_runtime_lifecycle.py`, `test_init_runtime.py`. |
| `docs-configuration-parameters` | Silver | done | [Feature reference](feature-reference.md#setup-and-options) and form help cover settings areas; the linked [ICE reference](media-troubleshooting.md#connection-paths-for-the-live-picture) now explains all four choices, default, directional scope and exceptions. `test_user_documentation.py` compares the table with the filter and selector values; `test_config_flow_helpers.py` covers the field contract. |
| `docs-installation-parameters` | Silver | done | [Quickstart](quickstart.md) covers setup and one-time SSH inputs and now links the same ICE reference, including that no address/token is needed for this selector. `test_user_documentation.py` checks discoverability/default; `test_config_flow_helpers.py` covers setup choices. |
| `entity-unavailable` | Silver | done | `entity.py:available` follows shared connection state after grace; failed command reads also clear availability. Connection-diagnostic sensors intentionally remain readable. `test_entity.py`, `test_connection_state.py`, `test_switch.py`, `test_number.py`. |
| `integration-owner` | Silver | done | `manifest.json` now lists `@memphi2`, matching the maintainer of the linked public source and issue repository. This is ownership metadata, not an awarded tier. |
| `log-when-unavailable` | Silver | done | `events.py` emits one registration warning per outage and one recovery log, retaining registration-specific state across rediscovery. `test_event_registration_auth.py`, `test_event_registration_races.py`, `test_events.py` and `test_connection_state.py` cover retries, callbacks, recovery, repeated outages and teardown on HA 2026.10.0 and 2026.11.1. Optional diagnostics failures do not become registration outages. |
| `parallel-updates` | Silver | done | Entity platforms declare `PARALLEL_UPDATES` (0 for push-only event/binary-sensor/camera, 1 for command/read platforms); commands also use `entry_locks.py`. `notify.py` is a legacy service, not an entity polling platform. Platform tests and `test_entity_action_errors.py`. |
| `reauthentication-flow` | Silver | done | `config_flow_auth.py` implements entry-bound reauth with validated keys, identity checks, token override cleanup and one reload. `runtime_auth.py` starts recovery for runtime rejection; startup raises `ConfigEntryAuthFailed`. `test_config_flow_auth.py`, `test_runtime_auth.py` and `test_event_registration_auth.py` cover failure/success and the installed HA deduplication API on HA 2026.10.0 and 2026.11.1. One-time SSH bootstrap remains separate. |
| `test-coverage` | Silver | todo | Fresh per-module >95% evidence is pending; aggregate `scripts/check_coverage.py` and old reports cannot establish it. Run the final suite with coverage after reviews and inspect every module, not just the total. |
| `devices` | Gold | done | `entity.py:_device_info` groups one C300X per entry with manufacturer, model, name and firmware when available. `test_entity.py` and platform tests. |
| `diagnostics` | Gold | done | `diagnostics.py` supplies entry/runtime diagnostics with explicit redaction, including unloaded/offline paths. `test_diagnostics.py` exercises secrets, hostnames, IPv6 and error redaction. |
| `discovery-update-info` | Gold | todo | `config_flow.py:async_step_zeroconf` calls `_abort_if_unique_id_configured()` without address updates. Untrusted mDNS must not redirect stored credentials. Same-endpoint discovery can renew registration/adopt identity, not change host/port. `test_config_flow_helpers.py` discovery/security cases preserve this guard. A securely verified address-change workflow is absent; retain manual reconfigure rather than weaken security for compliance. |
| `discovery` | Gold | done | Manifest advertises the agent mDNS service; `discovery.py` validates identity/address. Advertising is intentionally disabled after registration. `test_discovery.py`, `test_native_mdns_runtime.py`. Address updates are a separate rule. |
| `docs-data-update` | Gold | done | [Operating model](feature-reference.md#operating-model), [architecture](architecture.md#data-flow), agenda and energy sections explain device push, HA-side refresh and explicit reads/writes. |
| `docs-examples` | Gold | done | [Blueprints](blueprints.md) and bundled automation examples cover ring, notifications and phrase decisions. `test_blueprint_installer.py` checks installation handling. |
| `docs-known-limitations` | Gold | done | [Feature reference](feature-reference.md), [media troubleshooting](media-troubleshooting.md) and [readiness](media-readiness.md) distinguish unsupported capabilities, media prerequisites and transport limitations. |
| `docs-supported-devices` | Gold | done | [README requirements](../README.md#requirements) and [quickstart prerequisites](quickstart.md#before-you-start) restrict support to the C300X family/firmware context and require SSH/root for bootstrap; no generic BTicino support claim. |
| `docs-supported-functions` | Gold | done | [Feature reference](feature-reference.md#main-user-features), entity/service tables and display-page sections describe functionality and gates. |
| `docs-troubleshooting` | Gold | done | [Media troubleshooting](media-troubleshooting.md), [readiness](media-readiness.md) and [advanced maintenance](advanced-maintenance.md) provide concrete diagnostic and recovery steps. |
| `docs-use-cases` | Gold | done | [User guide](user-guide.md#common-tasks), [quickstart](quickstart.md) and [blueprints](blueprints.md) explain practical ring/camera/automation workflows. |
| `dynamic-devices` | Gold | exempt | Each entry represents one physical C300X; activations are entities on it, not discovered child devices. `entity.py:_device_info`, `test_button.py`. |
| `entity-category` | Gold | done | Configuration/maintenance entities set CONFIG and diagnostic sensors/events set DIAGNOSTIC; normal controls remain primary. `sensor.py`, `switch.py`, `button.py` and platform tests. |
| `entity-device-class` | Gold | done | Doorbell events use DOORBELL, discrete status sensors ENUM, metrics relevant units/classes; arbitrary call-state enums are not forced into an unrelated class. `event.py`, `sensor.py`, `test_event_entity.py`, `test_sensor.py`. |
| `entity-disabled-by-default` | Gold | done | Diagnostic/transient helpers and destructive/advanced maintenance controls opt out by default; primary event/control entities remain enabled. `sensor.py`, `switch.py`, `select.py`, `button.py` and platform tests. |
| `entity-translations` | Gold | done | Fixed names use translation keys in `strings.json` / locale files; activation labels are user-supplied. `test_translations.py` covers locale key/placeholder parity and state/option labels. |
| `exception-translations` | Gold | todo | `exceptions.py` supplies translated helpers, but notification handlers in `services.py` use `ServiceValidationError(str(err))`, and `ring_ai.py` has plain-text HA errors. Extend `test_services.py`, `test_ring_ai.py`, `test_translations.py` before claiming completeness. |
| `icon-translations` | Gold | todo | `icons.json` covers many entities, but `camera.py` hardcodes `_attr_icon = "mdi:cctv"`; activation buttons select Python icons. Audit/migrate remaining overrides or document a supported exception; extend `test_camera.py`, `test_button.py`, `test_translations.py`. |
| `reconfiguration-flow` | Gold | done | `config_flow.py:async_step_reconfigure` and substeps preserve entry identity and clear stale option overrides. `test_config_flow_helpers.py`, activation/optional-page flow tests. This does not substitute for reauthentication. |
| `repair-issues` | Gold | done | `repair_issues.py`, `repairs.py` and extracted repair flows expose actionable issues/fixes; removal clears entry issues. `test_repair_issues.py`, `test_agent_update_repairs.py`, `test_frontend_repairs.py`. |
| `stale-devices` | Gold | exempt | One physical device per entry, no independent child-device lifecycle. Removing the entry removes the device. Stale entity cleanup is separate in `runtime_manager.py`, covered by `test_init_runtime.py`. |
| `async-dependency` | Platinum | todo | `_api_core.py` uses async aiohttp; optional SSH uses AsyncSSH, not WebRTC packages. However `device_installer.py:async_install_device_agent` uses `asyncio.to_thread` around a synchronous facade/private `asyncio.Runner`. Resolve that path's conformance to the HA-event-loop requirement; `test_device_ssh.py` / `test_device_installer.py` show current behavior, not a blocking-HA-loop finding. |
| `inject-websession` | Platinum | done | `runtime_manager.py`, `config_flow.py` and `mqtt_migration.py` pass `async_get_clientsession(hass)` into `C300XAgentApi`; no private aiohttp session is constructed. `test_api.py`, `test_init_runtime.py`. SSH/raw sockets are not HTTP-session consumers. |
| `strict-typing` | Platinum | todo | `scripts/check_typing.py` uses strict mode for explicit targets but follows other imports silently; `runtime_manager.py`, `_api_core.py` and several extracted helpers are not targets. Audit the complete module inventory/dependency typing, then run the expanded gate. Runtime tests cannot substitute for this proof. |

## Rule-Specific Sources

- New rules permit exemptions without a corresponding custom API:
  [conditions](https://contributors.home-assistant.io/core/quality-scale/docs-conditions/)
  and [triggers](https://contributors.home-assistant.io/core/quality-scale/docs-triggers/).
- Connection checks: [before configuration](https://contributors.home-assistant.io/core/quality-scale/test-before-configure/)
  and [before setup](https://contributors.home-assistant.io/core/quality-scale/test-before-setup/).
  The latter discusses intentionally offline devices; authentication failures
  still need explicit handling. This audit does not authorize changing the
  offline-first design without a separate decision.
- Reliability: [transition logging](https://contributors.home-assistant.io/core/quality-scale/log-when-unavailable/),
  [reauthentication](https://contributors.home-assistant.io/core/quality-scale/reauthentication-flow/),
  [ownership](https://contributors.home-assistant.io/core/quality-scale/integration-owner/)
  and [discovery updates](https://contributors.home-assistant.io/core/quality-scale/discovery-update-info/).
  The discovery rule is not a justification to trust unauthenticated mDNS.
- Documentation: [options](https://contributors.home-assistant.io/core/quality-scale/docs-configuration-parameters/)
  and [setup fields](https://contributors.home-assistant.io/core/quality-scale/docs-installation-parameters/).
- Technical requirements: [dependency provenance](https://contributors.home-assistant.io/core/quality-scale/dependency-transparency/),
  [async dependencies](https://contributors.home-assistant.io/core/quality-scale/async-dependency/),
  [icon translations](https://contributors.home-assistant.io/core/quality-scale/icon-translations/)
  and [strict typing](https://contributors.home-assistant.io/core/quality-scale/strict-typing/).

## Validation

Focused tracking checks (no device, network or full suite):

```bash
.venv/bin/python scripts/check_quality_scale.py
.venv/bin/python -m pytest tests/test_quality_scale.py
.venv/bin/ruff check scripts/check_quality_scale.py tests/test_quality_scale.py
```

The checker uses safe YAML parsing, rejects duplicate keys, malformed structures,
unknown rules/statuses and unexplained exemptions, and cross-checks every audit
row's status/tier. It accepts new documented TODOs; the earlier two-item blocker
list is not a permanent gate.

Only after all reviews and fixes, run the repository's full validation and fresh
coverage/typing gates. Record source revision, HA/Python versions and per-module
results then. Device/HA activation or live smoke testing requires separate
authorization; this document is not that authorization.
