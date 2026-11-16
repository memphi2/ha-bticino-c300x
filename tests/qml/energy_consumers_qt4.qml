import QtQuick 1.1
import "../../device_qml/js/c300x_energy_consumers.js" as Consumers

Item {
    Component.onCompleted: {
        var checks = 0
        function check(condition, label) {
            if (!condition) throw new Error("consumer label: " + label)
            checks++
        }
        var cases = [[0.5, "1 W", "0 W"], [1.5, "2 W", "2 W"],
                     [1234.5, "1234 W", "1234 W"], [1250, "999 W", "1250 W"],
                     [9007199254740991, null, "9007199254740991 W"],
                     [1e20, "100000000000000000000 W", "100000000000000000000 W"],
                     [999999999999999900000, "999999999999999868928 W", "999999999999999868928 W"],
                     [1e21, "1e+21 W", "1e+21 W"],
                     [Number.MAX_VALUE, "1.7976931348623157e+308 W", "1.7976931348623157e+308 W"]]
        var i, j, row
        for (i = 0; i < cases.length; i++) {
            row = Consumers.rows({items: [{watts: cases[i][0], value: cases[i][1]}]})[0]
            check(row.value === cases[i][2], "backend " + i + ": " + row.value)
            check(row.watts === cases[i][0], "measurement " + i)
        }
        var values = [9007199254740992, 1e20, 999999999999999900000, 1e21,
                      1.0000000000000001e21, 1.2345678901234567e200, Number.MAX_VALUE]
        var invalid = [null, 12, "", new Array(310).join("9") + " W", "1 W", "1 kWh",
                       "1e+21 W\n", " 1e+21 W", "1.000000000000000000000e+21 W",
                       "Infinity W", "NaN W", "0.1e+22 W", "1e-21 W",
                       "1000000000000000000000 W"]
        for (i = 0; i < values.length; i++) {
            for (j = 0; j < invalid.length; j++) {
                row = Consumers.rows({items: [{watts: values[i], value: invalid[j]}]})[0]
                check(Consumers.scientificWatts(values[i], row.value), "fallback " + i + "/" + j + ": " + row.value)
                check(row.watts === values[i], "raw " + i + "/" + j)
            }
        }
        console.log("QT4_CONSUMER_EVIDENCE " + JSON.stringify({
            toFixed: (999999999999999900000).toFixed(0),
            backend: Consumers.wholeWatts(999999999999999900000, "999999999999999868928 W"),
            fallback: Consumers.wholeWatts(999999999999999900000)
        }))
        console.log("C300X_CONSUMERS_QT4_PASS " + checks)
    }
}
