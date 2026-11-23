"""Fault injection for the coupled camera configuration and executable update."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_native_camera_quality import SETTINGS, STACK, WHOLE_PICTURE

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#define _GNU_SOURCE
#include "camera_files.h"
#include "camera_update.h"
#include "device_file.h"
#include "media_geometry_patch.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static int state = 0, failed = 0, settings_syncs = 0, crop_syncs = 0;
static const char *mode, *settings_path, *crop_path;
enum c300x_media_geometry_state c300x_media_geometry_state(const char *path) {
    (void)path;
    return state;
}
int c300x_media_geometry_prepare(int enable, const char **error) {
    (void)enable; (void)error;
    return 1;
}
int c300x_media_geometry_apply(int enable, int *ro, const char **error) {
    state = enable;
    *ro = 0;
    if (enable && !strcmp(mode,"binary")) { *error = "geometry_readback_failed"; return 0; }
    if (enable && !strcmp(mode,"final_readback")) {
        if (!c300x_device_file_write(crop_path,"damaged",7)) return 0;
    }
    return 1;
}
int __real_c300x_device_file_write(const char *path, const char *data, size_t len);
int __wrap_c300x_device_file_write(const char *path, const char *data, size_t len) {
    if (!strcmp(mode,"crop_write") && !failed && !strcmp(path,crop_path)) {
        failed = 1;
        return 0;
    }
    return __real_c300x_device_file_write(path,data,len);
}
int __real_c300x_device_file_sync_parents(const char *path);
int __wrap_c300x_device_file_sync_parents(const char *path) {
    if (!strcmp(path,settings_path)) settings_syncs++;
    if (!strcmp(path,crop_path)) crop_syncs++;
    if (!strcmp(mode,"backup_sync") && strstr(path,"/backups/")) return 0;
    if (!failed && ((!strcmp(mode,"settings_sync") && !strcmp(path,settings_path))
        || (!strcmp(mode,"crop_sync") && !strcmp(path,crop_path)))) {
        failed = 1;
        return 0;
    }
    if (!strcmp(mode,"persistent_sync") && !strcmp(path,settings_path)) return 0;
    return __real_c300x_device_file_sync_parents(path);
}
int __real_c300x_device_file_remount(const char *mode);
int __wrap_c300x_device_file_remount(const char *mount_mode) {
    if (!strcmp(mode,"ro_busy") && !strcmp(mount_mode,"ro")) return 0;
    return __real_c300x_device_file_remount(mount_mode);
}
int main(int argc, char **argv) {
    if (argc != 4 && argc != 5) return 2;
    settings_path = argv[1]; crop_path = argv[2]; mode = argv[3];
    int low = argc == 5 && !strcmp(argv[4],"low");
    int geometry_change = argc == 4;
    int crop_only = argc == 5 && !strcmp(argv[4],"crop");
    struct c300x_camera_values before, after;
    if (!c300x_camera_files_read(low,settings_path,crop_path,&before)) return 3;
    after = before;
    if (!crop_only) after.fps = 24;
    if (geometry_change || crop_only) {
        after.crop[0] = 8; after.crop[1] = 0; after.crop[2] = 704; after.crop[3] = 576;
    }
    const char *error = "";
    int ro = 0;
    int ok = c300x_camera_update(low,&before,&after,0,geometry_change,settings_path,crop_path,&ro,&error);
    printf("{\"ok\":%d,\"state\":%d,\"error\":\"%s\",\"ro_failed\":%d,"
        "\"settings_syncs\":%d,\"crop_syncs\":%d}\n",ok,state,error,ro,settings_syncs,crop_syncs);
    return 0;
}
'''


@pytest.fixture(scope="module")
def transaction_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("camera-transaction")
    source = folder / "probe.c"
    source.write_text(HARNESS)
    output = folder / "probe"
    files = ("camera_update", "camera_files", "camera_settings", "camera_crop", "device_file", "device_file_sync")
    subprocess.run([
        "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", "-I", str(ROOT / "native_agent/src"),
        str(source), *(str(ROOT / f"native_agent/src/{name}.c") for name in files),
        "-Wl,--wrap=c300x_device_file_write", "-Wl,--wrap=c300x_device_file_sync_parents",
        "-Wl,--wrap=c300x_device_file_remount",
        "-o", str(output),
    ], capture_output=True, check=True, text=True)
    return output


@pytest.mark.parametrize(("fault", "error"), [
    ("crop_write", "write_failed"),
    ("binary", "geometry_readback_failed"),
    ("final_readback", "target_state_mismatch"),
    ("backup_sync", "backup_failed"),
    ("none", ""),
])
def test_faults_restore_exact_pre_request_state(transaction_probe: Path, tmp_path: Path, fault: str, error: str) -> None:
    settings, crop = tmp_path / "settings", tmp_path / "crop"
    settings.write_text(SETTINGS)
    crop.write_text(STACK)
    settings.chmod(0o640)
    crop.chmod(0o644)
    result = subprocess.run([str(transaction_probe), str(settings), str(crop), fault],
                            capture_output=True, check=True, text=True,
                            env={**os.environ, "C300X_AUDIO_BACKUP_DIR": str(tmp_path / "backups"),
                                 "C300X_AUDIO_NO_REMOUNT": "1"})
    body = json.loads(result.stdout)
    if fault == "none":
        assert body["ok"] == 1 and body["state"] == 1
        assert settings.read_text() == SETTINGS.replace("FpsRtpH=15", "FpsRtpH=24")
        assert crop.read_text() == WHOLE_PICTURE
    else:
        assert {key: body[key] for key in ("ok", "state", "error")} == {"ok": 0, "state": 0, "error": error}
        assert settings.read_text() == SETTINGS
        assert crop.read_text() == STACK
    assert settings.stat().st_mode & 0o777 == 0o640
    assert crop.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize("profile", ["high", "low", "crop"])
@pytest.mark.parametrize("fault", ["none", "ro_busy", "settings_sync", "crop_sync", "persistent_sync"])
def test_config_only_durability_is_inside_rollback(transaction_probe: Path, tmp_path: Path,
                                                  profile: str, fault: str) -> None:
    settings, crop = tmp_path / "settings", tmp_path / "crop"
    settings.write_text(SETTINGS)
    if profile != "low":
        crop.write_text(STACK)
    result = subprocess.run([str(transaction_probe), str(settings), str(crop), fault, profile],
                            capture_output=True, check=True, text=True, timeout=5,
                            env={**os.environ, "C300X_AUDIO_BACKUP_DIR": str(tmp_path / "backups"),
                                 "C300X_AUDIO_NO_REMOUNT": "1"})
    body = json.loads(result.stdout)
    success = fault in ("none", "ro_busy") or (profile == "low" and fault == "crop_sync")
    assert body["ok"] == int(success)
    assert body["state"] == 0
    assert body["settings_syncs"] >= 1
    if profile == "low":
        assert body["crop_syncs"] == 0
        assert not crop.exists()
    if success:
        assert body["error"] == ""
        assert body["ro_failed"] == int(fault == "ro_busy")
        expected = SETTINGS if profile == "crop" else SETTINGS.replace(
            "FpsRtpL=10" if profile == "low" else "FpsRtpH=15",
            "FpsRtpL=24" if profile == "low" else "FpsRtpH=24")
        assert settings.read_text() == expected
        if profile != "low":
            assert body["crop_syncs"] >= 1
            assert crop.read_text() == (WHOLE_PICTURE if profile == "crop" else STACK)
    else:
        expected_error = "rollback_failed" if fault == "persistent_sync" and profile != "crop" else "config_sync_failed"
        assert body["error"] == expected_error
        assert settings.read_text() == SETTINGS
        if profile != "low":
            assert crop.read_text() == STACK
