"""Execute the actual QML command handler with simulated Qt boundaries."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_qml_ringer_uses_stock_state_calls_and_rejects_expired_commands() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const handler = source.slice(source.indexOf('    function waitForCommand'), source.indexOf('\n    Timer {'));
let requests = [], operations = [], reconnects = 0, mute = true;
class Request {
    static DONE = 4;
    open(method, url, async) { this.url = url; assert.equal(method, 'GET'); assert.equal(async, true); }
    setRequestHeader(name, value) { assert.equal(name, 'X-C300X-GUI'); assert.equal(value, 'ringer-v1'); }
    send() { requests.push(this); }
    reply(data, status = 200) {
        this.status = status;
        this.responseText = JSON.stringify(data);
        this.readyState = Request.DONE;
        this.onreadystatechange();
    }
}
const audioState = {
    enableState(state) { assert.equal(state, 4); mute = true; operations.push('enable'); },
    disableState(state) { assert.equal(state, 4); mute = false; operations.push('disable'); },
    isStateEnabled(state) { assert.equal(state, 4); return mute; }
};
const context = vm.createContext({pendingRequest: null, stopped: false, XMLHttpRequest: Request,
    global: {audioState}, AudioState: {RingtoneMute: 4}, reconnect: {start() { reconnects++; }}});
vm.runInContext(handler, context);
context.waitForCommand();
context.waitForCommand();
assert.equal(requests.length, 1); // One sleeping request, not duplicate polling.
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.equal(requests[0].url, 'http://127.0.0.1:' + config.listen.uiPort + '/ui/ringer/next');
function command(muted, overrides = {}) {
    return Object.assign({ok: true, id: 'a'.repeat(32), muted, expires: Date.now() + 5000}, overrides);
}
requests[0].reply(command(false));
assert.equal(mute, false);
assert.deepEqual(operations, ['disable']);
assert(requests[1].url.endsWith('completed=' + 'a'.repeat(32) + '&muted=0'));
requests[1].reply(command(true));
assert.equal(mute, true);
assert.deepEqual(operations, ['disable', 'enable']);
assert(requests[2].url.endsWith('&muted=1'));
requests[2].reply(command(false, {expires: Date.now() - 1}));
assert.equal(mute, true);
assert.equal(reconnects, 1);
for (const bad of [{id: '../arbitrary'}, {muted: 'false'}, {ok: false}, {expires: 'tomorrow'}]) {
    context.waitForCommand();
    requests.at(-1).reply(command(false, bad));
    assert.equal(mute, true);
}
assert.equal(reconnects, 5);
context.waitForCommand();
context.stopped = true;
requests.at(-1).reply(command(false));
assert.equal(mute, true);
assert.deepEqual(operations, ['disable', 'enable']);
assert(source.includes('repeat: false'));
assert(source.includes('pendingRequest.abort()'));
"""
    subprocess.run(
        [node, "-e", script, str(ROOT / "device_qml/C300XRingerControl.qml"),
         str(ROOT / "native_agent/config.example.json")],
        check=True, capture_output=True, text=True,
    )
