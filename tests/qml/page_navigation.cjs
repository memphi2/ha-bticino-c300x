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

// Favourites bar: up to four pages get a button each; with more pages the
// fourth button is More and lists the rest. Nothing here fetches data.
api.getJson = () => { throw new Error("The favourites bar must not fetch data"); };
const plain = value => JSON.parse(JSON.stringify(value));
const titled = names => names.map(title => ({title}));
assert.deepEqual(plain(api.dashboardPageTabs([], "Home", "More")), []);
assert.deepEqual(plain(api.dashboardPageTabs(undefined, "Home", "More")), []);
assert.deepEqual(plain(api.dashboardPageTabs(titled(["C300X", "Energy", "Rooms", "Garden"]), "Home", "More")), [
    {index: 0, title: "Home"}, {index: 1, title: "Energy"},
    {index: 2, title: "Rooms"}, {index: 3, title: "Garden"}]);
assert.deepEqual(plain(api.dashboardMoreLinks(titled(["C300X", "Energy", "Rooms", "Garden"]), "Home")), []);
const five = titled(["Energy", "C300X", "Rooms", "Garden", "Agenda"]);
assert.deepEqual(plain(api.dashboardPageTabs(five, "Home", "More")), [
    {index: 0, title: "Energy"}, {index: 1, title: "Home"},
    {index: 2, title: "Rooms"}, {index: -1, title: "More"}]);
assert.deepEqual(plain(api.dashboardMoreLinks(five, "Home")),
    [{index: 3, title: "Garden"}, {index: 4, title: "Agenda"}]);
// Every page is reachable exactly once, for every page count the display supports.
for (let count = 1; count <= 14; count++) {
    const pages = titled(Array.from({length: count}, (_, i) => "P" + i));
    const reachable = [...api.dashboardPageTabs(pages, "Home", "More"), ...api.dashboardMoreLinks(pages, "Home")]
        .map(link => link.index).filter(index => index >= 0);
    assert.deepEqual(reachable, pages.map((_, i) => i), "pages " + count);
    assert.ok(api.dashboardPageTabs(pages, "Home", "More").length <= 4);
}
// The highlighted button: the page itself, or More for a listed page and
// while the list is open.
assert.equal(api.dashboardTabCurrent(4, 3, false), 3);
assert.equal(api.dashboardTabCurrent(5, 2, false), 2);
assert.equal(api.dashboardTabCurrent(5, 3, false), -1);
assert.equal(api.dashboardTabCurrent(5, 0, true), -1);
assert.equal(api.dashboardTabCurrent(4, 0, true), 0);

let tabLoads = 0;
api.loadDashboardPage = () => { tabLoads++; };
const tabbed = {dashboardPages: five, pageCount: 5, currentPageIndex: 0, morePagesOpen: false};
api.dashboardSelectTab(-1, {}, tabbed);
assert.equal(tabbed.morePagesOpen, true);
assert.equal(tabLoads, 0);
assert.equal(tabbed.currentPageIndex, 0);
api.dashboardSelectTab(-1, {}, tabbed);
assert.equal(tabbed.morePagesOpen, false);
api.dashboardSelectTab(-1, {}, tabbed);
api.dashboardSelectTab(4, {}, tabbed);
assert.deepEqual([tabbed.morePagesOpen, tabbed.currentPageIndex, tabLoads], [false, 4, 1]);
api.dashboardSelectTab(-1, {}, tabbed);
for (const invalid of [5, -2, 0.5, NaN, "1", null]) api.dashboardSelectTab(invalid, {}, tabbed);
assert.deepEqual([tabbed.morePagesOpen, tabbed.currentPageIndex, tabLoads], [false, 4, 1]);
api.loadDashboardPage = loadDashboardPage;

// The dashboard data switches the bar on and off; the open More list closes
// when the bar goes away or no longer has a More button.
const live = vm.createContext({Date, JSON, Math, XMLHttpRequest() {}});
vm.runInContext(fs.readFileSync(path.resolve(__dirname, "../../device_qml/js/c300x_ha.js"), "utf8")
    .replace(/^\.pragma library\s*/, ""), live);
live.startEventWatch = () => {};
const requests = [];
live.getJson = (url, success, error) => requests.push({url, success, error});
live.getJsonShared = live.getJson;
const board = {uiText: key => key, runtimeGeneration: 0, pageActive: true, currentPageIndex: 0,
    dashboardPages: [], items: [], notifications: [], morePagesOpen: false, tabNavigation: false};
function respond(revision, count, navigation) {
    live.dashboard({}, board);
    const data = {revision, data: {pages: titled(Array.from({length: count}, (_, i) => "P" + i))}};
    if (navigation) data.navigation = navigation;
    requests.shift().success(data);
}
respond("a", 5, "tabs");
assert.equal(board.tabNavigation, true);
board.morePagesOpen = true;
respond("b", 6, "tabs");
assert.equal(board.morePagesOpen, true, "a refresh keeps the open list");
respond("c", 4, "tabs");
assert.equal(board.morePagesOpen, false, "four pages have no More button");
board.morePagesOpen = true;
respond("d", 6);
assert.deepEqual([board.tabNavigation, board.morePagesOpen], [false, false]);
respond("e", 6, "bar");
assert.equal(board.tabNavigation, false, "only the known value switches the bar on");

// The page wires the bar, the list and the arrows to these functions.
const qml = fs.readFileSync(path.resolve(__dirname, "../../device_qml/HomeAssistant.qml"), "utf8");
const component = fs.readFileSync(path.resolve(__dirname, "../../device_qml/C300XPageNavigation.qml"), "utf8");
for (const line of [
    "visible: tabNavigation && pageCount > 1 && !detailOpen && !notificationsOpen",
    'links: visible ? Api.dashboardPageTabs(dashboardPages, uiText("start_page"), uiText("more")) : []',
    "current: Api.dashboardTabCurrent(pageCount, currentPageIndex, morePagesOpen)",
    'links: visible ? Api.dashboardMoreLinks(dashboardPages, uiText("start_page")) : []',
    "visible: morePagesOpen && tabBar.visible",
    "visible: pageCount > 1 && !tabNavigation",
    "height: pageCount > 1 && !tabNavigation ? 38 : 0",
    "visible: !detailOpen && !notificationsOpen && !morePagesOpen",
    "anchors.bottomMargin: tabBar.visible ? 65 : 18",
    "else if (morePagesOpen) morePagesOpen = false",
]) assert.ok(qml.includes(line), line);
assert.equal(qml.split("onSelected: Api.dashboardSelectTab(pageIndex, status, page)").length, 3);
// Leaving the page closes the list, so it does not open on the next visit.
assert.match(qml, /function aboutToHide\(\) \{[^}]*morePagesOpen = false/);
// The bar is 56 px high and lies 9 px below the content: 65 px in all.
assert.ok(component.includes("height: navigation.bar ? 56 : 52"));
