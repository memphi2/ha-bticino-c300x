# C300X Native Agent

Native C runtime for the BTicino C300X. This directory holds the agent source
(`src/`), device scripts (`scripts/`), the local test harness (`test/`), the
Makefile and `config.example.json`.

## Build and Run

The build needs a C compiler, `pkg-config` and the libcurl development headers.
`make -C native_agent` builds the host binary under `build/host/`,
`make -C native_agent check` runs the tests, and the `armhf` targets build and
check the device binary. Prerequisites, `CURL_INCLUDE_DIR`, the ABI/stack
guards and a local run with an untracked config are described once in
[Native Agent: Build and Checks](../docs/dev/native-agent.md#build-and-checks).

Keep real configs and tokens untracked.

## Documentation

- Runtime, packaging, bootstrap, update and security notes:
  [docs/dev/native-agent.md](../docs/dev/native-agent.md)
- HTTP endpoint contract and compatibility rules: [API.md](API.md)
- Internal module ownership, workers and resource limits:
  [docs/dev/architecture.md](../docs/dev/architecture.md)
- Display QML files and safety rules:
  [device_qml/README.md](../device_qml/README.md)

`API.md` is the single source for the HTTP contract; do not copy endpoint lists
here.
