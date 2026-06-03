from __future__ import annotations

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
        "system_metrics_changed(config, &runtime->system_metrics_last_dispatched, &sample)"
        in text
    )
    assert "metric_changed_points(previous->memory_usage_percent" in text


def test_native_agent_metrics_reads_memory_only_inside_metrics_sample() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    sample_body = text.rsplit("static int read_system_metrics_sample", maxsplit=1)[
        1
    ].split("static int system_metrics_json", maxsplit=1)[0]

    assert "read_memory_metrics(" in sample_body
    assert text.count("read_memory_metrics(") == 2
    assert "static int metric_changed_points(" in text


def test_native_agent_metrics_does_not_mark_unsent_samples_as_dispatched() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    dispatch_body = text.split("static void system_metrics_dispatch_if_due", maxsplit=1)[
        1
    ].split("static int map_openwebnet_event", maxsplit=1)[0]

    assert (
        "if (!system_metrics_watch_active(config, runtime)) {\n"
        "        runtime->system_metrics_next_sample_at = now + "
        "config->system_metrics_heartbeat_seconds;\n"
        "        return;\n"
        "    }\n"
        in dispatch_body
    )
    assert dispatch_body.index("system_metrics_json(&sample") < dispatch_body.index(
        "system_metrics_mark_dispatched(runtime, &sample, now)"
    )


def test_native_agent_metrics_does_not_wake_for_metrics_without_subscribers() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    poll_body = _c300x_run_loop_body(text)

    assert "if (system_metrics_watch_active(config, runtime))" in poll_body


def test_native_agent_metrics_dispatch_loop_is_subscriber_gated() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert (
        "if (system_metrics_watch_active(config, runtime)) {\n"
        "            system_metrics_dispatch_if_due(config, runtime, time(NULL));\n"
        "        }"
        in text
    )


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

    assert "read_system_metrics_sample(" not in post_body
    assert (
        'if (subscription_matches_event(&runtime->subscriptions[0], "system.metrics_changed"))'
        in post_body
    )
    assert dispatch_now_body.index("system_metrics_watch_active") < dispatch_now_body.index(
        "read_system_metrics_sample"
    )


def test_native_agent_metrics_does_not_sample_at_start_without_subscribers() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    init_body = text.split("static void system_metrics_init", maxsplit=1)[1].split(
        "static void system_metrics_mark_dispatched",
        maxsplit=1,
    )[0]

    assert init_body.index("system_metrics_watch_active") < init_body.index(
        "read_system_metrics_sample"
    )


def test_native_agent_maintenance_requires_token_even_in_no_auth_mode() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    maintenance_body = text.rsplit(
        "static int maintenance_authorized",
        maxsplit=1,
    )[1].split("static int maintenance_auth_available", maxsplit=1)[0]

    assert "if (config->api_no_auth)" not in maintenance_body
    assert "config->maintenance_admin_token[0] == '\\0'" in maintenance_body


def test_native_agent_openwebnet_address_events_do_not_use_greedy_scanf() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert "parse_openwebnet_address_event(" in text
    assert "%31[0-9#]##" not in text


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
