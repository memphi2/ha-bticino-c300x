.pragma library

function list(value) {
    return value && typeof value !== "string" && value.length !== undefined ? value : [];
}

function finite(value) {
    return typeof value === "number" && isFinite(value);
}

function bucket(x, width, count) {
    if (!finite(x) || !finite(width) || width <= 0 || count <= 0) return -1;
    return Math.max(0, Math.min(count - 1, Math.floor(x / width * count)));
}

function count(series) {
    var result = 0;
    for (var i = 0; i < series.length; i++) result = Math.max(result, list(series[i].values).length);
    return result;
}

function clock(minutes) {
    var hours = Math.floor(minutes / 60), rest = minutes % 60;
    return (hours < 10 ? "0" : "") + hours + ":" + (rest < 10 ? "0" : "") + rest;
}

function interval(index, minutes, buckets) {
    if (index < 0 || index >= buckets) return "";
    return clock(index * minutes) + " - " + clock((index + 1) * minutes);
}

function timestamp(history, index) {
    var time = history ? history.time : undefined;
    if (!time || !finite(time.start) || time.step !== 900 || index < 0 || index >= time.count) return "--";
    var offsets = list(time.offsets), offset = null;
    for (var i = 0; i < offsets.length; i++) {
        if (offsets[i][0] <= index) offset = offsets[i][1];
        else break;
    }
    if (!finite(offset)) return "--";
    // UTC getters operate on the supplied HA wall time, never the device timezone.
    var date = new Date((time.start + index * time.step + offset) * 1000);
    if (!finite(date.getTime())) return "--";
    var zone = clock(Math.abs(offset) / 60).replace(":", "");
    return date.getUTCFullYear() + "-" + pad(date.getUTCMonth() + 1) + "-" + pad(date.getUTCDate()) + " " +
           clock(date.getUTCHours() * 60 + date.getUTCMinutes()) + " UTC" + (offset < 0 ? "-" : "+") + zone;
}

function pad(value) {
    return (value < 10 ? "0" : "") + value;
}

function points(values, axis) {
    values = list(values);
    var result = [], span = axis ? axis.max - axis.min : NaN;
    for (var i = 0; i < values.length; i++) {
        var value = values[i], point = null;
        if (finite(value) && finite(span) && span > 0 && finite(axis.min) && value >= axis.min && value <= axis.max) {
            point = (value - axis.min) / span;
            if (!finite(point)) point = null;
        }
        result.push(point);
    }
    return result;
}

function decimalSeparator(axis) {
    if (axis && axis.decimal_separator === ",") return ",";
    var ticks = list(axis ? axis.ticks : undefined);
    for (var i = 0; i < ticks.length; i++) {
        if (String(ticks[i].label).indexOf(",") >= 0) return ",";
    }
    return ".";
}

function zeroTick(ticks) {
    var all = list(ticks);
    for (var i = 0; i < all.length; i++) if (all[i] && all[i].value === 0) return i;
    return 0;
}

function barSegment(series, hour, index, axis, height) {
    var empty = {y: 0, height: 0};
    if (!axis || !finite(axis.min) || !finite(axis.max) || axis.max <= axis.min ||
            !finite(height) || height <= 0 || index < 0 || index >= series.length) return empty;
    var value = list(series[index].values)[hour];
    if (!finite(value) || value === 0) return empty;
    var base = 0;
    for (var i = 0; i < index; i++) {
        var previous = list(series[i].values)[hour];
        if (finite(previous) && (previous < 0) === (value < 0)) base += previous;
    }
    var span = axis.max - axis.min;
    if (!finite(span) || !finite(base + value)) return empty;
    var from = Math.round(Math.max(0, Math.min(1, (axis.max - base) / span)) * height);
    var to = Math.round(Math.max(0, Math.min(1, (axis.max - base - value) / span)) * height);
    return {y: Math.min(from, to), height: Math.abs(to - from)};
}

function number(value, digits, separator) {
    if (value !== 0 && (Math.abs(value) < 0.001 || Math.abs(value) >= 1e9)) {
        return value.toExponential(2).replace(".", separator);
    }
    var rounded = Number(value.toFixed(digits));
    return String(rounded === 0 ? 0 : rounded).replace(".", separator);
}

function powerRows(history, index) {
    var series = list(history ? history.series : undefined), result = [];
    var axis = history && history.axis ? history.axis : {};
    for (var i = 0; i < series.length; i++) {
        var value = "--";
        var watts = list(series[i].values)[index];
        if (index >= 0 && finite(watts)) {
            var divisor = Math.abs(watts) >= 1000000 ? 1000000 : Math.abs(watts) >= 1000 ? 1000 : 1;
            value = number(watts / divisor, 3, decimalSeparator(axis)) + (divisor === 1 ? " W" : divisor === 1000 ? " kW" : " MW");
        }
        result.push({label: series[i].label || "", color: series[i].color, value: value});
    }
    return result;
}

function todayRows(hours, sums, index) {
    var series = list(hours ? hours.series : undefined), result = [];
    sums = list(sums);
    for (var i = 0; i < series.length; i++) {
        var entry = series[i], label = entry.label || "", separator = decimalSeparator(hours.axis);
        // Today series carry colors, not labels. The first matching sum is
        // the matching source (battery discharge precedes battery charge).
        for (var j = 0; j < sums.length; j++) {
            if (sums[j].color === entry.color) {
                label = label || sums[j].label;
                if (String(sums[j].value).indexOf(",") >= 0) separator = ",";
                break;
            }
        }
        var value = list(entry.values)[index];
        result.push({label: label, color: entry.color,
                     value: index >= 0 && finite(value) ? number(value, 3, separator) + " kWh" : "--"});
    }
    return result;
}
