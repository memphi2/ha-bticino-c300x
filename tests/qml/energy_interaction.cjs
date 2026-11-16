const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const helper = fs.readFileSync(path.join(root, 'device_qml/js/c300x_energy.js'), 'utf8');
const qml = fs.readFileSync(path.join(root, 'device_qml/C300XEnergy.qml'), 'utf8');
const ctx = vm.createContext({});
vm.runInContext(helper.replace(/^\.pragma library\s*/, ''), ctx);
const rows = value => JSON.parse(JSON.stringify(value));

for (const count of [24, 92, 96, 100]) {
    assert.equal(ctx.bucket(-1, 658, count), 0);
    assert.equal(ctx.bucket(658, 658, count), count - 1);
    assert.equal(ctx.bucket(900, 658, count), count - 1);
    for (let index = 0; index < count; index++) {
        assert.equal(ctx.bucket((index + 0.5) * 658 / count, 658, count), index);
    }
}
for (const args of [[0, 0, 24], [NaN, 658, 24], [1, 658, 0], [1, Infinity, 24]]) {
    assert.equal(ctx.bucket(...args), -1);
}
assert.equal(ctx.interval(23, 60, 24), '23:00 - 24:00');
assert.equal(ctx.interval(-1, 60, 24), '');
assert.equal(ctx.timestamp({}, 0), '--');
const autumn = {time: {start: Date.parse('2026-10-25T00:00:00+02:00') / 1000,
                      step: 900, count: 100, offsets: [[0, 7200], [12, 3600]]}};
assert.equal(ctx.timestamp(autumn, 8), '2026-10-25 02:00 UTC+0200');
assert.equal(ctx.timestamp(autumn, 12), '2026-10-25 02:00 UTC+0100');
assert.equal(ctx.timestamp(autumn, 99), '2026-10-25 23:45 UTC+0100');
assert.equal(ctx.timestamp(autumn, 100), '--');
const spring = {time: {start: Date.parse('2026-03-29T00:00:00+01:00') / 1000,
                      step: 900, count: 92, offsets: [[0, 3600], [8, 7200]]}};
assert.equal(ctx.timestamp(spring, 7), '2026-03-29 01:45 UTC+0100');
assert.equal(ctx.timestamp(spring, 8), '2026-03-29 03:00 UTC+0200');
assert.equal(ctx.timestamp({time: {start: 0, step: 900, count: 96, offsets: [[0, -12600]]}}, 0), '1969-12-31 20:30 UTC-0330');
assert.equal(ctx.timestamp({time: {start: 0, step: 900, count: 96, offsets: [[0, 20700]]}}, 0), '1970-01-01 05:45 UTC+0545');
assert.deepEqual(rows(ctx.points([-10, 0, null, 10, '3', Infinity, 11], {min: -10, max: 10})), [0, 0.5, null, 1, null, null, null]);
assert.deepEqual(rows(ctx.points([0], {min: 0, max: 0})), [null]);
assert.deepEqual(rows(ctx.powerRows(null, 0)), []);
assert.deepEqual(rows(ctx.todayRows(null, null, 0)), []);
const series = [{label: 'Battery', color: '#7fffd4', points: [0.12345, 0, null, 1, 0.5],
                 values: [-1234.567, 0, null, Infinity, 1.23456789]}];
const history = {axis: {min: -999999, max: 999999, ticks: [{label: '0,5'}]}, series};
assert.equal(ctx.count(series), 5);
assert.equal(ctx.powerRows(history, 0)[0].value, '-1,235 kW');
assert.equal(ctx.powerRows(history, 1)[0].value, '0 W');
assert.equal(ctx.powerRows(history, 2)[0].value, '--');
assert.equal(ctx.powerRows(history, 3)[0].value, '--');
// Read from exact watts, never reverse-map rounded coordinates or axis scales.
assert.equal(ctx.powerRows(history, 4)[0].value, '1,235 W');
assert.equal(ctx.powerRows(history, 99)[0].value, '--');
assert.equal(ctx.powerRows({series: [{points: [0.5]}]}, 0)[0].value, '--');
const sums = [{color: 'red', label: 'Discharge', value: '0,1 kWh'},
              {color: 'red', label: 'Charge', value: '-2 kWh'}];
const hours = {series: [{color: 'red', values: [0, 1.234, null, -1, '2']}]};
assert.deepEqual(rows(ctx.todayRows(hours, sums, 0)), [{color: 'red', label: 'Discharge', value: '0 kWh'}]);
assert.equal(ctx.todayRows(hours, sums, 1)[0].value, '1,234 kWh');
assert.equal(ctx.todayRows(hours, sums, 3)[0].value, '-1 kWh');
for (const index of [2, 4, 8]) assert.equal(ctx.todayRows(hours, sums, index)[0].value, '--');

const stackedBars = [{values: [2]}, {values: [-3]}, {values: [1]}, {values: [-1]}];
const signedAxis = {min: -4, max: 4};
for (const [index, y, height] of [[0, 20, 20], [1, 40, 30], [2, 10, 10], [3, 70, 10]]) {
    assert.deepEqual(rows(ctx.barSegment(stackedBars, 0, index, signedAxis, 80)), {y, height});
}
assert.deepEqual(rows(ctx.barSegment([{values: [-3]}], 0, 0, {min: -4, max: 0}, 80)), {y: 0, height: 60});
assert.deepEqual(rows(ctx.barSegment([{values: [2]}], 0, 0, {min: 0, max: 4}, 80)), {y: 40, height: 40});
for (const value of [0, null, undefined, NaN, Infinity, '2']) {
    assert.deepEqual(rows(ctx.barSegment([{values: [value]}], 0, 0, signedAxis, 80)), {y: 0, height: 0});
}
for (const axis of [null, {}, {min: 1, max: 1}, {min: 0, max: Infinity}]) {
    assert.equal(ctx.barSegment(stackedBars, 0, 0, axis, 80).height, 0);
}
for (const index of [-1, 4]) assert.equal(ctx.barSegment(stackedBars, 0, index, signedAxis, 80).height, 0);
assert.equal(ctx.barSegment(stackedBars, 0, 0, signedAxis, 0).height, 0);

for (const fixture of JSON.parse(fs.readFileSync(0, 'utf8'))) {
    const energy = fixture.energy, before = JSON.stringify(energy);
    for (let index = 0; index < 24; index++) {
        const selected = ctx.todayRows(energy.hours, energy.sums, index);
        assert.equal(selected.length, energy.hours.series.length);
        for (let i = 0; i < selected.length; i++) {
            assert(selected[i].label);
            assert.equal(parseFloat(selected[i].value.replace(',', '.')), energy.hours.series[i].values[index]);
        }
    }
    const power = energy.power;
    for (let index = 0; index < power.time.count; index++) {
        assert.equal(ctx.timestamp(power, index), '2026-11-15 ' + ctx.clock(index * 15) + ' UTC+0000');
        const selected = ctx.powerRows(power, index);
        for (let i = 0; i < selected.length; i++) {
            assert.equal(selected[i].label, power.series[i].label);
            const value = power.series[i].values[index];
            if (value === null) assert.equal(selected[i].value, '--');
            else {
                assert(!selected[i].value.includes('~'));
                const scale = selected[i].value.endsWith(' MW') ? 1e6 : selected[i].value.endsWith(' kW') ? 1000 : 1;
                assert(Math.abs(parseFloat(selected[i].value.replace(',', '.')) - value / scale) <= 0.00050001);
            }
        }
    }
    for (const curve of power.series) {
        const points = ctx.points(curve.values, power.axis);
        assert.equal(points.length, curve.values.length);
        for (let index = 0; index < points.length; index++) {
            if (curve.values[index] === null) assert.equal(points[index], null);
            else assert(points[index] >= 0 && points[index] <= 1);
        }
    }
    assert.equal(JSON.stringify(energy), before);
}

for (const [name, prop, count] of [['energyHoursTap', 'selectedHour', 24], ['energyPowerTap', 'selectedPower', 100]]) {
    const block = qml.split(`objectName: "${name}"`)[1].split('\n            }')[0];
    const handler = block.match(/onClicked: (.+)/)[1];
    const state = {powerBuckets: count};
    vm.runInNewContext(handler, {root: state, EnergyChart: ctx, mouseX: 329, width: 658});
    assert.equal(state[prop], count / 2);
    assert(!block.includes('BeepingMouseArea'));
}
assert(qml.includes('onPowerHistoryChanged: selectedPower = -1'));
assert(qml.includes('onShownChanged: { selectedHour = -1; selectedPower = -1 }'));
const sync = qml.match(/function syncPower\(\) \{[\s\S]*?\n    }/)[0];
const old = {revision: 'old'}, fresh = {revision: 'new'};
const cache = vm.createContext({energy: {power: {revision: 'old'}}, powerHistory: old});
vm.runInContext(sync, cache);
cache.syncPower();
assert.equal(cache.powerHistory, old);
cache.energy = {power: fresh};
cache.syncPower();
assert.equal(cache.powerHistory, fresh);
cache.energy = {};
cache.syncPower();
assert.deepEqual(rows(cache.powerHistory), {});
console.log('Energy helper, payload, tap handlers and revision cache checks passed');
