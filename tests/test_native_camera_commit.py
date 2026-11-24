"""A verified camera commit must not be turned into an error by response reads."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_native_camera_quality import SETTINGS, STACK

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#define _POSIX_C_SOURCE 200809L
#include "camera_quality.h"
#include "camera_files.h"
#include "camera_running.h"
#include "camera_update.h"
#include "media_geometry_patch.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int committed, disk_reads, config_reads, low, state, drop_running;
int c300x_device_display_is_qt5(void) { return low; }
enum c300x_media_geometry_state c300x_media_geometry_state(const char *path) {
    if (path) return drop_running && committed ? C300X_MEDIA_GEOMETRY_UNKNOWN : state;
    if (committed) { disk_reads++; return C300X_MEDIA_GEOMETRY_UNKNOWN; }
    return state;
}
int c300x_media_geometry_process_name(char *name, size_t len) { (void)name; (void)len; return 0; }
enum c300x_media_geometry_state c300x_media_geometry_running_state(pid_t pid) {
    (void)pid; return C300X_MEDIA_GEOMETRY_UNKNOWN;
}
int c300x_media_geometry_prepare(int enable, const char **error) { (void)enable; (void)error; return 1; }
int c300x_media_geometry_apply(int enable, int *ro, const char **error) {
    (void)error; state = enable; *ro = 0; return 1;
}
int __real_c300x_camera_update(int, const struct c300x_camera_values *, const struct c300x_camera_values *,
    int, int, const char *, const char *, int *, const char **);
int __wrap_c300x_camera_update(int l, const struct c300x_camera_values *before,
    const struct c300x_camera_values *after, int g0, int g1, const char *s, const char *c,
    int *ro, const char **error) {
    int ok = __real_c300x_camera_update(l,before,after,g0,g1,s,c,ro,error);
    committed = ok;
    return ok;
}
int __real_c300x_camera_files_read(int,const char *,const char *,struct c300x_camera_values *);
int __wrap_c300x_camera_files_read(int l,const char *s,const char *c,struct c300x_camera_values *v) {
    if (committed) { config_reads++; return 0; }
    return __real_c300x_camera_files_read(l,s,c,v);
}
int __wrap_c300x_device_file_remount(const char *mode) { return strcmp(mode,"ro") != 0; }
int main(int argc,char **argv) {
    if (argc != 2) return 2;
    low = !strcmp(argv[1],"low");
    state = !strcmp(argv[1],"unknown") ? C300X_MEDIA_GEOMETRY_UNKNOWN : C300X_MEDIA_GEOMETRY_STOCK;
    drop_running = !strcmp(argv[1],"drop_running");
    c300x_camera_quality_note_running();
    struct c300x_camera_quality quality;
    const char *error = "";
    int ok = c300x_camera_quality_apply(&quality,low ? 180 : 800,24,
        !strcmp(argv[1],"geometry") ? "960x576" : NULL,&error);
    struct c300x_camera_values actual;
    if (!__real_c300x_camera_files_read(low,getenv("C300X_CAMERA_QUALITY_FILE"),
        getenv("C300X_CAMERA_CROP_FILE"),&actual)) return 3;
    printf("{\"ok\":%d,\"error\":\"%s\",\"actual_fps\":%d,\"response_fps\":%d,"
        "\"config_reads_after_commit\":%d,\"disk_reads_after_commit\":%d,\"changed\":%d,"
        "\"restart_required\":%d,\"ro_failed\":%d,\"geometry_supported\":%d,\"geometry_enabled\":%d,"
        "\"size\":\"%s\",\"running_fps\":%d}\n",ok,error,actual.fps,quality.saved.fps,
        config_reads,disk_reads,quality.changed,quality.restart_required,quality.remount_ro_failed,
        quality.geometry_supported,quality.geometry_enabled,quality.size,quality.running.fps);
    return 0;
}
'''


@pytest.fixture(scope="module")
def commit_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("camera-commit")
    source, output = folder / "probe.c", folder / "probe"
    source.write_text(HARNESS)
    files = ("camera_quality", "camera_running", "camera_update", "camera_update_lock", "camera_files",
             "camera_settings", "camera_crop", "camera_sizes", "device_file", "device_file_sync", "root_mount")
    result = subprocess.run([
        "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-D_DEFAULT_SOURCE", "-I", str(ROOT / "native_agent/src"), str(source),
        *(str(ROOT / f"native_agent/src/{name}.c") for name in files),
        "-Wl,--wrap=c300x_camera_update", "-Wl,--wrap=c300x_camera_files_read",
        "-Wl,--wrap=c300x_device_file_remount", "-o", str(output),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return output


@pytest.mark.parametrize("mode", ["high", "low", "geometry", "unknown", "drop_running"])
def test_committed_response_uses_verified_values_despite_read_failures(
    commit_probe: Path, tmp_path: Path, mode: str,
) -> None:
    settings, crop, running = tmp_path / "settings", tmp_path / "crop", tmp_path / "running"
    settings.write_text(SETTINGS)
    if mode != "low":
        crop.write_text(STACK)
    running.write_text("generated process fixture")
    result = subprocess.run([str(commit_probe), mode], check=True, capture_output=True, text=True, timeout=5,
                            env={**os.environ, "C300X_CAMERA_QUALITY_FILE": str(settings),
                                 "C300X_CAMERA_CROP_FILE": str(crop),
                                 "C300X_CAMERA_UPDATE_LOCK": str(tmp_path / "lock"),
                                 "C300X_CAMERA_RUNNING_NOTE": str(tmp_path / "note"),
                                 "C300X_MEDIA_GEOMETRY_RUNNING_TARGET": str(running),
                                 "C300X_AUDIO_BACKUP_DIR": str(tmp_path / "backups")})
    body = json.loads(result.stdout)
    assert body["ok"] == 1 and body["error"] == ""
    assert body["actual_fps"] == body["response_fps"] == 24
    assert body["config_reads_after_commit"] == body["disk_reads_after_commit"] == 0
    assert body["changed"] == body["restart_required"] == body["ro_failed"] == 1
    assert body["geometry_supported"] == int(mode not in ("low", "unknown"))
    assert body["geometry_enabled"] == int(mode == "geometry")
    assert body["size"] == {"low": "400x288", "geometry": "960x576"}.get(mode, "688x480")
    assert body["running_fps"] == (0 if mode in ("geometry", "drop_running") else 10 if mode == "low" else 15)
