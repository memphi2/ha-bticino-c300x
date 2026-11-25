// The bridge's setMuted with a model of the vendor AudioState: the flag, and the
// transition (frame and isRingtoneMuteChanged) only while no higher state holds.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const start = source.indexOf("    function setMuted(");
assert(start >= 0, "setMuted missing");
const end = source.indexOf("\n    }\n", start);
const audio = {
    flag: false, higher: false, frames: [], bridge: null,
    isStateEnabled(state) { assert.equal(state, 4); return this.flag; },
    set(value) {
        if (this.flag === value) return;
        this.flag = value;
        if (this.higher) return;
        this.frames.push(value ? "*#8**#33*0##" : "*#8**#33*1##");
        this.bridge.muteSignals++;
    },
    enableState(state) { assert.equal(state, 4); this.set(true); },
    disableState(state) { assert.equal(state, 4); this.set(false); },
};
const bridge = {running: true, stopped: false, blocked: false, muteState: 4, muteSignals: 0,
                vendor: {audioState: audio}};
audio.bridge = bridge;
vm.createContext(bridge);
vm.runInContext(source.slice(start, end + 6).replace("function setMuted", "this.setMuted = function"), bridge);

assert.equal(bridge.setMuted(true), true);
assert.deepEqual(audio.frames, ["*#8**#33*0##"]);
assert.equal(bridge.setMuted(true), true, "an unchanged flag is reported as it is");
assert.equal(audio.frames.length, 1);
assert.equal(bridge.setMuted(false), false);
assert.deepEqual(audio.frames, ["*#8**#33*0##", "*#8**#33*1##"]);

// An answering-machine message or another higher state: no transition now, so no deferred one later.
audio.higher = true;
assert.equal(bridge.setMuted(true), false, "acked a mute that only takes effect later");
assert.equal(audio.flag, false, "the flag change was not undone");
audio.flag = true;
assert.equal(bridge.setMuted(false), true, "acked an unmute that never reaches the device");
assert.equal(audio.flag, true);
assert.equal(audio.frames.length, 2);

bridge.blocked = true;
assert.equal(bridge.setMuted(false), null);
assert.equal(audio.flag, true);
