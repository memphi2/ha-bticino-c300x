/* The call table and the outdoor units, fed with the frame sequences of the
 * owner's captures (one unit, 1.7.19) and of a three-unit installation
 * (20#2 behind an apartment interface, 21, 22). Times are the captures'. */
#include <assert.h>
#include <stdio.h>
#include <string.h>

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

static void reset(const char *archive)
{
    memset(&units, 0, sizeof(units));
    c300x_outdoor_units_build(&units, archive, archive ? "ok" : "missing", CONF, "20", "20");
    c300x_calls_init(&calls, "8f3a1c2e");
    total = 0;
}

static void ring(long long now) { if (c300x_calls_ring(&calls, &sink, "*8*1#1#4#21*11##", now, data, sizeof(data))) record(NULL, "doorbell.pressed", data); }
static void frame(const char *text, long long now) { c300x_calls_frame(&calls, &sink, text, now); }

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
    ring(0);
    frame("*8*9#1#4*20##", 166);
    assert(count("doorbell.pressed") == 1);
    expect(nth("doorbell.pressed", 1), "\"call_id\":\"8f3a1c2e-1\",\"unit\":null,\"attribution\":\"pending\"");
    assert(count("call.caller_identified") == 1);
    expect(nth("call.caller_identified", 1), "\"unit\":\"20\",\"where\":\"20\",\"action_where\":\"20\",\"attribution\":\"caller_frame\"");
    c300x_calls_tick(&calls, &sink, 1500);
    assert(count("call.caller_identified") == 1);
    /* POST .../answer at 13043; the agent's answer reports the view at 13073. */
    c300x_calls_answer_started(&calls, "8f3a1c2e-1");
    c300x_calls_answer_seen(&calls, &sink, 13073);
    expect(nth("call.answered", 1), "\"answered_by\":\"ha\"");
    frame("*8*2#1#4*11##", 13173);
    frame("*8*100#1#4*20##", 13305);
    c300x_calls_answer_seen(&calls, &sink, 13395);
    assert(count("call.answered") == 1 && count("call.ended") == 0);
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    /* POST .../hangup at 19900. */
    c300x_calls_end(&calls, &sink, "8f3a1c2e-1", "hangup", 19900);
    expect(nth("call.ended", 1), "\"unit\":\"20\",\"kind\":\"ring\",\"reason\":\"hangup\"");
    assert(c300x_calls_timeout_ms(&calls, 19900) == -1);
    assert(c300x_calls_current(&calls) == NULL);
}

/* c300x-unanswered-ring-20260708-134502: no *8*100 at all; the station
 * cancels at 29.9 s and the agent's media close ends the call. */
static void unanswered_capture(void)
{
    reset(NULL);
    ring(0);
    frame("*8*9#1#4*20##", 352);
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    c300x_calls_media_closed(&calls, &sink, 29951);
    expect(nth("call.ended", 1), "\"unit\":\"20\",\"kind\":\"ring\",\"reason\":\"media_closed\"");
    assert(count("call.answered") == 0);
}

/* The display answers: no answer of HA runs. */
static void station_answer(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    c300x_calls_answer_seen(&calls, &sink, 5600);
    expect(nth("call.answered", 1), "\"answered_by\":\"station\"");
    frame("*8*100#1#4*20##", 5800);
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
}

static void unit_behind_interface(void)
{
    reset(ARCHIVE_THREE);
    assert(units.count == 3);
    assert(strcmp(c300x_outdoor_units_default(&units)->id, "20_2") == 0);
    assert(strcmp(units.items[0].name, "Gate & street") == 0);
    ring_with_caller(0, "*8*9#1#4*20#2##");
    expect(nth("call.caller_identified", 1), "\"unit\":\"20_2\",\"where\":\"20#2\",\"action_where\":\"20\"");
    assert(count("outdoor_units.changed") == 0);
    ring_with_caller(60000, "*8*9#1#4*22##");
    expect(nth("call.caller_identified", 2), "\"unit\":\"22\"");
    /* Without an archive the default from conf.xml learns the qualifier. */
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20#2##");
    expect(nth("call.caller_identified", 1), "\"unit\":\"20\",\"where\":\"20#2\",\"action_where\":\"20\"");
    assert(count("outdoor_units.changed") == 1 && units.count == 1);
    c300x_outdoor_units_build(&units, NULL, "missing", CONF, "20", "20");
    assert(units.count == 1 && strcmp(units.items[0].where, "20#2") == 0 && strcmp(units.items[0].id, "20") == 0);
    ring_with_caller(60000, "*8*9#1#4*20#2##");
    assert(count("outdoor_units.changed") == 1);
}

static void two_units_within_one_second(void)
{
    reset(ARCHIVE_THREE);
    ring(0);
    ring(285);
    frame("*8*9#1#4*21##", 351);
    ring(600);
    frame("*8*9#1#4*22##", 900);
    frame("*8*9#1#4*22##", 1005);
    assert(count("doorbell.pressed") == 2);
    expect(nth("doorbell.pressed", 2), "\"call_id\":\"8f3a1c2e-2\",\"unit\":\"22\"");
    expect(nth("call.caller_identified", 1), "\"call_id\":\"8f3a1c2e-1\",\"unit\":\"21\"");
    expect(nth("call.caller_identified", 2), "\"call_id\":\"8f3a1c2e-2\",\"unit\":\"22\"");
    assert(count("call.ended") == 0);
}

static void caller_missing(void)
{
    reset(ARCHIVE_THREE);
    ring(0);
    ring(285);
    assert(c300x_calls_timeout_ms(&calls, 300) == 700);
    c300x_calls_tick(&calls, &sink, 999);
    assert(count("call.caller_identified") == 0);
    c300x_calls_tick(&calls, &sink, 1000);
    expect(nth("call.caller_identified", 1), "\"unit\":\"20_2\",\"where\":\"20#2\",\"action_where\":\"20\",\"attribution\":\"default_fallback\",\"raw\":null");
    assert(c300x_calls_timeout_ms(&calls, 1000) == C300X_CALL_RINGING_TIMEOUT_MS);
}

static void caller_late(void)
{
    reset(ARCHIVE_THREE);
    ring(0);
    ring(285);
    c300x_calls_tick(&calls, &sink, 1000);
    frame("*8*9#1#4*21##", 1100);
    frame("*8*9#1#4*20#2##", 1150);
    assert(count("doorbell.pressed") == 1 && count("call.caller_identified") == 1);
    assert(calls.caller_frames_ignored == 1);
}

static void stale_call_id(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    c300x_calls_media_closed(&calls, &sink, 20000);
    ring_with_caller(40000, "*8*9#1#4*20##");
    assert(!c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-2"));
    assert(!c300x_calls_is_current(&calls, "0badc0de-2"));
    assert(c300x_calls_unlock_allowed(&calls, "8f3a1c2e-1", "20", 40000));
    assert(!c300x_calls_unlock_allowed(&calls, "8f3a1c2e-1", "20", 80001));
    assert(!c300x_calls_unlock_allowed(&calls, "8f3a1c2e-2", "21", 40000));
}

static void second_ring_during_answered_call(void)
{
    reset(ARCHIVE_THREE);
    ring_with_caller(0, "*8*9#1#4*21##");
    c300x_calls_answer_started(&calls, "8f3a1c2e-1");
    c300x_calls_answered(&calls, &sink, "8f3a1c2e-1", "ha", 2000);
    c300x_calls_answer_seen(&calls, &sink, 2100);
    assert(count("call.answered") == 1);
    ring_with_caller(5000, "*8*9#1#4*22##");
    assert(count("doorbell.pressed") == 2);
    expect(nth("call.caller_identified", 2), "\"call_id\":\"8f3a1c2e-2\",\"unit\":\"22\"");
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    frame("*8*100#1#4*21##", 9000);
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-1"));
    c300x_calls_end(&calls, &sink, "8f3a1c2e-1", "hangup", 9000);
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-2"));
}

static void same_unit_pressed_again(void)
{
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    ring_with_caller(3000, "*8*9#1#4*20##");
    assert(count("doorbell.pressed") == 2);
    expect(nth("call.ended", 1), "\"call_id\":\"8f3a1c2e-1\",\"unit\":\"20\",\"kind\":\"ring\",\"reason\":\"superseded\"");
    assert(c300x_calls_is_current(&calls, "8f3a1c2e-2"));
}

static void sip_ring_merges(void)
{
    reset(NULL);
    ring(0);
    assert(!c300x_calls_ring(&calls, &sink, NULL, 1800, data, sizeof(data)));
    assert(c300x_calls_ring(&calls, &sink, NULL, 9000, data, sizeof(data)));
}

static void view_and_media_closed(void)
{
    reset(NULL);
    frame("*8*1#5#4#20*11##", 0);
    frame("*8*1#5#4#20*11##", 120);
    frame("*8*9#5#4*20##", 300);
    assert(count("call.view_started") == 1);
    expect(nth("call.view_started", 1), "\"unit\":\"20\"");
    assert(c300x_calls_current(&calls) == NULL);
    /* c300x-ha-first-click-click-stop-20260621-214931: *8*100#5 578 ms after the view. */
    frame("*8*100#5#4*20##", 578);
    assert(count("call.ended") == 0);
    c300x_calls_media_closed(&calls, &sink, 1660);
    expect(nth("call.ended", 1), "\"kind\":\"view\",\"reason\":\"media_closed\"");
    ring(10000);
    c300x_calls_media_closed(&calls, &sink, 12000);
    expect(nth("call.ended", 2), "\"unit\":null,\"kind\":\"ring\",\"reason\":\"media_closed\"");
}

static void timeouts_and_json(void)
{
    char json[2048];
    reset(NULL);
    ring_with_caller(0, "*8*9#1#4*20##");
    assert(c300x_calls_json(&calls, 1000, json, sizeof(json)));
    expect(json, "\"current_call_id\":\"8f3a1c2e-1\"");
    expect(json, "\"state\":\"ringing\",\"unit\":\"20\",\"attribution\":\"caller_frame\",\"answered_by\":null,\"end_reason\":null,\"age_ms\":1000");
    c300x_calls_tick(&calls, &sink, 351 + C300X_CALL_RINGING_TIMEOUT_MS);
    expect(nth("call.ended", 1), "\"reason\":\"timeout\"");
    assert(c300x_calls_timeout_ms(&calls, 100000) == -1);
    assert(c300x_outdoor_units_json(&units, json, sizeof(json)));
    expect(json, "\"default_unit\":\"20\",\"archive\":\"missing\",\"units\":[{\"id\":\"20\",\"where\":\"20\",\"action_where\":\"20\",\"lock_where\":\"20\",\"name\":\"\",\"source\":\"default\",\"default\":true}]");
    for (int index = 0; index < 20; index++) ring_with_caller(200000 + index * 5000, "*8*9#1#4*20##");
    assert(c300x_calls_json(&calls, 300000, json, sizeof(json)));
}

/* A frame that names the plain address of a unit behind an apartment
 * interface (20 for 20#2) is that unit: no phantom unit, no second id. */
static void plain_address_is_the_qualified_unit(void)
{
    int changed;
    reset(ARCHIVE_THREE);
    int gate = c300x_outdoor_units_find_id(&units, "20_2");
    assert(gate >= 0);
    assert(c300x_outdoor_units_note_caller(&units, "20", &changed) == gate && !changed && units.count == 3);
    frame("*8*1#5#4#20*11##", 0);
    expect(nth("call.view_started", 1), "\"unit\":\"20_2\"");
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

int main(int argc, char **argv)
{
    static const struct { const char *name; void (*run)(void); } cases[] = {
        {"single_unit_capture", single_unit_capture},
        {"unanswered_capture", unanswered_capture},
        {"station_answer", station_answer},
        {"unit_behind_interface", unit_behind_interface},
        {"two_units_within_one_second", two_units_within_one_second},
        {"caller_missing", caller_missing},
        {"caller_late", caller_late},
        {"stale_call_id", stale_call_id},
        {"second_ring_during_answered_call", second_ring_during_answered_call},
        {"same_unit_pressed_again", same_unit_pressed_again},
        {"sip_ring_merges", sip_ring_merges},
        {"view_and_media_closed", view_and_media_closed},
        {"timeouts_and_json", timeouts_and_json},
        {"plain_address_is_the_qualified_unit", plain_address_is_the_qualified_unit},
    };
    for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]); index++) {
        if (argc < 2 || strcmp(argv[1], cases[index].name) == 0) {
            cases[index].run();
            printf("ok %s\n", cases[index].name);
        }
    }
    return 0;
}
