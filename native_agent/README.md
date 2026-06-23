# C300X Native Agent

Native C runtime for BTicino C300X. This directory contains the agent source,
local test harness, build scripts, and the example config.

## Build and Check

```bash
make -C native_agent
make -C native_agent check
make -C native_agent armhf armhf-abi-check
make -C native_agent armhf-stack-check
```

`armhf-abi-check` needs the C300X firmware sysroot via
`C300X_DEVICE_SYSROOT`. Public CI still compiles ARMHF and runs the stack
guard, but local release builds should run the ABI check against the real
device sysroot.

## Run Locally

```bash
cp native_agent/config.example.json native_agent/config.json
$EDITOR native_agent/config.json
native_agent/build/host/c300x-agent-native --config native_agent/config.json
```

Keep real configs and tokens untracked.

## Documentation

- Runtime, packaging, bootstrap, update, and security notes:
  [docs/native-agent.md](../docs/native-agent.md)
- HTTP endpoint contract and compatibility rules: [API.md](API.md)
- Device display QML files and safety rules:
  [device_qml/README.md](../device_qml/README.md)

Do not duplicate endpoint lists in this README. `API.md` is the single source
for the native-agent HTTP contract.
