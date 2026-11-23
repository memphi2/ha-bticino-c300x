/* The C100X activation state machine with a fake payload and an injected clock. */
#include "../src/c100x_activation.h"
#include "../src/device_detect.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define GENERATION "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
#define MINUTE 60000LL

static char directory[256], bundle[300], state[300], log_path[300];

static void write_file(const char *path, const char *text)
{
    FILE *file = fopen(path, "w");
    assert(file != NULL);
    fputs(text, file);
    fclose(file);
}

static void set_state(const char *phase, int switched, int confirmed, int reboot_due)
{
    char text[512];
    snprintf(text, sizeof(text),
        "{\"ok\":true,\"state\":\"installed\",\"runtime_verified\":false,\"phase\":\"%s\",\"trial_switched\":%s,"
        "\"confirmed\":%s,\"reboot_due\":%s,\"generation\":\"%s\",\"available\":\"%s\",\"last_result\":\"\"}\n",
        phase, switched ? "true" : "false", confirmed ? "true" : "false", reboot_due ? "true" : "false",
        strcmp(phase, "stock") ? GENERATION : "", GENERATION);
    write_file(state, text);
}

/* Each action is logged; prepare, recover, restore and a passing check move the state on. */
static void make_bundle(void)
{
    /* In the working directory the caller gives, removed with it. */
    snprintf(directory, sizeof(directory), "./c100x-activation-XXXXXX");
    assert(mkdtemp(directory) != NULL);
    snprintf(bundle, sizeof(bundle), "%s/bundle.sh", directory);
    snprintf(state, sizeof(state), "%s/state", directory);
    snprintf(log_path, sizeof(log_path), "%s/log", directory);
    setenv("FAKE_STATE", state, 1);
    setenv("FAKE_LOG", log_path, 1);
    setenv("FAKE_DIR", directory, 1);
    write_file(bundle,
        "printf '%s\\n' \"$1\" >> \"$FAKE_LOG\"\n"
        "g=" GENERATION "\n"
        "head='{\"ok\":true,\"state\":\"installed\",\"runtime_verified\":false,\"phase\":'\n"
        "case \"$1\" in\n"
        "status) [ -e \"$FAKE_DIR/status_fails\" ] && { echo 'c100x_display: unsupported GUI binary' >&2; exit 1; }; cat \"$FAKE_STATE\" ;;\n"
        "prepare) printf '%s\"prepared\",\"trial_switched\":true,\"confirmed\":false,\"reboot_due\":false,\"generation\":\"%s\",\"available\":\"%s\",\"last_result\":\"\"}\\n' \"$head\" $g $g > \"$FAKE_STATE\"; echo '{\"ok\":true}' ;;\n"
        "recover) printf '%s\"stock\",\"trial_switched\":false,\"confirmed\":false,\"reboot_due\":false,\"generation\":\"\",\"available\":\"%s\",\"last_result\":\"interrupted\"}\\n' \"$head\" $g > \"$FAKE_STATE\"; echo '{\"ok\":true}' ;;\n"
        "restore) printf '%s\"stock\",\"trial_switched\":false,\"confirmed\":false,\"reboot_due\":true,\"generation\":\"\",\"available\":\"%s\",\"last_result\":\"restored\"}\\n' \"$head\" $g > \"$FAKE_STATE\"; echo '{\"ok\":true}' ;;\n"
        "boot-confirm) [ -e \"$FAKE_DIR/confirm_passes\" ] || { echo 'c100x_display: readiness not confirmed; trial retained' >&2; exit 1; }\n"
        "  printf '%s\"installed\",\"trial_switched\":false,\"confirmed\":true,\"reboot_due\":false,\"generation\":\"%s\",\"available\":\"%s\",\"last_result\":\"confirmed\"}\\n' \"$head\" $g $g > \"$FAKE_STATE\"; echo '{\"ok\":true,\"runtime_verified\":true}' ;;\n"
        "esac\n");
}

static int log_count(const char *action)
{
    char line[64];
    int count = 0;
    FILE *file = fopen(log_path, "r");
    if (file == NULL) return 0;
    while (fgets(line, sizeof(line), file) != NULL) {
        line[strcspn(line, "\n")] = '\0';
        count += strcmp(line, action) == 0;
    }
    fclose(file);
    return count;
}

static struct c100x_activation_inputs idle_station(long long now)
{
    return (struct c100x_activation_inputs){.now_ms = now, .door_events = 1, .reboot_allowed = 1};
}

/* Ticks until no job runs; the injected clock stands still meanwhile. */
static int settle(struct c100x_activation *activation, const struct c100x_activation_inputs *inputs)
{
    int reboots = 0;
    for (int round = 0; round < 2000; round++) {
        reboots += c100x_activation_tick(activation, inputs);
        if (!c100x_activation_busy(activation) && !activation->refresh) return reboots;
        usleep(5000);
    }
    assert(!"job did not finish");
    return reboots;
}

static void start_with(struct c100x_activation *activation, long long now)
{
    struct c100x_activation_inputs inputs = idle_station(now);
    c100x_activation_init(activation, bundle);
    assert(activation->enabled);
    assert(settle(activation, &inputs) == 0 || 1);
    assert(activation->known);
}

/* Steps the clock in one-second ticks; returns how many reboots were asked for. */
static int run_for(struct c100x_activation *activation, struct c100x_activation_inputs *inputs, long long until)
{
    int reboots = 0;
    while (inputs->now_ms < until) {
        inputs->now_ms += 1000;
        reboots += settle(activation, inputs);
    }
    return reboots;
}

static void test_reboot_only_after_the_idle_window_and_at_most_once(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    set_state("prepared", 1, 0, 0);
    start_with(&activation, inputs.now_ms);
    assert(settle(&activation, &inputs) == 0);
    assert(!strcmp(activation.blocked, "waiting_for_idle"));
    assert(run_for(&activation, &inputs, inputs.now_ms + 119000) == 0);
    assert(run_for(&activation, &inputs, inputs.now_ms + 1000) == 1);
    assert(!strcmp(activation.blocked, "reboot_requested"));
    /* Still up much later: one more request, then it gives up. */
    assert(run_for(&activation, &inputs, inputs.now_ms + 10 * MINUTE + 2 * MINUTE) == 1);
    assert(run_for(&activation, &inputs, inputs.now_ms + 30 * MINUTE) == 0);
    assert(!strcmp(activation.blocked, "reboot_failed"));
    c100x_activation_close(&activation);
}

static void expect_blocked(struct c100x_activation_inputs inputs, const char *frame, const char *reason)
{
    struct c100x_activation activation;
    /* Until the station has been up two minutes; else five minutes, past the idle window. */
    long long until = inputs.now_ms < 2 * MINUTE ? 2 * MINUTE - 1000 : inputs.now_ms + 5 * MINUTE;
    set_state("prepared", 1, 0, 0);
    start_with(&activation, inputs.now_ms);
    if (frame != NULL) c100x_activation_door_frame(&activation, frame, inputs.now_ms);
    assert(run_for(&activation, &inputs, until) == 0);
    assert(!strcmp(activation.blocked, reason));
    c100x_activation_close(&activation);
}

static void test_never_during_a_call_ring_stream_announcement_or_job(void)
{
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    expect_blocked(inputs, "*8*1#1#4#21*10##", "call_active");
    expect_blocked(inputs, "*8*2#1#4#21*10##", "call_active");
    inputs.station_busy = 1;
    expect_blocked(inputs, NULL, "station_busy");
    inputs = idle_station(10 * MINUTE);
    inputs.lease = 1;
    inputs.lease_blocked = 1;
    inputs.lease_generation = GENERATION;
    expect_blocked(inputs, NULL, "display_busy");
    inputs = idle_station(10 * MINUTE);
    inputs.door_events = 0;
    expect_blocked(inputs, NULL, "call_state_unknown");
    inputs = idle_station(10 * MINUTE);
    inputs.reboot_allowed = 0;
    expect_blocked(inputs, NULL, "reboot_disabled");
    inputs = idle_station(0);
    expect_blocked(inputs, NULL, "starting");
    /* A call that ended, and a lock frame, hold the reboot only for the idle window. */
    {
        struct c100x_activation activation;
        inputs = idle_station(10 * MINUTE);
        set_state("prepared", 1, 0, 0);
        start_with(&activation, inputs.now_ms);
        c100x_activation_door_frame(&activation, "*8*1#1#4#21*10##", inputs.now_ms);
        c100x_activation_door_frame(&activation, "*8*3#1#4#21*10##", inputs.now_ms);
        assert(run_for(&activation, &inputs, inputs.now_ms + 60000) == 0);
        assert(!strcmp(activation.blocked, "call_recent"));
        c100x_activation_door_frame(&activation, "*8*19*21##", inputs.now_ms);
        assert(run_for(&activation, &inputs, inputs.now_ms + 60000) == 0);
        assert(run_for(&activation, &inputs, inputs.now_ms + 125000) == 1);
        c100x_activation_close(&activation);
    }
}

static void test_trial_waits_settles_checks_three_times_then_reboots(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    set_state("trial", 1, 0, 0);
    start_with(&activation, inputs.now_ms);
    /* No display lease: no check and no reboot. */
    assert(run_for(&activation, &inputs, inputs.now_ms + 5 * MINUTE) == 0);
    assert(log_count("boot-confirm") == 0);
    inputs.lease = 1;
    inputs.lease_generation = GENERATION;
    assert(run_for(&activation, &inputs, inputs.now_ms + 14000) == 0);
    assert(log_count("boot-confirm") == 0);
    assert(run_for(&activation, &inputs, inputs.now_ms + 2000) == 0);
    assert(log_count("boot-confirm") == 1);
    assert(strstr(activation.error, "trial retained") != NULL);
    assert(run_for(&activation, &inputs, inputs.now_ms + 2 * MINUTE + 5000) == 0);
    assert(log_count("boot-confirm") == 3);
    assert(log_count("recover") == 0);
    /* The last check failed: the start rule rolls back after an idle reboot. */
    assert(run_for(&activation, &inputs, inputs.now_ms + MINUTE + 2 * MINUTE + 5000) == 1);
    assert(log_count("boot-confirm") == 3);
    assert(!c100x_activation_confirmed(&activation));
    c100x_activation_close(&activation);
}

static void test_trial_confirms_without_reboot(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    char json[1024];
    set_state("trial", 1, 0, 0);
    {
        char marker[320];
        snprintf(marker, sizeof(marker), "%s/confirm_passes", directory);
        write_file(marker, "");
    }
    start_with(&activation, inputs.now_ms);
    inputs.lease = 1;
    inputs.lease_generation = GENERATION;
    assert(!c300x_device_display_features());
    assert(run_for(&activation, &inputs, inputs.now_ms + 20000) == 0);
    assert(c100x_activation_confirmed(&activation));
    assert(c300x_device_display_features());
    assert(run_for(&activation, &inputs, inputs.now_ms + 10 * MINUTE) == 0);
    assert(c100x_activation_json(&activation, json, sizeof(json)));
    assert(strstr(json, "\"phase\":\"installed\",") && strstr(json, "\"confirmed\":true,"));
    assert(strstr(json, "\"activate\":false,\"restore\":true,"));
    c100x_activation_close(&activation);
}

static void test_trial_without_display_fails_after_the_wait(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    set_state("trial", 1, 0, 0);
    start_with(&activation, inputs.now_ms);
    assert(run_for(&activation, &inputs, inputs.now_ms + 10 * MINUTE - 2000) == 0);
    assert(run_for(&activation, &inputs, inputs.now_ms + 2 * MINUTE + 5000) == 1);
    assert(log_count("boot-confirm") == 0);
    c100x_activation_close(&activation);
}

static void test_interrupted_prepare_recovers_without_reboot(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    set_state("prepared", 0, 0, 0);
    start_with(&activation, inputs.now_ms);
    assert(run_for(&activation, &inputs, inputs.now_ms + 10 * MINUTE) == 0);
    assert(log_count("recover") == 1);
    assert(activation.phase == C100X_PHASE_STOCK);
    c100x_activation_close(&activation);
}

static void test_unknown_status_fails_closed(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    char marker[320], json[1024];
    snprintf(marker, sizeof(marker), "%s/status_fails", directory);
    write_file(marker, "");
    set_state("prepared", 1, 0, 0);
    c100x_activation_init(&activation, bundle);
    assert(run_for(&activation, &inputs, inputs.now_ms + 10 * MINUTE) == 0);
    assert(!activation.known);
    assert(!strcmp(activation.error, "unsupported gui binary") || strstr(activation.error, "unsupported"));
    assert(!strcmp(c100x_activation_request(&activation, C100X_ACTION_PREPARE), "c100x_display_status_unknown"));
    assert(c100x_activation_json(&activation, json, sizeof(json)));
    assert(strstr(json, "\"status_known\":false,") && strstr(json, "\"activate\":false,\"restore\":false,"));
    unlink(marker);
    c100x_activation_close(&activation);
    c100x_activation_init(&activation, "/nonexistent/bundle.sh");
    assert(run_for(&activation, &inputs, inputs.now_ms + MINUTE) == 0);
    assert(!activation.known && !strcmp(activation.error, "payload unavailable"));
    c100x_activation_close(&activation);
}

static void test_activate_and_restore_requests(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    set_state("stock", 0, 0, 0);
    start_with(&activation, inputs.now_ms);
    assert(c100x_activation_request(&activation, C100X_ACTION_PREPARE) == NULL);
    assert(!strcmp(c100x_activation_request(&activation, C100X_ACTION_RESTORE), "c100x_display_busy"));
    assert(settle(&activation, &inputs) == 0);
    assert(activation.phase == C100X_PHASE_PREPARED);
    assert(!strcmp(c100x_activation_request(&activation, C100X_ACTION_PREPARE), "c100x_display_trial_pending"));
    assert(c100x_activation_request(&activation, C100X_ACTION_RESTORE) == NULL);
    assert(settle(&activation, &inputs) == 0);
    assert(activation.reboot_due && activation.phase == C100X_PHASE_STOCK);
    assert(run_for(&activation, &inputs, inputs.now_ms + 125000) == 1);
    c100x_activation_close(&activation);
}

/* Key beep, alerts, bridge and ringer mute: only with the confirmed adapter. */
static void test_display_functions_follow_the_confirmed_adapter(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    set_state("installed", 0, 0, 0);
    start_with(&activation, inputs.now_ms);
    assert(settle(&activation, &inputs) == 0);
    assert(activation.known && !c300x_device_display_features());
    set_state("installed", 0, 1, 0);
    c100x_activation_close(&activation);
    start_with(&activation, inputs.now_ms);
    assert(settle(&activation, &inputs) == 0);
    assert(c300x_device_display_features());
    assert(c100x_activation_request(&activation, C100X_ACTION_RESTORE) == NULL);
    assert(settle(&activation, &inputs) == 0);
    assert(!c100x_activation_confirmed(&activation) && !c300x_device_display_features());
    c100x_activation_close(&activation);
}

static void test_inert_without_a_c100x(void)
{
    struct c100x_activation activation;
    struct c100x_activation_inputs inputs = idle_station(10 * MINUTE);
    struct pollfd fd;
    c100x_activation_init(&activation, bundle);
    assert(!activation.enabled);
    assert(c100x_activation_prepare(&activation, &fd) == -1);
    c100x_activation_door_frame(&activation, "*8*1#1#4#21*10##", inputs.now_ms);
    assert(activation.call_open_ms == 0);
    assert(run_for(&activation, &inputs, inputs.now_ms + 10 * MINUTE) == 0);
    assert(!strcmp(c100x_activation_request(&activation, C100X_ACTION_PREPARE), "c100x_required"));
    assert(log_count("status") == 0);
    c100x_activation_close(&activation);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    make_bundle();
    if (!strcmp(argv[1], "inert")) test_inert_without_a_c100x();
    else if (!strcmp(argv[1], "idle")) test_reboot_only_after_the_idle_window_and_at_most_once();
    else if (!strcmp(argv[1], "busy")) test_never_during_a_call_ring_stream_announcement_or_job();
    else if (!strcmp(argv[1], "trial-fails")) test_trial_waits_settles_checks_three_times_then_reboots();
    else if (!strcmp(argv[1], "trial-confirms")) test_trial_confirms_without_reboot();
    else if (!strcmp(argv[1], "no-display")) test_trial_without_display_fails_after_the_wait();
    else if (!strcmp(argv[1], "interrupted")) test_interrupted_prepare_recovers_without_reboot();
    else if (!strcmp(argv[1], "unknown")) test_unknown_status_fails_closed();
    else if (!strcmp(argv[1], "requests")) test_activate_and_restore_requests();
    else if (!strcmp(argv[1], "features")) test_display_functions_follow_the_confirmed_adapter();
    else assert(!"unknown case");
    return 0;
}
