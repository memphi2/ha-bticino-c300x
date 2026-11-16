.pragma library

function finite(value) {
    return typeof value === "number" && isFinite(value) && value >= 0;
}

function scientificWatts(watts, text) {
    return typeof text === "string" && text.length <= 25 && text.slice(-2) === " W" &&
        /^[1-9](\.[0-9]{1,16})?e\+[0-9]{1,3} W$/.test(text) &&
        Number(text.slice(0, -2)) === watts;
}

function wholeWatts(watts, value) {
    // Match Python round(): exact halves go to the nearest even integer.
    var rounded = Math.floor(watts), fraction = watts - rounded;
    if (fraction > 0.5 || (fraction === 0.5 && rounded % 2 !== 0)) rounded += 1;
    if (watts < 1e21 && typeof value === "string" && value.length <= 23 && value.slice(-2) === " W" &&
        /^(0|[1-9][0-9]*) W$/.test(value) && Number(value.slice(0, -2)) === rounded) return value;
    if (watts >= 1e21 && scientificWatts(watts, value)) return value;
    // Qt4 pads shortest dtoa digits in toFixed: trust the backend for unsafe integers.
    if (rounded <= 9007199254740991) return rounded.toFixed(0) + " W";
    var text = rounded.toExponential() + " W";
    return scientificWatts(rounded, text) ? text : "--";
}

function rows(payload) {
    var source = payload && payload.items, result = [];
    if (!source || typeof source === "string" || source.length === undefined) return result;
    for (var i = 0; i < source.length; i++) {
        var item = source[i];
        if (!item || typeof item !== "object") continue;
        var watts = finite(item.watts) ? item.watts : null;
        result.push({entity_id: String(item.entity_id || ""), label: String(item.label || ""),
            watts: watts, color: item.color || "#90caf9",
            value: watts === null ? "--" : wholeWatts(watts, item.value), order: i});
    }
    result.sort(function(a, b) {
        if (a.watts === null && b.watts !== null) return 1;
        if (b.watts === null && a.watts !== null) return -1;
        if (a.watts !== b.watts) return a.watts > b.watts ? -1 : 1;
        return a.entity_id < b.entity_id ? -1 : a.entity_id > b.entity_id ? 1 : a.order - b.order;
    });
    return result.slice(0, 10);
}

function logarithm(value) { return Math.log(value) / Math.LN10; }

function domain(items) {
    var low = Infinity, high = -Infinity;
    for (var i = 0; i < items.length; i++) {
        if (!finite(items[i].watts) || items[i].watts === 0) continue;
        var power = logarithm(items[i].watts);
        low = Math.min(low, power);
        high = Math.max(high, power);
    }
    if (!isFinite(low)) return {low: 0, high: 2};
    var exponent = Math.floor(high), fraction = high - exponent;
    var ceiling = fraction < 1e-12 ? 0 : fraction <= logarithm(2) ? logarithm(2) :
                  fraction <= logarithm(5) ? logarithm(5) : 1;
    // Store bounds in exponent space: no overflow at MAX_VALUE or underflow at MIN_VALUE.
    return {low: Math.floor(low) - 1, high: exponent + ceiling};
}

function scale(previous, desired, now) {
    if (!previous || !isFinite(now)) return {low: desired.low, high: desired.high, deadline: 0};
    var low = previous.low, high = previous.high;
    if (desired.low < low || desired.high > high) {
        return scale({low: Math.min(low, desired.low), high: Math.max(high, desired.high), deadline: 0}, desired, now);
    }
    if (desired.low < low + 1 && desired.high > high - logarithm(2) + 1e-10) {
        return {low: low, high: high, deadline: 0};
    }
    var deadline = previous.deadline || now + 10000;
    var nextLow = previous.deadline ? Math.min(previous.nextLow, desired.low) : desired.low;
    var nextHigh = previous.deadline ? Math.max(previous.nextHigh, desired.high) : desired.high;
    if (now >= deadline || deadline - now > 10000) return {low: nextLow, high: nextHigh, deadline: 0};
    return {low: low, high: high, deadline: deadline, nextLow: nextLow, nextHigh: nextHigh};
}

function position(watts, axis) {
    if (!finite(watts) || watts === 0 || !axis || axis.high <= axis.low) return 0;
    return Math.max(0, Math.min(1, (logarithm(watts) - axis.low) / (axis.high - axis.low)));
}

function tickLabel(value) {
    var kilo = value >= 1000, number = kilo ? value / 1000 : value;
    return String(Number(number.toPrecision(3))) + (kilo ? " kW" : " W");
}

function ticks(axis, width) {
    if (!axis || width <= 0) return [];
    var count = width < 280 ? 3 : 4, result = [], right = -8;
    for (var i = 0; i < count; i++) {
        var power = i === 0 ? axis.low : i === count - 1 ? axis.high :
                    Math.round(axis.low + (axis.high - axis.low) * i / (count - 1));
        var value = Math.pow(10, power);
        if (!isFinite(value) || value === 0) continue;
        var label = tickLabel(value), labelWidth = label.length * 7 + 4;
        var point = (power - axis.low) / (axis.high - axis.low) * width;
        var x = Math.max(0, Math.min(width - labelWidth, point - labelWidth / 2));
        if (labelWidth > width || x < right + 8) continue;
        result.push({label: label, x: x, width: labelWidth, point: point});
        right = x + labelWidth;
    }
    return result;
}
