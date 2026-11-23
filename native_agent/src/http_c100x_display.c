#include "http_c100x_display.h"
#include "agent_update.h"
#include "camera_update_guard.h"
#include "time_util.h"

#include <stdio.h>

void c100x_display_init(struct c100x_activation *activation, const struct c300x_config *config)
{
    char base[C300X_MAX_PATH_LEN], bundle[C300X_MAX_PATH_LEN + 32];
    int ok = agent_base_dir(config, base, sizeof(base));
    if (ok) {
        snprintf(bundle, sizeof(bundle), "%s/qml/c100x_bundle.sh", base);
    }
    c100x_activation_init(activation, ok ? bundle : NULL);
}

void c100x_display_step(struct c100x_activation *activation, const struct c300x_config *config,
    struct c300x_video *video, const struct c300x_announce *announce,
    const struct c300x_http_maintenance *maintenance, const struct c100x_gui_presence *presence,
    c300x_schedule_command_fn schedule)
{
    struct c100x_activation_inputs inputs;

    if (!activation->enabled) {
        return;
    }
    inputs = (struct c100x_activation_inputs){
        .now_ms = c300x_monotonic_ms(),
        .door_events = announce->door_events,
        .station_busy = c300x_camera_update_media_busy(video) || c300x_announce_busy(announce)
            || c300x_http_maintenance_busy(maintenance),
        .lease = presence->fd >= 0,
        .lease_blocked = presence->blocked,
        .lease_generation = presence->generation,
        .reboot_allowed = config->maintenance_enabled && config->maintenance_reboot_enabled,
    };
    /* The agent's own reboot: no SSH start, the configured delay. */
    if (c100x_activation_tick(activation, &inputs)
        && !schedule(C300X_REBOOT_PROGRAM, NULL, config->maintenance_reboot_delay_ms)) {
        activation->blocked = "reboot_failed";
    }
}
