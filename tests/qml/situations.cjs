const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.join(__dirname, "../../device_qml");
const context = vm.createContext({XMLHttpRequest: function () { assert.fail("page rendering must not execute requests"); }});
vm.runInContext(fs.readFileSync(path.join(root, "js/c300x_ha.js"), "utf8").replace(/^\.pragma library\s*/, ""), context);
const page = {currentPageIndex: 1, pageCount: 3, pageActive: false,
    dashboardPages: [{title: "Agenda", agenda: {events: []}},
        {title: "Situations", situations: {checks: [{name: "Window", state_label: "Unknown"}]}},
        {title: "Leave home", leave_home: {checks: []}}]};
context.loadDashboardPage({}, page);
assert.equal(page.currentPageIndex, 1);
assert.equal(page.pageActive, false);
assert.equal(page.situationsVisible, true);
assert.equal(page.leaveHomeVisible, false);
assert.equal(page.situations.checks[0].state_label, "Unknown");
const previous = page.situations;
context.loadDashboardPage({}, page);
assert.equal(page.situations, previous, "unchanged payload must not reallocate the QML model");
page.currentPageIndex = 2;
context.loadDashboardPage({}, page);
assert.equal(page.situationsVisible, false);
assert.equal(page.leaveHomeVisible, true);
assert.equal(Object.keys(page.situations).length, 0);
page.currentPageIndex = 0;
context.loadDashboardPage({}, page);
assert.equal(page.agendaVisible, true);
assert.equal(page.situationsVisible, false);
for (const file of ["C300XSituations.qml", "C300XChecks.qml"]) {
    const qml = fs.readFileSync(path.join(root, file), "utf8");
    assert.match(qml, /^import QtQuick 1\.1/m);
    assert.doesNotMatch(qml, /QtQuick 2|property var |Component\.onCompleted|MouseArea|Timer|Api\.|XMLHttpRequest|wake|activateTab|actionRequested|alarmRequested/);
}
const host = fs.readFileSync(path.join(root, "C300XOptionalPages.qml"), "utf8");
assert.match(host, /source: root.situationsVisible \? "C300XSituations.qml" : ""/);
assert.match(host, /when: situationsLoader.status === Loader.Ready/);
assert.match(host, /onActionRequested: root.actionRequested\(item\)/);
assert.match(host, /onAlarmRequested: root.alarmRequested\(\)/);
assert.doesNotMatch(host, /QtQuick 2|property var |Component\.onCompleted|wake|activateTab/);
