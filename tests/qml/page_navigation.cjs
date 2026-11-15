const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const api = vm.createContext({Math, JSON});
vm.runInContext(fs.readFileSync(path.resolve(__dirname, "../../device_qml/js/c300x_ha.js"), "utf8")
    .replace(/^\.pragma library\s*/, ""), api);
let loads = 0;
const loadDashboardPage = api.loadDashboardPage;
api.loadDashboardPage = () => { loads++; };
api.getJson = () => { throw new Error("Navigation must not fetch data"); };
const page = {dashboardPages: [{title: "Energy"}, {title: "C300X"}, {title: "Rooms"}],
    currentPageIndex: 1, pageCount: 3};
assert.deepEqual(JSON.parse(JSON.stringify(api.dashboardPageLinks(page))),
    [{index: 0, title: "Energy"}, {index: 2, title: "Rooms"}]);
for (const invalid of [-1, 3, NaN, Infinity, 0.5, "0", null]) api.dashboardSelectPage(invalid, {}, page);
assert.equal(loads, 0);
assert.equal(page.currentPageIndex, 1);
api.dashboardSelectPage(0, {}, page);
assert.equal(page.currentPageIndex, 0);
assert.equal(loads, 1);
assert.equal(api.dashboardMixedItems([{kind: "navigation"}])[0].kind, "navigation");
assert.equal(api.dashboardPageLinks({dashboardPages: [{}], currentPageIndex: 0}).length, 0);

api.loadDashboardPage = loadDashboardPage;
const optional = {dashboardPages: [
    {title: "Agenda", agenda: {events: [{summary: "Meeting"}]}},
    {title: "Leave home", leave_home: {checks: [], actions: []}},
    {title: "Energy", energy: {views: [{id: "today"}]}},
    {title: "C300X", items: [{kind: "navigation"}]},
], pageCount: 4, currentPageIndex: 0, uiText: key => key};
const status = {};
for (let i = 0; i < 4; i++) {
    api.dashboardSelectPage(i, status, optional);
    assert.equal(optional.agendaVisible, i === 0);
    assert.equal(optional.leaveHomeVisible, i === 1);
    assert.equal(optional.energyVisible, i === 2);
    if (i !== 0) assert.deepEqual(Object.keys(optional.agenda), []);
    if (i !== 1) assert.deepEqual(Object.keys(optional.leaveHome), []);
}
