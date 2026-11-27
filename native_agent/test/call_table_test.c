/* The call table and the outdoor units, fed with the frame sequences of the
 * owner's captures (one unit, 1.7.19) and of a three-unit installation
 * (20#2 behind an apartment interface, 21, 22). Times are the captures'.
 * Rings pass the agent's duplicate filter first, as in the agent. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>

#include "../src/call_table.h"
#include "../src/outdoor_units.h"

static char types[64][40];
static char datas[64][512];
static int total;

static void record(void *context, const char *type, const char *data)
{
    (void)context;
    assert(total < 64);
    snprintf(types[total], sizeof(types[0]), "%s", type);
    snprintf(datas[total], sizeof(datas[0]), "%s", data);
    total++;
}

static int count(const char *type)
{
    int found = 0;
    for (int index = 0; index < total; index++) found += strcmp(types[index], type) == 0;
    return found;
}

static const char *nth(const char *type, int wanted)
{
    for (int index = 0, seen = 0; index < total; index++) {
        if (strcmp(types[index], type) == 0 && ++seen == wanted) return datas[index];
    }
    fprintf(stderr, "no %s #%d\n", type, wanted);
    assert(0);
    return "";
}

static void expect(const char *haystack, const char *needle)
{
    if (strstr(haystack, needle) == NULL) {
        fprintf(stderr, "expected %s in %s\n", needle, haystack);
        assert(0);
    }
}

static struct c300x_outdoor_units units;
static struct c300x_calls calls;
static struct c300x_call_sink sink = {record, NULL, &units};
static char data[512];

static const char *CONF =
    "<setup><vdes><communication><vde_enabled>1</vde_enabled><dev>1</dev><address>0</address>"
    "<p_default>\n<dev>2</dev>\n<address>0</address>\n</p_default></communication></vdes></setup>";
static const char *ARCHIVE_THREE =
    "<?xml version=\"1.0\"?><archive>"
    "<obj where=\"0\" cid=\"10050\" dev=\"2\" lock=\"0\" staircase=\"0\">"
    "<ist uii=\"101\" cid=\"10060\" where=\"0\" descr=\"Lock gate\"/>"
    "<ist uii=\"109\" cid=\"10060\" where=\"1\" descr=\"Lock 1\"/>"
    "<ist uii=\"114\" where=\"0#2\" descr=\"Gate &amp; street\"/>"
    "<ist uii=\"115\" where=\"1\" descr=\"Building A\"/>"
    "<ist uii=\"116\" where=\"2\" descr=\"Building B\"/>"
    "</obj><obj where=\"1\" cid=\"10053\" dev=\"1\"></obj></archive>";

static struct c300x_call_media media;
static long long last_press;

/* The units of these station files, as the agent builds them. */
static void build(const char *archive, const char *conf)
{
    struct c300x_station_archive station;
    c300x_station_archive_parse(&station, archive, conf);
    c300x_outdoor_units_build(&units, &station, archive ? "ok" : "missing", "20", "20");
}

static void reset(const char *archive)
{
    memset(&units, 0, sizeof(units));
    build(archive, CONF);
    c300x_calls_init(&calls, "8f3a1c2e");
    memset(&media, 0, sizeof(media));
    last_press = -100000;
    total = 0;
}

/* A ring frame: the duplicate filter (1 s from the last ring it let through), then the table. */
static void ring(long long now)
{
    if (now - last_press < 1000) return;
    last_press = now;
    const struct c300x_call *call = c300x_calls_ring(&calls, &sink, now);
    snprintf(data, sizeof(data), "{\"call_id\":\"%s\",\"unit\":\"%s\",\"attribution\":\"%s\"}", call->id,
             call->unit, call->attribution);
    record(NULL, "doorbell.pressed", data);
}
static void frame(const char *text, long long now) { c300x_calls_frame(&calls, &sink, text, now); }
static void tick(long long now) { c300x_calls_tick(&calls, &sink, &media, now); }
static void answer_seen(long long now) { c300x_calls_answer_seen(&calls, &sink, &media, now); }
static void closed(int external, int from_bus, long long now)
{
    c300x_calls_media_closed(&calls, &sink, &media, external, from_bus, now);
}

/* c300x-full-ring-20260704-145356: three ring copies, three caller copies. */
static void ring_with_caller(long long t, const char *caller)
{
    ring(t);
    ring(t + 285);
    ring(t + 291);
    frame(caller, t + 351);
    frame(caller, t + 456);
    frame(caller, t + 460);
}

/* c300x-ha-device-20260615-230207 (1.7.19, one unit), times from the ring
 * frame on the multicast path: HA answers, *8*100 follows the answer by
 * 130 ms and ends nothing, HA hangs up. */
static void single_unit_capture(void)
{
    reset(NULL);
    assert(c300x_calls_timeout_ms(&calls, 0) == -1);
    ring_with_caller(0, "*8*9#1#4*20##");
    assert(count("doorbell.pressed") == 1);
    expect(nth("doorbell.pressed", 1), "\"call_id\":\"8f3a1c2e-1\",\"unit\":\"\",\"attribution\":\"pending\"");
    assert(count("call.caller_identified") == 1);
    expect(nth("call.caller_identified", 1), "\"unit\":\"20\",\"where\":\"20\",\"action_where\":\"20\",\"attribution\":\"caller_frame\"");
    tick(1500);
    assert(count("call.caller_identified") == 1);
    /* POST .../answer at 13043; the agent's answer reports the view at 13073. */
    media.ring_leg = media.ha_answered = 1;
    answer_seen(13073);
    expect(nth("call.answered", 1), "\"answered_by\":\"ha\"");
    frame("*8*2#1#4*11##", 13173);
    frame("*8*100#1#4*20##", 13305);
    answer_seen(13395);
    assert(count("call.answered") == 1 && count("call.ended") == 0);
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    /* POST .../hangup at 19900. */
    c300x_calls_end(&calls, &sink, "8f3a1c2e-1", "hangup", 19900);
    expect(nth("call.ended", 1), "\"unit\":\"20\",\"kind\":\"ring\",\"reason\":\"hangup\"");
    assert(c300x_calls_timeout_ms(&calls, 19900) == C300X_CALL_ENDED_KEEP_MS);
    assert(c300x_calls_current(&calls) == NULL);
    tick(19900 + C300X_CALL_ENDED_KEEP_MS);
    assert(c300x_calls_timeout_ms(&calls, 80000) == -1 && c300x_calls_find(&calls, "8f3a1c2e-1") == NULL);
}

/* c300x-unanswered-ring-20260708-134502: the station's end frame at
 * 29.6 s, its CANCEL at 29.9 s; no answer frame follows. */
static void unanswered_capture(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    media.ring_leg = 1;
    closed(0, 1, 29600);
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1") && count("call.ended") == 0);
    media.ring_leg = 0;
    closed(0, 0, 29951);
    assert(c300x_calls_timeout_ms(&calls, 29951) == 29600 + C300X_CALL_SETTLE_MS - 29951);
    tick(29600 + C300X_CALL_SETTLE_MS - 1);
    assert(count("call.ended") == 0);
    tick(29600 + C300X_CALL_SETTLE_MS);
    expect(nth("call.ended", 1), "\"unit\":\"20\",\"kind\":\"ring\",\"reason\":\"media_closed\"");
    assert(count("call.answered") == 0 && c300x_calls_current(&calls) == NULL);
}

/* The display answers after the agent's leg closed (no preview client):
 * the call is answered on the station, the leg's close ends nothing. The
 * display call ends with the bus end frame. */
static void station_answer(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    closed(0, 0, 5300);
    answer_seen(5600);
    expect(nth("call.answered", 1), "\"answered_by\":\"station\"");
    tick(5300 + C300X_CALL_SETTLE_MS);
    frame("*8*100#1#4*20##", 5800);
    closed(0, 0, 6000);
    closed(1, 1, 6100);
    assert(count("call.ended") == 0 && c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    closed(0, 1, 65600);
    expect(nth("call.ended", 1), "\"reason\":\"media_closed\"");
}

/* c300x-app-device-20260612-182122: the app answers; the station's end
 * frame of the ring comes first. */
static void app_answer_end_frame_first(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    media.ring_leg = 1;
    closed(0, 1, 5000);
    answer_seen(5100);
    expect(nth("call.answered", 1), "\"answered_by\":\"station\"");
    tick(5000 + C300X_CALL_SETTLE_MS);
    assert(count("call.ended") == 0);
}

/* A display call whose end frame is lost ends when the display guard is
 * over, a display call that goes on is checked again. */
static void display_guard(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    answer_seen(5000);
    media.external = 1;
    assert(c300x_calls_timeout_ms(&calls, 5000) == C300X_CALL_GUARD_MS);
    tick(5000 + C300X_CALL_GUARD_MS);
    assert(count("call.ended") == 0);
    assert(c300x_calls_timeout_ms(&calls, 5000 + C300X_CALL_GUARD_MS) == C300X_CALL_PROBE_MS);
    media.external = 0;
    tick(5000 + C300X_CALL_GUARD_MS + C300X_CALL_PROBE_MS);
    expect(nth("call.ended", 1), "\"reason\":\"media_closed\"");
    /* HA's call: its leg ends it; the check finds a leg that is gone. */
    ring_with_caller(100000, "*8*9#1#4*20##");
    media.ring_leg = media.ha_answered = 1;
    answer_seen(101000);
    closed(1, 0, 102000);
    tick(101000 + C300X_CALL_GUARD_MS);
    assert(count("call.ended") == 1);
    media.ring_leg = 0;
    tick(101000 + C300X_CALL_GUARD_MS + C300X_CALL_PROBE_MS);
    expect(nth("call.ended", 2), "\"call_id\":\"8f3a1c2e-2\",\"unit\":\"20\",\"kind\":\"ring\",\"reason\":\"media_closed\"");
}

static void unit_behind_interface(void)
{
    reset(ARCHIVE_THREE);
    assert(units.count == 3);
    /* The archive's 20#2 is conf.xml's default unit 20: one unit, id 20. */
    assert(strcmp(c300x_outdoor_units_default(&units)->id, "20") == 0);
    assert(strcmp(units.items[0].name, "Gate & street") == 0);
    ring_with_caller(0, "*8*9#1#4*20#2##");
    expect(nth("call.caller_identified", 1), "\"unit\":\"20\",\"where\":\"20#2\",\"action_where\":\"20\"");
    assert(count("outdoor_units.changed") == 0);
    c300x_calls_end(&calls, &sink, "8f3a1c2e-1", "hangup", 20000);
    ring_with_caller(60000, "*8*9#1#4*22##");
    expect(nth("call.caller_identified", 2), "\"unit\":\"22\"");
    /* Without an archive the default from conf.xml learns the qualifier. */
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20#2##");
    expect(nth("call.caller_identified", 1), "\"unit\":\"20\",\"where\":\"20#2\",\"action_where\":\"20\"");
    assert(count("outdoor_units.changed") == 1 && units.count == 1);
    build(NULL, CONF);
    assert(units.count == 1 && strcmp(units.items[0].where, "20#2") == 0 && strcmp(units.items[0].id, "20") == 0);
    c300x_calls_end(&calls, &sink, "8f3a1c2e-1", "hangup", 20000);
    ring_with_caller(60000, "*8*9#1#4*20#2##");
    assert(count("outdoor_units.changed") == 1);
}

/* Two units within one ring session: one call, the last caller frame names it. */
static void two_units_within_one_second(void)
{
    reset(ARCHIVE_THREE);
    ring(0);
    ring(285);
    frame("*8*9#1#4*21##", 351);
    ring(600);
    frame("*8*9#1#4*22##", 900);
    frame("*8*9#1#4*22##", 1005);
    assert(count("doorbell.pressed") == 1);
    expect(nth("call.caller_identified", 1), "\"call_id\":\"8f3a1c2e-1\",\"unit\":\"21\"");
    expect(nth("call.caller_identified", 2), "\"call_id\":\"8f3a1c2e-1\",\"unit\":\"22\"");
    assert(count("call.caller_identified") == 2 && count("call.ended") == 0);
}

static void caller_missing(void)
{
    reset(ARCHIVE_THREE);
    ring(0);
    ring(285);
    assert(c300x_calls_timeout_ms(&calls, 300) == 700);
    tick(999);
    assert(count("call.caller_identified") == 0);
    tick(1000);
    expect(nth("call.caller_identified", 1), "\"unit\":\"20\",\"where\":\"20#2\",\"action_where\":\"20\",\"attribution\":\"default_fallback\",\"raw\":null");
    assert(c300x_calls_timeout_ms(&calls, 1000) == C300X_CALL_RINGING_TIMEOUT_MS - 1000);
}

/* c300x-ring-answer-20260703-185353: HA answers at +277 ms, before the
 * caller frame at +302 ms; a caller frame after the default unit stood in
 * names the call too. Frames without a ring session are ignored. */
static void caller_late(void)
{
    reset(ARCHIVE_THREE);
    ring(0);
    media.ring_leg = media.ha_answered = 1;
    answer_seen(277);
    frame("*8*9#1#4*21##", 302);
    ring(546);
    ring(553);
    expect(nth("call.caller_identified", 1), "\"call_id\":\"8f3a1c2e-1\",\"unit\":\"21\",\"where\":\"21\"");
    assert(count("doorbell.pressed") == 1);
    reset(ARCHIVE_THREE);
    ring(0);
    tick(1000);
    frame("*8*9#1#4*21##", 1100);
    frame("*8*9#1#4*21##", 1150);
    assert(count("call.caller_identified") == 2);
    expect(nth("call.caller_identified", 2), "\"unit\":\"21\",\"where\":\"21\",\"action_where\":\"21\",\"attribution\":\"caller_frame\"");
    c300x_calls_end(&calls, &sink, "8f3a1c2e-1", "hangup", 2000);
    frame("*8*9#1#4*22##", 2100);
    assert(calls.caller_frames_ignored == 1 && count("call.caller_identified") == 2);
}

static void stale_call_id(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    closed(0, 0, 20000);
    tick(20000 + C300X_CALL_SETTLE_MS);
    ring_with_caller(40000, "*8*9#1#4*20##");
    assert(!c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-2"));
    assert(!c300x_calls_is_current(&calls, "0badc0de-2"));
    assert(c300x_calls_unlock_allowed(&calls, "8f3a1c2e-1", "20", 40000));
    assert(!c300x_calls_unlock_allowed(&calls, "8f3a1c2e-1", "20", 81501));
    assert(!c300x_calls_unlock_allowed(&calls, "8f3a1c2e-2", "21", 40000));
}

/* Rings of a live ring session are its call; a ring after the ring ended
 * unanswered is a new one. */
static void rings_of_one_session(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    ring(3000);
    media.ring_leg = media.ha_answered = 1;
    answer_seen(4000);
    ring(5000);
    assert(count("doorbell.pressed") == 3 && strstr(nth("doorbell.pressed", 3), "8f3a1c2e-1"));
    assert(count("call.answered") == 1 && count("call.ended") == 0);
    c300x_calls_end(&calls, &sink, "8f3a1c2e-1", "hangup", 9000);
    memset(&media, 0, sizeof(media));
    ring(20000);
    expect(nth("doorbell.pressed", 4), "\"call_id\":\"8f3a1c2e-2\"");
    tick(21000);
    closed(0, 1, 30000);
    ring(30500);
    expect(nth("call.ended", 2), "\"call_id\":\"8f3a1c2e-2\",\"unit\":\"20\",\"kind\":\"ring\",\"reason\":\"media_closed\"");
    expect(nth("doorbell.pressed", 5), "\"call_id\":\"8f3a1c2e-3\"");
}

/* HA's hang-up ends the call as hangup, whichever close comes first. */
static void hangup_reason(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    media.ha_hangup = 1;
    closed(0, 0, 3000);
    expect(nth("call.ended", 1), "\"reason\":\"hangup\"");
    media.ha_hangup = 0;
    ring_with_caller(10000, "*8*9#1#4*20##");
    media.ring_leg = media.ha_answered = 1;
    answer_seen(11000);
    media.ha_hangup = 1;
    closed(0, 0, 15000);
    expect(nth("call.ended", 2), "\"call_id\":\"8f3a1c2e-2\",\"unit\":\"20\",\"kind\":\"ring\",\"reason\":\"hangup\"");
}

static void view_and_media_closed(void)
{
    reset(NULL);
    frame("*8*1#5#4#20*11##", 0);
    frame("*8*1#5#4#20*11##", 120);
    frame("*8*9#5#4*20##", 300);
    assert(count("call.view_started") == 1);
    expect(nth("call.view_started", 1), "\"unit\":\"20\"");
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    /* c300x-ha-first-click-click-stop-20260621-214931: *8*100#5 578 ms after the view. */
    frame("*8*100#5#4*20##", 578);
    media.agent = 1;
    tick(C300X_CALL_PROBE_MS);
    assert(count("call.ended") == 0);
    closed(1, 1, 1500);
    assert(count("call.ended") == 0);
    closed(0, 0, 1660);
    expect(nth("call.ended", 1), "\"kind\":\"view\",\"reason\":\"media_closed\"");
    /* A ring during a view is the current call; a view of another unit
     * ends the one before; a view whose media is gone ends at its check. */
    frame("*8*1#5#4#20*11##", 2000);
    ring(2500);
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-3"));
    frame("*8*1#5#4#21*11##", 3000);
    expect(nth("call.ended", 2), "\"call_id\":\"8f3a1c2e-2\",\"unit\":\"20\",\"kind\":\"view\",\"reason\":\"superseded\"");
    media.agent = 0;
    tick(3000 + C300X_CALL_PROBE_MS);
    expect(nth("call.ended", 3), "\"call_id\":\"8f3a1c2e-4\",\"unit\":\"21\",\"kind\":\"view\",\"reason\":\"media_closed\"");
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-3"));
}

static void timeouts_and_json(void)
{
    char json[2048];
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    assert(c300x_calls_json(&calls, 1000, json, sizeof(json)));
    expect(json, "\"current_call_id\":\"8f3a1c2e-1\"");
    expect(json, "\"state\":\"ringing\",\"unit\":\"20\",\"attribution\":\"caller_frame\",\"answered_by\":null,\"end_reason\":null,\"age_ms\":1000");
    tick(C300X_CALL_RINGING_TIMEOUT_MS);
    expect(nth("call.ended", 1), "\"reason\":\"timeout\"");
    tick(C300X_CALL_RINGING_TIMEOUT_MS + C300X_CALL_ENDED_KEEP_MS);
    assert(c300x_calls_timeout_ms(&calls, 200000) == -1);
    assert(c300x_outdoor_units_json(&units, json, sizeof(json)));
    expect(json, "\"default_unit\":\"20\",\"archive\":\"missing\",\"units\":[{\"id\":\"20\",\"where\":\"20\",\"action_where\":\"20\",\"lock_where\":\"20\",\"name\":\"\",\"source\":\"default\",\"default\":true}]");
    for (int index = 0; index < 20; index++) {
        ring_with_caller(200000 + index * 5000, "*8*9#1#4*20##");
        c300x_calls_end(&calls, &sink, calls.items[0].state == C300X_CALL_RINGING ? calls.items[0].id : "", "hangup", 0);
        for (int slot = 0; slot < C300X_MAX_CALLS; slot++) {
            if (calls.items[slot].state == C300X_CALL_RINGING) c300x_calls_end(&calls, &sink, calls.items[slot].id, "hangup", 200000 + index * 5000 + 1000);
        }
    }
    assert(c300x_calls_json(&calls, 300000, json, sizeof(json)));
}

/* A frame that names the plain address of a unit behind an apartment
 * interface (20 for 20#2) is that unit: no phantom unit, no second id. */
static void plain_address_is_the_qualified_unit(void)
{
    int changed;
    reset(ARCHIVE_THREE);
    int gate = c300x_outdoor_units_find_id(&units, "20");
    assert(gate >= 0);
    assert(c300x_outdoor_units_note_caller(&units, "20", &changed) == gate && !changed && units.count == 3);
    frame("*8*1#5#4#20*11##", 0);
    expect(nth("call.view_started", 1), "\"unit\":\"20\"");
    assert(units.count == 3 && count("outdoor_units.changed") == 0);
    reset(NULL);
    assert(c300x_outdoor_units_note_caller(&units, "20#2", &changed) == 0 && changed);
    assert(c300x_outdoor_units_note_caller(&units, "20", &changed) == 0 && !changed && units.count == 1);
    assert(c300x_outdoor_units_note_caller(&units, "23", &changed) == 1 && changed);
    assert(c300x_outdoor_units_note_caller(&units, "23#1", &changed) == 1 && units.count == 2);
    assert(strcmp(units.items[1].id, "23") == 0 && strcmp(units.items[1].where, "23#1") == 0);
    for (int a = 0; a < units.count; a++) {
        for (int b = a + 1; b < units.count; b++) assert(strcmp(units.items[a].id, units.items[b].id) != 0);
    }
}

/* Seen units are kept in a file: after an agent restart the station's
 * units are the same. */
static void seen_units_survive_restart(void)
{
    char path[] = "/var/tmp/c300x-seen-units-XXXXXX";
    int changed;
    int fd = mkstemp(path);
    assert(fd >= 0);
    close(fd);
    reset(ARCHIVE_THREE);
    assert(c300x_outdoor_units_note_caller(&units, "23", &changed) == 3 && changed);
    assert(c300x_outdoor_units_note_caller(&units, "24#1", &changed) == 4 && changed);
    assert(c300x_outdoor_units_save_seen(&units, path));
    reset(ARCHIVE_THREE);
    assert(units.count == 3);
    c300x_outdoor_units_load_seen(&units, path);
    assert(units.count == 5);
    assert(strcmp(units.items[3].id, "23") == 0 && strcmp(units.items[3].source, "seen") == 0);
    assert(strcmp(units.items[4].id, "24_1") == 0 && strcmp(units.items[4].where, "24#1") == 0);
    c300x_outdoor_units_load_seen(&units, path);
    assert(units.count == 5);
    build(ARCHIVE_THREE, CONF);
    assert(units.count == 5);
    unlink(path);
    reset(ARCHIVE_THREE);
    c300x_outdoor_units_load_seen(&units, path);
    assert(units.count == 3);
}

/* archive.xml names outdoor units only in its outdoor-unit object (cid
 * 10050): the <ist> without cid. Locks (cid 10060), actuators (3008), the
 * stair light (2009), cameras and intercoms are none; an <ist> attribute it
 * lacks is its <obj>'s. */
static const char *ARCHIVE_SAMPLE =
    "<archive><obj where=\"0\" cid=\"10050\" descr=\"X\" lock=\"0\" id=\"10050\" dev=\"2\" staircase=\"0\">"
    "<ist where=\"0\" cid=\"10060\" descr=\"L0\" uii=\"101\"/><ist where=\"1\" cid=\"10060\" descr=\"L1\" uii=\"109\"/>"
    "<ist where=\"2\" cid=\"10060\" descr=\"L2\" uii=\"112\"/><ist where=\"0#2\" descr=\"Haust\xc3\xbcr\" uii=\"114\"/>"
    "<ist where=\"1\" descr=\"Garten\" uii=\"115\"/><ist where=\"2\" descr=\"Garage\" uii=\"116\"/></obj>"
    "<obj where=\"0\" cid=\"10053\" descr=\"g\" id=\"10053\" dev=\"1\"/>"
    "<obj where=\"0\" cid=\"10052\" descr=\"g\" id=\"10052\" dev=\"1\"/></archive>";

static void archive_objects_by_cid(void)
{
    static const char *const others =
        "<archive><obj cid=\"3008\" dev=\"2\" where=\"0\" descr=\"Generic\"><ist where=\"5\" descr=\"Gate opener\" uii=\"1\"/></obj>"
        "<obj cid=\"10052\" dev=\"1\" where=\"0\" descr=\"Intercom\"><ist where=\"3\" descr=\"Kitchen\" uii=\"2\"/></obj>"
        "<obj cid=\"10051\" dev=\"4\" where=\"0\"><ist where=\"1\" descr=\"Camera\" uii=\"3\"/></obj>"
        "<obj cid=\"2009\" dev=\"2\"><ist descr=\"Stairs\" uii=\"4\"/></obj>"
        "<obj cid=\"10050\" dev=\"2\" where=\"7\" descr=\"Panel\"><ist cid=\"10060\" dev=\"5\" where=\"1\" lkid=\"a\"/>"
        "<ist uii=\"5\"/><ist where=\"3\" dev=\"\" descr=\"No dev\"/><ist where=\"9 9\" descr=\"Bad\"/></obj>"
        "<object cid=\"10050\"><ist where=\"8\"/></object></archive>";
    struct c300x_station_archive station;

    reset(ARCHIVE_SAMPLE);
    assert(units.count == 3);
    expect(units.items[0].where, "20#2");
    assert(strcmp(units.items[0].name, "Haust\xc3\xbcr") == 0);
    assert(strcmp(units.items[1].where, "21") == 0 && strcmp(units.items[1].name, "Garten") == 0);
    assert(strcmp(units.items[2].where, "22") == 0 && strcmp(units.items[2].name, "Garage") == 0);
    reset(others);
    c300x_station_archive_parse(&station, others, CONF);
    assert(station.unit_count == 2);
    /* An <ist> without where or descr takes its <obj>'s; an empty dev is the default 2. */
    assert(strcmp(station.units[0].where, "27") == 0 && strcmp(station.units[0].name, "Panel") == 0);
    assert(strcmp(station.units[1].where, "23") == 0 && strcmp(station.units[1].name, "No dev") == 0);
    assert(units.count == 3 && strcmp(units.items[2].source, "default") == 0);
}

/* conf.xml's default unit 20 and the archive's 20#2 (behind an apartment
 * interface) are one door: one unit with the archive's name and where and
 * the default unit's id, the same with and without the archive. */
static void default_unit_keeps_its_id(void)
{
    char json[2048];
    int changed;

    reset(ARCHIVE_SAMPLE);
    assert(units.count == 3 && units.default_index == 0);
    assert(strcmp(units.items[0].id, "20") == 0 && strcmp(units.items[0].where, "20#2") == 0);
    assert(strcmp(units.items[0].source, "archive") == 0 && strcmp(units.items[0].action_where, "20") == 0);
    assert(c300x_outdoor_units_json(&units, json, sizeof(json)));
    expect(json, "\"default_unit\":\"20\",\"archive\":\"ok\",\"units\":[{\"id\":\"20\",\"where\":\"20#2\","
                 "\"action_where\":\"20\",\"lock_where\":\"20\",\"name\":\"Haust\xc3\xbcr\",\"source\":\"archive\",\"default\":true},"
                 "{\"id\":\"21\"");
    assert(strstr(json, "20_2") == NULL);
    /* Caller and view frames of the door name that unit, never a second one. */
    assert(c300x_outdoor_units_note_caller(&units, "20#2", &changed) == 0 && !changed);
    assert(c300x_outdoor_units_note_caller(&units, "20", &changed) == 0 && !changed && units.count == 3);
    /* Without the archive the same door has the same id. */
    reset(NULL);
    assert(units.count == 1 && strcmp(units.items[0].id, "20") == 0);
    /* An archive unit at the plain default address is the default; 20#2 stays its own unit. */
    reset("<archive><obj cid=\"10050\" dev=\"2\"><ist where=\"0#2\" descr=\"Behind\"/>"
          "<ist where=\"0\" descr=\"Front\"/></obj></archive>");
    assert(units.count == 2 && units.default_index == 1 && strcmp(units.items[1].id, "20") == 0);
    assert(strcmp(units.items[0].id, "20_2") == 0);
}

int main(int argc, char **argv)
{
    static const struct { const char *name; void (*run)(void); } cases[] = {
        {"single_unit_capture", single_unit_capture},
        {"unanswered_capture", unanswered_capture},
        {"station_answer", station_answer},
        {"app_answer_end_frame_first", app_answer_end_frame_first},
        {"display_guard", display_guard},
        {"unit_behind_interface", unit_behind_interface},
        {"two_units_within_one_second", two_units_within_one_second},
        {"caller_missing", caller_missing},
        {"caller_late", caller_late},
        {"stale_call_id", stale_call_id},
        {"rings_of_one_session", rings_of_one_session},
        {"hangup_reason", hangup_reason},
        {"view_and_media_closed", view_and_media_closed},
        {"timeouts_and_json", timeouts_and_json},
        {"plain_address_is_the_qualified_unit", plain_address_is_the_qualified_unit},
        {"seen_units_survive_restart", seen_units_survive_restart},
        {"archive_objects_by_cid", archive_objects_by_cid},
        {"default_unit_keeps_its_id", default_unit_keeps_its_id},
    };
    for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]); index++) {
        if (argc < 2 || strcmp(argv[1], cases[index].name) == 0) {
            cases[index].run();
            printf("ok %s\n", cases[index].name);
        }
    }
    return 0;
}
