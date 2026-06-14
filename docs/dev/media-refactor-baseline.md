# Media Refactor Baseline

This document records the baseline for the media refactor work on branch
`1.2.0`. It is intentionally factual and does not define new behavior.

## Scope Guard

Allowed work:

- Refactor `camera.py` and media orchestration.
- Add testable media state and RTSP admission policy modules.
- Analyze, model, test, and implement RTSP client handling.

Out of scope for this refactor:

- Public Home Assistant service redesign.
- Security changes.
- Unlock or phrase-match changes.
- `evaluate_ring_analysis` behavior changes.
- Frontend card type or entity unique ID changes.

## Current Public Surface

These values are regression anchors and must remain stable unless an explicit
breaking change is approved:

- Domain: `bticino_c300x`
- Camera entity class: `C300XDoorbellCamera`
- Doorbell card type: `custom:c300x-doorbell-call-card`
- Home Call websocket commands:
  - `bticino_c300x/home_call/webrtc/get_client_config`
  - `bticino_c300x/home_call/webrtc/offer`
  - `bticino_c300x/home_call/webrtc/candidate`
- Public media services:
  - `activate_doorbell_video`
  - `stop_doorbell_video`
  - `answer_doorbell_call`
  - `hangup_doorbell_call`
  - `capture_doorbell_call`
  - `run_ring_wyoming_analysis`
  - `evaluate_ring_analysis`
  - `start_home_call`
  - `stop_home_call`

The refactor must not change service names, entity unique IDs, config-flow data,
or frontend card tags.

## `camera.py` Responsibilities

Baseline size:

- `custom_components/bticino_c300x/camera.py`: 1994 lines
- `tests/test_camera.py`: 2041 lines

Observed responsibility clusters in `camera.py`:

- Home Assistant camera setup and entity properties.
- Native WebRTC offer handling.
- ICE candidate parsing, buffering, and flushing.
- WebRTC session lifecycle and cleanup.
- RTSP stream URL preparation, probing, cooldown, warmup, restart and backoff.
- Restarting RTSP audio/video tracks.
- Ring preview, ring answer and ring cleanup handling.
- Home Call start, active wait, audio-only stream handling and cleanup.
- Browser microphone talkback encoding to Speex/8 kHz RTP.
- SDP audio-section parsing and direction decisions.
- Status derivation from agent video/home-call status and push events.
- Link-local ICE candidate filtering.

These clusters justify extracting focused media modules in small behavior
preserving steps.

## Existing Test Anchors

Important existing tests:

- `tests/test_camera.py`
  - camera entity attributes and WebRTC entry points
  - ICE candidate buffering and flushing
  - SDP audio direction decisions
  - Home Call audio-only WebRTC flow
  - talkback RTP packet/audio forwarding behavior
  - RTSP restart track behavior
  - agent event handling and cleanup
- `tests/test_native_agent_ring_call.py`
  - native ring, on-demand and Home Call media protocol invariants
- `tests/test_reference_pcap_fingerprints.py`
  - anonymized reference media fingerprint invariants
- `tests/test_services.py` and `tests/test_services_metadata.py`
  - service registration and schema regression surface

## Baseline Validation

Commands run before functional refactoring:

```bash
.venv/bin/python scripts/check_repo.py
.venv/bin/python scripts/check_quality_scale.py
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_coverage.py
.venv/bin/python scripts/check_typing.py
```

Baseline result after commit `84fc2b2`:

- `check_repo.py`: passed
- `check_quality_scale.py`: passed
- `ruff check .`: passed
- `pytest`: passed
- `check_coverage.py`: passed, total coverage 76.84%
- `check_typing.py`: passed

## PCAP / Network Evidence Policy

Raw PCAP files are not repository artifacts.

Allowed repository artifacts:

- synthetic JSON/Markdown contract summaries
- parser and comparison methodology
- tests that assert reference facts without IPs, tokens, authorization headers,
  Call-IDs, SIP branches, or crypto keys

Committed fixtures are synthetic contract fixtures. Real PCAP-derived
fingerprints are local evidence only and must not be committed. Current
synthetic fixtures live in:

- `tests/fixtures/c300x_pcap_fingerprints/reference_ring_call.json`
- `tests/fixtures/c300x_pcap_fingerprints/reference_on_demand.json`
- `tests/fixtures/c300x_pcap_fingerprints/reference_home_call.json`

The extractor lives in:

- `scripts/extract_pcap_fingerprint.py`

Any future RTSP or media behavior change must either use the methodology or
state why no PCAP evidence is available for that local unit-level change.

## Refactor Round Result

Completed media modules:

- `camera_media/sdp.py`
- `camera_media/talkback.py`
- `camera_media/rtsp_reader.py`
- `camera_media/rtsp_policy.py`
- `camera_media/webrtc_session.py`
- `camera_media/state_machine.py`
- `camera_media/home_call_ws.py`
- `camera_media/rtsp_url.py`

Final size after the scoped refactor and follow-up hardening:

- `custom_components/bticino_c300x/camera.py`: 1311 lines

Behavior-preserving boundaries:

- Public service names and schemas unchanged.
- Doorbell card custom element name unchanged.
- Home Call websocket command names unchanged.
- Entity unique IDs unchanged.
- Raw PCAPs remain outside the repository.
- RTSP sharing is modeled by policy, but no unproven multi-client sharing is
  invented by this refactor.

Final validation commands:

```bash
.venv/bin/python scripts/check_repo.py
.venv/bin/python scripts/check_quality_scale.py
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_coverage.py
.venv/bin/python scripts/check_typing.py
```

Final result:

- `check_repo.py`: passed
- `check_quality_scale.py`: passed
- `ruff check .`: passed
- `pytest`: passed
- `check_coverage.py`: passed, total coverage 85.59%
- `check_typing.py`: passed
- `make -C native_agent check`: passed
- `make -C native_agent smoke`: passed
- `make -C native_agent armhf-abi-check`: passed
