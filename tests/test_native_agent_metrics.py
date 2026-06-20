from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _c300x_run_loop_body(text: str) -> str:
    run_body = text.rsplit("int c300x_run", maxsplit=1)[1]
    return run_body.split("for (;;) {", maxsplit=1)[1].split(
        "if (poll(poll_fds",
        maxsplit=1,
    )[0]


def test_native_agent_metrics_threshold_uses_last_dispatched_baseline() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert "struct system_metrics_sample system_metrics_last_dispatched;" in text
    assert "int system_metrics_dispatched_initialized;" in text
    assert (
        "c300x_system_metrics_changed(\n"
        "            config,\n"
        "            &runtime->system_metrics_last_dispatched,\n"
        "            &sample\n"
        "        )"
        in text
    )
    watchdog = (
        ROOT / "native_agent" / "src" / "system_metrics_watchdog.c"
    ).read_text(encoding="utf-8")
    assert "metric_changed_points(" in watchdog


def test_native_agent_metrics_reads_memory_only_inside_metrics_sample() -> None:
    text = (ROOT / "native_agent" / "src" / "system_metrics.c").read_text(
        encoding="utf-8"
    )
    sample_body = text.rsplit(
        "int c300x_system_metrics_read_sample",
        maxsplit=1,
    )[1].split("int c300x_system_metrics_json", maxsplit=1)[0]

    assert "read_memory_metrics(" in sample_body
    assert text.count("read_memory_metrics(") == 2
    watchdog = (
        ROOT / "native_agent" / "src" / "system_metrics_watchdog.c"
    ).read_text(encoding="utf-8")
    assert "static int metric_changed_points(" in watchdog


def test_native_agent_metrics_does_not_mark_unsent_samples_as_dispatched() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    dispatch_body = text.split("static void system_metrics_dispatch_if_due", maxsplit=1)[
        1
    ].split("static int map_openwebnet_event", maxsplit=1)[0]

    assert (
        "if (!system_metrics_monitor_active(config)) {\n"
        "        runtime->system_metrics_next_sample_at = now + "
        "config->system_metrics_heartbeat_seconds;\n"
        "        return;\n"
        "    }\n"
        in dispatch_body
    )
    assert dispatch_body.index("c300x_system_metrics_json(&sample") < (
        dispatch_body.index("system_metrics_mark_dispatched(runtime, &sample, now)")
    )


def test_native_agent_metrics_monitor_wakes_without_subscribers_for_safety() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    poll_body = _c300x_run_loop_body(text)

    assert "if (system_metrics_monitor_active(config))" in poll_body


def test_native_agent_metrics_dispatch_loop_runs_internal_monitor() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert (
        "if (system_metrics_monitor_active(config)) {\n"
        "            system_metrics_dispatch_if_due(config, runtime, time(NULL));\n"
        "        }"
        in text
    )


def test_native_agent_metrics_push_high_cpu_samples_for_watchdog() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    dispatch_body = text.split("static void system_metrics_dispatch_if_due", maxsplit=1)[
        1
    ].split("static int map_openwebnet_event", maxsplit=1)[0]

    assert "|| (sample.has_cpu_usage && sample.cpu_usage_percent >= 90.0)" in dispatch_body
    assert (
        "if (!has_matching_subscription(runtime, \"system.metrics_changed\")) {\n"
        "        return;\n"
        "    }"
        in dispatch_body
    )
    assert dispatch_body.index(
        "SYSTEM_METRICS_CPU_WATCHDOG(runtime, &sample, now)"
    ) < dispatch_body.index(
        "if (!has_matching_subscription(runtime, \"system.metrics_changed\"))"
    )


def test_native_agent_metrics_cpu_watchdog_stops_owned_media_only() -> None:
    text = (
        ROOT / "native_agent" / "src" / "system_metrics_watchdog.c"
    ).read_text(encoding="utf-8")

    assert "#define C300X_SYSTEM_METRICS_CPU_WATCHDOG_PERCENT 90.0" in text
    assert "#define C300X_SYSTEM_METRICS_CPU_WATCHDOG_SECONDS 300" in text
    assert "*high_cpu_since = now;" in text
    assert "*tripped_at = now;" in text
    assert "c300x_video_doorbell_call_hangup(video);" in text
    assert "c300x_video_home_call_stop(video);" in text
    assert "c300x_video_stop(video);" in text
    assert "!status.external_media_active" in text


def test_native_agent_metrics_snapshot_registration_is_subscriber_gated() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    post_body = text.split("static void handle_subscriptions_post", maxsplit=1)[1].split(
        "static void handle_display_bridge_status",
        maxsplit=1,
    )[0]
    dispatch_now_body = text.rsplit(
        "static void system_metrics_dispatch_now",
        maxsplit=1,
    )[1].split("static void system_metrics_dispatch_if_due", maxsplit=1)[0]

    assert "c300x_system_metrics_read_sample(" not in post_body
    assert (
        'if (subscription_matches_event(&runtime->subscriptions[0], "system.metrics_changed"))'
        in post_body
    )
    assert dispatch_now_body.index("system_metrics_watch_active") < (
        dispatch_now_body.index("c300x_system_metrics_read_sample")
    )


def test_native_agent_metrics_initializes_internal_monitor_without_subscribers() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    init_body = text.split("static void system_metrics_init", maxsplit=1)[1].split(
        "static void system_metrics_mark_dispatched",
        maxsplit=1,
    )[0]

    assert init_body.index("system_metrics_monitor_active") < init_body.index(
        "c300x_system_metrics_read_sample"
    )


def test_native_agent_maintenance_requires_token_even_in_no_auth_mode() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    maintenance_body = text.rsplit(
        "static int maintenance_authorized",
        maxsplit=1,
    )[1].split("static int maintenance_auth_available", maxsplit=1)[0]

    assert "if (config->api_no_auth)" not in maintenance_body
    assert "config->maintenance_admin_token[0] == '\\0'" in maintenance_body


def test_native_agent_device_user_status_does_not_expose_sip_identity() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = text.split("static void device_user_status_body", maxsplit=1)[1].split(
        "static void handle_device_user_get",
        maxsplit=1,
    )[0]

    assert '"\\"domain_present\\":%s,"' in body
    assert '"\\"media_identity_available\\":%s,"' in body
    assert '"\\"from_aor\\"' not in body
    assert '"\\"to_aor\\"' not in body
    assert '"\\"device_domain\\"' not in body
    assert '"\\"homeassistant_aor\\"' not in body
    assert '"\\"route_int\\"' not in body
    assert '"\\"route_ext\\"' not in body
    assert '"\\"digest\\"' not in body
    assert "device_routing_update_sha256" not in body
    assert "device_routing_update_backup_sha256" not in body


def test_native_agent_device_user_status_reports_read_availability() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = text.split("static void device_user_status_body", maxsplit=1)[1].split(
        "static void handle_device_user_get",
        maxsplit=1,
    )[0]
    read_status = (ROOT / "native_agent" / "src" / "device_user.c").read_text(
        encoding="utf-8"
    )

    assert '"\\"ok\\":%s,"' in body
    assert '"\\"status_available\\":%s,"' in body
    assert "status->status_available ? \"true\" : \"false\"" in body
    assert "status->status_available = 1;" in read_status
    assert "status->status_available = 0;" in read_status


def test_native_agent_self_test_keeps_unavailable_device_user_unknown() -> None:
    text = (ROOT / "native_agent" / "src" / "self_test.c").read_text(
        encoding="utf-8"
    )

    assert "user_ok = -1;" in text
    assert "device_routing_ok = -1;" in text
    assert 'user_reason = "device_user_status_unavailable";' in text
    assert "check_json(user_ok)" in text
    assert "check_json(device_routing_ok)" in text


def test_native_agent_self_test_keeps_device_routing_independent_from_qml_label() -> None:
    text = (ROOT / "native_agent" / "src" / "self_test.c").read_text(
        encoding="utf-8"
    )
    block = text.split(
        "if (user_status.status_available && user_status.homeassistant_user_present)",
        maxsplit=1,
    )[1].split("if (!agent_init_script_present)", maxsplit=1)[0]

    assert "device_routing_ok = routing_read_ok\n                && routing_status.patched;" in block
    assert "media_user_label_patched" not in text
    assert "run_qml_status_script" not in text


def test_native_agent_device_user_keeps_homeassistant_out_of_external_route() -> None:
    text = (ROOT / "native_agent" / "src" / "device_user.c").read_text(
        encoding="utf-8"
    )

    assert "ensure_route_target(&route_int" in text
    assert "ensure_route_target(&route_ext" not in text
    assert "remove_route_target(&route_ext" in text
    assert "&& !status->route_ext_homeassistant_present" in text
    assert "user_is_homeassistant(user)" in text


def test_native_agent_device_user_removes_only_homeassistant_from_external_route(
    tmp_path: Path,
) -> None:
    test_source = tmp_path / "device_user_route_test.c"
    test_binary = tmp_path / "device_user_route_test"
    test_source.write_text(
        textwrap.dedent(
            r'''
            #include <stdio.h>
            #include <stdlib.h>
            #include <string.h>

            #include "src/string_util.c"
            #include "src/device_user.c"

            static int check_route(
                const char *initial,
                const char *expected,
                int expected_changed
            )
            {
                struct file_buffer route;
                int changed = 0;
                char error[128] = {0};

                memset(&route, 0, sizeof(route));
                route.data = strdup(initial);
                if (route.data == NULL) {
                    return 10;
                }
                route.len = strlen(initial);
                route.mode = 0644;
                route.exists = 1;
                if (!remove_route_target(&route, &changed, error, sizeof(error))) {
                    fprintf(stderr, "remove_route_target failed: %s\n", error);
                    free(route.data);
                    return 11;
                }
                if (changed != expected_changed) {
                    fprintf(stderr, "changed=%d expected=%d\n", changed, expected_changed);
                    free(route.data);
                    return 12;
                }
                if (strcmp(route.data, expected) != 0) {
                    fprintf(stderr, "route mismatch\nactual:   %s\nexpected: %s\n", route.data, expected);
                    free(route.data);
                    return 13;
                }
                free(route.data);
                return 0;
            }

            int main(void)
            {
                int rc;

                rc = check_route(
                    "<sip:alluser@example.test> <sip:c300x@example.test>, <sip:homeassistant-a1@example.test>\n"
                    "<sip:family@example.test> <sip:phone@example.test>\n",
                    "<sip:alluser@example.test> <sip:c300x@example.test>\n"
                    "<sip:family@example.test> <sip:phone@example.test>\n",
                    1
                );
                if (rc != 0) {
                    return rc;
                }
                rc = check_route(
                    "<sip:alluser@example.test> <sip:homeassistant@example.test>\n"
                    "<sip:family@example.test> <sip:phone@example.test>\n",
                    "<sip:family@example.test> <sip:phone@example.test>\n",
                    1
                );
                if (rc != 0) {
                    return rc;
                }
                rc = check_route(
                    "<sip:alluser@example.test> <sip:c300x@example.test>\n",
                    "<sip:alluser@example.test> <sip:c300x@example.test>\n",
                    0
                );
                if (rc != 0) {
                    return rc;
                }
                return 0;
            }
            '''
        ),
        encoding="utf-8",
    )

    compile_result = subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-D_DEFAULT_SOURCE",
            "-D_POSIX_C_SOURCE=200809L",
            "-I.",
            str(test_source),
            "-o",
            str(test_binary),
        ],
        cwd=ROOT / "native_agent",
        check=False,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    run_result = subprocess.run(
        [str(test_binary)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run_result.returncode == 0, run_result.stderr


def test_native_agent_device_user_bootstraps_local_only_flexisip_files(
    tmp_path: Path,
) -> None:
    flexisip_dir = tmp_path / "etc" / "flexisip"
    users_dir = flexisip_dir / "users"
    flexisip_config = tmp_path / "home" / "bticino" / "cfg" / "flexisip.conf"
    domain_file = flexisip_dir / "domain-registration.conf"
    users_file = users_dir / "users.db.txt"
    accounts_file = users_dir / "accounts.txt"
    route_int = users_dir / "route_int.conf"
    route_ext = users_dir / "route_ext.conf"
    route_conf = users_dir / "route.conf"
    test_source = tmp_path / "device_user_bootstrap_test.c"
    test_binary = tmp_path / "device_user_bootstrap_test"

    flexisip_dir.mkdir(parents=True)
    flexisip_config.parent.mkdir(parents=True)
    flexisip_config.write_text(
        "[module::Registrar]\n"
        "reg-domains=local-device.example\n"
        "[module::Authentication]\n"
        "auth-domains=ignored.example\n",
        encoding="utf-8",
    )
    test_source.write_text(
        textwrap.dedent(
            f'''
            #include <stdio.h>
            #include <stdlib.h>
            #include <string.h>
            #include <unistd.h>

            #define FLEXISIP_CONFIG_FILE {json.dumps(str(flexisip_config))}
            #define FLEXISIP_DOMAIN_FILE {json.dumps(str(domain_file))}
            #define FLEXISIP_USERS_DIR {json.dumps(str(users_dir))}
            #define FLEXISIP_USERS_FILE {json.dumps(str(users_file))}
            #define FLEXISIP_ACCOUNTS_FILE {json.dumps(str(accounts_file))}
            #define FLEXISIP_ROUTE_INT_FILE {json.dumps(str(route_int))}
            #define FLEXISIP_ROUTE_EXT_FILE {json.dumps(str(route_ext))}
            #define FLEXISIP_ROUTE_ACTIVE_FILE {json.dumps(str(route_conf))}

            #include "src/string_util.c"
            #include "src/device_user.c"

            static char *read_all(const char *path)
            {{
                FILE *fp = fopen(path, "rb");
                long len;
                char *data;

                if (fp == NULL) {{
                    return NULL;
                }}
                if (fseek(fp, 0, SEEK_END) != 0) {{
                    fclose(fp);
                    return NULL;
                }}
                len = ftell(fp);
                if (len < 0 || fseek(fp, 0, SEEK_SET) != 0) {{
                    fclose(fp);
                    return NULL;
                }}
                data = calloc((size_t)len + 1, 1);
                if (data == NULL) {{
                    fclose(fp);
                    return NULL;
                }}
                if (fread(data, 1, (size_t)len, fp) != (size_t)len && ferror(fp)) {{
                    free(data);
                    fclose(fp);
                    return NULL;
                }}
                fclose(fp);
                return data;
            }}

            int main(void)
            {{
                struct c300x_device_user_status status;
                struct c300x_device_user_identity identity;
                char error[128] = {{0}};
                char *users;
                char *accounts;
                char *internal_route;
                char *external_route;
                char link_target[512] = {{0}};
                ssize_t link_len;

                if (!c300x_device_user_ensure_homeassistant(&status, "Home Assistant Lab", error, sizeof(error))) {{
                    fprintf(stderr, "ensure failed: %s\\n", error);
                    return 10;
                }}
                if (!status.homeassistant_user_present || !status.media_identity_available) {{
                    fprintf(
                        stderr,
                        "unexpected status after ensure: ha=%d media=%d domain=%d error=%s\\n",
                        status.homeassistant_user_present,
                        status.media_identity_available,
                        status.domain_present,
                        status.error
                    );
                    return 11;
                }}
                if (!status.route_int_homeassistant_present || status.route_ext_homeassistant_present || !status.routes_consistent) {{
                    fprintf(stderr, "unexpected route status after ensure\\n");
                    return 12;
                }}
                users = read_all(FLEXISIP_USERS_FILE);
                accounts = read_all(FLEXISIP_ACCOUNTS_FILE);
                internal_route = read_all(FLEXISIP_ROUTE_INT_FILE);
                external_route = read_all(FLEXISIP_ROUTE_EXT_FILE);
                if (users == NULL || accounts == NULL || internal_route == NULL || external_route == NULL) {{
                    fprintf(stderr, "missing generated flexisip files\\n");
                    return 13;
                }}
                if (
                    strstr(users, "version:1\\n") == NULL
                    || strstr(users, "homeassistant-") == NULL
                    || strstr(users, "@local-device.example md5:") == NULL
                    || strstr(users, "c300x@local-device.example") != NULL
                ) {{
                    fprintf(stderr, "unexpected users file: %s\\n", users);
                    return 14;
                }}
                if (strcmp(accounts, "Home Assistant Lab|homeassistant\\n") != 0) {{
                    fprintf(stderr, "unexpected accounts file: %s\\n", accounts);
                    return 15;
                }}
                if (
                    strstr(internal_route, "<sip:alluser@local-device.example> <sip:homeassistant-") == NULL
                    || strstr(internal_route, "@local-device.example>") == NULL
                ) {{
                    fprintf(stderr, "unexpected route_int file: %s\\n", internal_route);
                    return 16;
                }}
                if (strstr(external_route, "homeassistant") != NULL) {{
                    fprintf(stderr, "homeassistant leaked to route_ext: %s\\n", external_route);
                    return 17;
                }}
                link_len = readlink(FLEXISIP_ROUTE_ACTIVE_FILE, link_target, sizeof(link_target) - 1);
                if (link_len <= 0 || strcmp(link_target, FLEXISIP_ROUTE_INT_FILE) != 0) {{
                    fprintf(stderr, "route.conf does not point to route_int\\n");
                    return 18;
                }}
                if (!c300x_device_user_media_identity(NULL, &identity)) {{
                    fprintf(stderr, "media identity unavailable\\n");
                    return 19;
                }}
                if (
                    strcmp(identity.domain, "local-device.example") != 0
                    || strncmp(identity.from_user, "homeassistant-", 14) != 0
                    || strcmp(identity.to_aor, "c300x@local-device.example") != 0
                ) {{
                    fprintf(
                        stderr,
                        "unexpected identity: domain=%s from=%s to=%s\\n",
                        identity.domain,
                        identity.from_user,
                        identity.to_aor
                    );
                    return 20;
                }}
                free(users);
                free(accounts);
                free(internal_route);
                free(external_route);
                return 0;
            }}
            '''
        ),
        encoding="utf-8",
    )

    compile_result = subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-D_DEFAULT_SOURCE",
            "-D_POSIX_C_SOURCE=200809L",
            "-I.",
            str(test_source),
            "-o",
            str(test_binary),
        ],
        cwd=ROOT / "native_agent",
        check=False,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    run_result = subprocess.run(
        [str(test_binary)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run_result.returncode == 0, run_result.stderr


def test_native_agent_openwebnet_address_events_do_not_use_greedy_scanf() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert "parse_openwebnet_address_event(" in text
    assert "%31[0-9#]##" not in text


def test_native_agent_smartphone_forwarding_events_are_change_based() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    event_body = text.split("static int map_openwebnet_event", maxsplit=1)[1].split(
        "static void handle_udp_event",
        maxsplit=1,
    )[0]
    remember_body = text.split(
        "static void remember_smartphone_forwarding_mode",
        maxsplit=1,
    )[1].split("static int note_smartphone_forwarding_changed", maxsplit=1)[0]
    note_body = text.split(
        "static int note_smartphone_forwarding_changed",
        maxsplit=1,
    )[1].split("static void refresh_smartphone_forwarding_mode", maxsplit=1)[0]
    state_body = text.split("static void api_state", maxsplit=1)[1].split(
        "static void handle_doorbell_video_get",
        maxsplit=1,
    )[0]

    assert "int smartphone_forwarding_mode_known;" in text
    assert "int smartphone_forwarding_mode_code;" in text
    assert "c300x_smartphone_code_from_reply(msg, &code)" in event_body
    assert "note_smartphone_forwarding_changed(runtime, code)" in event_body
    assert "return 0;" in note_body
    assert "runtime->smartphone_forwarding_mode_code == code" in note_body
    assert "c300x_video_set_ring_forwarding_enabled" not in remember_body
    assert '\\"smartphone_forwarding\\":%s' in state_body
    assert "refresh_smartphone_forwarding_mode(config, runtime)" in text


def test_native_agent_ringer_events_are_change_based() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    event_body = text.split("static int map_openwebnet_event", maxsplit=1)[1].split(
        "static void handle_udp_event",
        maxsplit=1,
    )[0]
    note_body = text.split(
        "static int note_ringer_muted_changed",
        maxsplit=1,
    )[1].split("static void refresh_smartphone_forwarding_mode", maxsplit=1)[0]
    state_body = text.split("static void api_state", maxsplit=1)[1].split(
        "static void handle_doorbell_video_get",
        maxsplit=1,
    )[0]

    assert "int ringer_muted_known;" in text
    assert "int ringer_muted;" in text
    assert "note_ringer_muted_changed(runtime, muted)" in event_body
    assert "return 0;" in note_body
    assert "runtime->ringer_muted == muted" in note_body
    assert "remember_ringer_muted(runtime, muted)" in note_body
    assert "remember_ringer_muted(runtime, readback)" in text
    assert '\\"ringer_muted\\":%s' in state_body


def test_native_agent_maps_device_doorbell_answer_and_close_frames() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    event_body = text.split("static int map_openwebnet_event", maxsplit=1)[1].split(
        "static void handle_udp_event",
        maxsplit=1,
    )[0]

    assert 'strncmp(msg, "*8*2#1#4*", strlen("*8*2#1#4*")) == 0' in event_body
    assert 'strncmp(msg, "*8*3#1#4*", strlen("*8*3#1#4*")) == 0' in event_body
    assert 'strncmp(msg, "*8*3#5#4*", strlen("*8*3#5#4*")) == 0' in event_body
    assert 'strcmp(msg, "*7*0*##") == 0' in event_body
    assert event_body.index('strncmp(msg, "*8*2#1#4*"') < event_body.index(
        'c300x_copy_string(type, type_len, "doorbell.pressed")'
    )
    assert event_body.index(
        'c300x_copy_string(type, type_len, "doorbell.view_requested")'
    ) < event_body.index('strncmp(msg, "*8*3#1#4*"')
    assert event_body.index(
        'c300x_copy_string(type, type_len, "doorbell.media.closed")'
    ) < event_body.index(
        'strncmp(msg, "*8*1#1#4#"'
    )


def test_native_agent_message_watch_mask_includes_file_modifications() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert "#define C300X_MESSAGE_WATCH_MASK" in text
    assert "IN_MODIFY" in text.split("#define C300X_MESSAGE_WATCH_MASK", maxsplit=1)[1]


def test_native_agent_voicemail_signature_includes_video_playability_fields() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    signature_body = text.split("static unsigned long long voicemail_signature", maxsplit=1)[
        1
    ].split("static void drain_inotify_events", maxsplit=1)[0]

    assert "&message->has_thumbnail" in signature_body
    assert "&message->has_video" in signature_body
    assert "message->video_mime_type" in signature_body
    assert "&message->video_size" in signature_body


def test_native_agent_memo_watch_tracks_incomplete_new_directories() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    safe_name_body = text.split(
        "static int safe_voicemail_entry_name",
        maxsplit=1,
    )[1].split("static const char *video_mime_type_for_name", maxsplit=1)[0]
    add_dirs_body = text.split(
        "static void voicemail_add_entry_dir_watches",
        maxsplit=1,
    )[1].split("static void voicemail_refresh_watches", maxsplit=1)[0]
    refresh_body = text.split(
        "static void voicemail_refresh_watches",
        maxsplit=1,
    )[1].split("static void voicemail_close", maxsplit=1)[0]

    assert 'strcmp(name, ".") == 0 || strcmp(name, "..") == 0' in safe_name_body
    assert "safe_voicemail_entry_name(entry->d_name)" in add_dirs_body
    assert "path_is_directory(entry_dir)" in add_dirs_body
    assert "voicemail_add_watch(voicemail, entry_dir, 0)" in add_dirs_body
    assert "voicemail_add_entry_dir_watches(voicemail)" in refresh_body
    assert "snapshot.messages[index].dir_path" not in refresh_body


def test_native_agent_runtime_diagnostics_are_memory_only_until_requested() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    diagnostics_body = text.rsplit("static void handle_diagnostics_get", maxsplit=1)[
        1
    ].split("static void handle_setup_page", maxsplit=1)[0]
    run_body = text.rsplit("int c300x_run", maxsplit=1)[1]

    assert "char last_wake_reason[64];" in text
    assert "runtime->loop_iterations++;" in run_body
    assert "runtime->poll_wakeups++;" in run_body
    assert "runtime->accepted_clients++;" in run_body
    assert '"api"' in run_body
    assert '"ui"' in run_body
    assert 'runtime_set_wake_reason(runtime, "mqtt")' in run_body
    assert "count_open_fds()" in diagnostics_body
    assert text.count("count_open_fds()") == 1
    assert '\\"open_fd_count\\":%d' in diagnostics_body
    assert "int video_media_running;" in diagnostics_body
    assert "video_media_running = (" in diagnostics_body
    assert '\\"video_rtsp_server_running\\":%s' in diagnostics_body
    assert (
        diagnostics_body.index('"\\"video_running\\":%s,"')
        < diagnostics_body.index('"\\"video_rtsp_server_running\\":%s,"')
        < diagnostics_body.index('"\\"video_media_starting\\":%s,"')
    )
    assert (
        diagnostics_body.index('video_media_running ? "true" : "false",')
        < diagnostics_body.index('video_status.running ? "true" : "false",')
    )
    assert '\\"video_bridge_active_threads\\":%d' in diagnostics_body


def test_native_agent_recent_event_diagnostics_are_heap_backed() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    recent_events_header = (ROOT / "native_agent" / "src" / "recent_events.h").read_text(
        encoding="utf-8"
    )
    recent_events_source = (ROOT / "native_agent" / "src" / "recent_events.c").read_text(
        encoding="utf-8"
    )
    runtime_struct = text.split("struct agent_runtime {", maxsplit=1)[1].split(
        "};",
        maxsplit=1,
    )[0]
    cleanup_body = text.rsplit("cleanup:", maxsplit=1)[1]

    assert "#include \"recent_events.h\"" in text
    assert "struct c300x_recent_events recent_events;" in runtime_struct
    assert "C300X_MAX_RECENT_EVENTS][C300X_RECENT_EVENT_LEN]" not in runtime_struct
    assert "char *items[C300X_RECENT_EVENTS_CAPACITY];" in recent_events_header
    assert "recent_event_copy(event_json)" in recent_events_source
    assert "free(events->items[0]);" in recent_events_source
    assert "c300x_recent_events_clear(&runtime->recent_events);" in cleanup_body
