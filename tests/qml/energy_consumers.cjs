const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'device_qml/js/c300x_energy_consumers.js'), 'utf8');
const ctx = vm.createContext({});
vm.runInContext(source.replace(/^\.pragma library\s*/, ''), ctx);
const plain = value => JSON.parse(JSON.stringify(value));
const items = values => values.map((watts, i) => ({entity_id: `sensor.${i}`, watts, label: `Label ${i}`, color: '#abcdef'}));

// Contract: global ranking, deterministic ties, exact watts, unknown is not zero.
assert.deepEqual(plain(ctx.rows(null)), []);
assert.deepEqual(plain(ctx.rows({items: 'bad'})), []);
const input = {items: items([null, 0, -1, 0.05, Infinity, NaN, '8', 25, 25, Number.MAX_VALUE])};
const before = input.items.slice();
const ranked = plain(ctx.rows(input));
assert.deepEqual(ranked.slice(0, 5).map(row => row.watts), [Number.MAX_VALUE, 25, 25, 0.05, 0]);
assert(ranked.slice(5).every(row => row.watts === null && row.value === '--'));
assert.equal(ranked[3].value, '0 W');
assert.equal(ranked[4].value, '0 W');
assert(ranked.every(row => row.color === '#abcdef'));
assert.deepEqual(input.items, before);
assert.equal(ctx.rows({items: items(Array.from({length: 30}, (_, i) => i))}).length, 10);
assert.equal(ctx.rows({items: [{watts: 0.125, value: '0,125 W'}]})[0].value, '0 W');
assert.equal(ctx.rows({items: [{watts: 1250, value: '1.25 kW'}]})[0].value, '1250 W');

// Whole-W text uses backend half-even rounding, never quantizing the measurements.
for (const [watts, expected] of [[0, '0 W'], [-0, '0 W'], [1e-200, '0 W'],
        [0.5, '0 W'], [1.5, '2 W'], [2.5, '2 W'], [3.5, '4 W'],
        [0.49999999999999994, '0 W'], [0.5000000000000001, '1 W'],
        [1234.5678912345, '1235 W'], [22000.5, '22000 W'], [22001.5, '22002 W'],
        [1234.5, '1234 W'], [1235.5, '1236 W'], [9007199254740991, '9007199254740991 W']]) {
    for (const value of [undefined, null, 12, '', 'bad W', `${watts} W`,
                         `${watts}`.replace('.', ',') + ' W', '1.25 kW', expected]) {
        const row = ctx.rows({items: [{watts, value}]})[0];
        assert.equal(row.value, expected);
        assert.equal(row.watts, watts);
    }
}
// Preserve Python's canonical integer digits; Qt4 toFixed would pad shortest dtoa instead.
for (const [watts, value] of [[9007199254740992, '9007199254740992 W'],
        [1e20, '100000000000000000000 W'], [999999999999999900000, '999999999999999868928 W'],
        [1e21, '1e+21 W'], [Number.MAX_VALUE, '1.7976931348623157e+308 W']]) {
    const row = ctx.rows({items: [{watts, value}]})[0];
    assert.equal(row.value, value);
    assert.equal(row.watts, watts);
}
// A Qt4-like toFixed must never be used to invent exact digits for unsafe integers.
vm.runInContext(`var nativeToFixed = Number.prototype.toFixed;
    Number.prototype.toFixed = function(digits) {
        if (this > 9007199254740991) throw new Error('unsafe toFixed');
        return nativeToFixed.call(this, digits);
    };`, ctx);
for (const watts of [9007199254740992, 1e20, 999999999999999900000,
                    1e21, 1.0000000000000001e21, Number.MAX_VALUE, 1.2345678901234567e200]) {
    for (const value of [undefined, null, 12, '', '9'.repeat(309) + ' W', '1 W', '1 kWh',
                         ' 1e+21 W', '1e+21 W\n', '1.000000000000000000000e+21 W',
                         'Infinity W', 'NaN W', '0.1e+22 W', '1e-21 W', '1000000000000000000000 W']) {
        const row = ctx.rows({items: [{watts, value}]})[0];
        assert(/^[1-9](?:\.\d+)?e\+\d+ W$/.test(row.value));
        assert(row.value.length <= 25);
        assert(row.value.endsWith(' W'));
        assert.equal(Number(row.value.slice(0, -2)), watts);
        assert.equal(row.watts, watts);
    }
}
vm.runInContext('Number.prototype.toFixed = nativeToFixed;', ctx);
vm.runInContext(`var nativeToExponential = Number.prototype.toExponential;
    Number.prototype.toExponential = function() { return '1e+20'; };`, ctx);
assert.equal(ctx.rows({items: [{watts: 1e21}]})[0].value, '--');
assert.equal(ctx.rows({items: [{watts: 1e21, value: '1e+21 W'}]})[0].value, '1e+21 W');
vm.runInContext('Number.prototype.toExponential = nativeToExponential;', ctx);
assert.equal(ctx.rows({items: [{watts: 0.5, value: '1 W'}]})[0].value, '0 W');
assert.equal(ctx.rows({items: [{watts: 1250, value: '999 W'}]})[0].value, '1250 W');
assert.equal(ctx.rows({items: [{watts: 1234.5, value: '9'.repeat(309) + ' W'}]})[0].value, '1234 W');
const fractional = items([1.01, 1.02, 1.03]);
const fractionalRows = ctx.rows({items: fractional});
assert.deepEqual(plain(fractionalRows.map(row => row.watts)), [1.03, 1.02, 1.01]);
assert(fractionalRows.every(row => row.value === '1 W'));
assert.deepEqual(plain(ctx.domain(fractionalRows)), plain(ctx.domain(fractional)));
const fractionalAxis = ctx.domain(fractionalRows);
assert(ctx.position(fractionalRows[0].watts, fractionalAxis) >
       ctx.position(fractionalRows[1].watts, fractionalAxis));

// The log transform is monotonic, bounded and truthful for equal/zero/extreme inputs.
for (const values of [[0, 0], [10, 10], [.005, .01, .5], [Number.MIN_VALUE], [Number.MAX_VALUE],
                      [Number.MIN_VALUE, 0.01, 1e100, Number.MAX_VALUE]]) {
    const axis = ctx.domain(items(values));
    assert(Number.isFinite(axis.low) && Number.isFinite(axis.high) && axis.high > axis.low);
    let last = -1;
    for (const value of values) {
        const position = ctx.position(value, axis);
        assert(Number.isFinite(position) && position >= 0 && position <= 1);
        assert(value === 0 ? position === 0 : position > 0);
        assert(position >= last);
        last = position;
    }
    for (const value of [null, undefined, NaN, Infinity, -1, '2']) assert.equal(ctx.position(value, axis), 0);
    for (const width of [140, 202, 362, 700]) {
        let right = -8;
        for (const tick of ctx.ticks(axis, width)) {
            assert(/ (?:kW|W)$/.test(tick.label));
            assert(!/NaN|Infinity|log/.test(tick.label));
            assert(tick.x >= right + 8 && tick.x + tick.width <= width);
            assert(tick.point >= 0 && tick.point <= width);
            right = tick.x + tick.width;
        }
    }
}
const left = ctx.domain(items([22000, 11000, 2450, 1450, 620]));
const right = ctx.domain(items([410, 210, 95, 62, 10]));
assert.notDeepEqual(plain(left), plain(right));
assert.equal(ctx.position(10, ctx.domain(items([10, 100, 1000]))), 1 / 3);

// Expansion is immediate; sustained shrink needs ten seconds, fluctuations cancel it.
let state = ctx.scale(null, left, 100);
assert.equal(state.deadline, 0);
assert.deepEqual(plain(ctx.scale(state, left, 500)), plain(state));
const small = {low: left.low, high: left.high - 2};
state = ctx.scale(state, small, 1000);
assert.equal(state.high, left.high);
assert.equal(state.deadline, 11000);
assert.equal(ctx.scale(state, small, 10999).high, left.high);
assert.equal(ctx.scale(state, small, 11000).high, small.high);
assert.equal(ctx.scale(state, small, 11000).deadline, 0);
assert.equal(ctx.scale(state, left, 9000).deadline, 0);
assert.equal(ctx.scale(state, {low: left.low, high: left.high + 1}, 9000).high, left.high + 1);
assert.equal(ctx.scale(state, {low: left.low - 1, high: left.high + 1}, 9000).low, left.low - 1);
// Falling watts extend the low end immediately while scheduling the high-end shrink.
const falling = ctx.scale(ctx.scale(null, left, 0), {low: left.low - 3, high: left.high - 3}, 500);
assert.equal(falling.low, left.low - 3);
assert.equal(falling.high, left.high);
assert.equal(falling.deadline, 10500);
assert.equal(ctx.scale(falling, {low: left.low - 3, high: left.high - 3}, 10500).deadline, 0);
assert.equal(ctx.scale(falling, {low: left.low - 3, high: left.high - 3}, -1000).deadline, 0);
console.log('consumer ranking, whole-W display, raw watts, logarithms, ticks and hysteresis passed');
