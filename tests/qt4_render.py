"""Run display pages on the station's own Qt 4.8 with a GUI, when it is at hand.

Needs an ARM emulator and cross compiler, an unpacked system image, a copy of
its skin directory and placeholder modules for its compiled-in imports: the
C300X_QT4_QEMU, _ROOTFS, _GUI and _COMPILE_IMPORTS variables of the compile
test. None of these belong in the repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/qml/qt4_render_probe.c"
START = ROOT / "native_agent/src/arm_start.S"
NAMES = ("QEMU", "ROOTFS", "COMPILE_IMPORTS", "GUI")
# Qt reports a QML problem with the file and line it comes from.
WARNING = re.compile(r"\.(?:qml|js):\d+")


def environment() -> list[str] | None:
    paths = [os.environ.get("C300X_QT4_" + name, "") for name in NAMES]
    return paths if all(paths) and shutil.which("arm-linux-gnueabihf-gcc") else None


def build_probe(rootfs: str) -> Path:
    """Build the probe once per source state, outside the checkout."""
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "c300x-dev/qt4-render"
    digest = hashlib.sha256(SOURCE.read_bytes() + START.read_bytes()).hexdigest()[:16]
    probe = cache / f"qml_render_probe-{digest}"
    if not probe.exists():
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        staged = cache / f".{probe.name}.{os.getpid()}"
        subprocess.run([
            "arm-linux-gnueabihf-gcc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_GNU_SOURCE",
            "-D_TIME_BITS=32", "-Wl,--export-dynamic", str(SOURCE), str(START), "-pthread",
            f"-Wl,-rpath-link,{rootfs}/lib", f"-L{rootfs}/lib", "-l:libpthread.so.0", "-l:libdl.so.2",
            "-l:libc.so.6", "-l:ld-linux-armhf.so.3", "-nostartfiles", "-o", str(staged),
        ], check=True, capture_output=True, timeout=60)
        staged.replace(probe)
    return probe


class Station:
    """The skin with this checkout's display files, and the means to show a page of it."""

    def __init__(self, paths: list[str]):
        from test_device_file_strip import strip

        self.qemu, rootfs, imports, gui = paths
        self.probe = build_probe(rootfs)
        # The system image links /tmp elsewhere, so the emulator resolves nothing below it.
        self.work = Path(tempfile.mkdtemp(prefix="c300x-qt4-render-", dir="/var/tmp"))
        self.gui = self.work / "gui"
        shutil.copytree(gui, self.gui)
        shutil.copytree(imports, self.work / "imports")
        for relative in strip.DEVICE_SOURCE_FILES:
            strip.strip_device_file(strip.DEVICE_SOURCE_DIR / relative, self.gui / relative)
        # A system root of its own keeps the window system's socket out of the host's /tmp.
        self.root = self.work / "sys"
        self.root.mkdir()
        for name in ("bin", "etc", "lib", "sbin", "usr"):
            (self.root / name).symlink_to(Path(rootfs) / name)
        (self.root / "tmp").mkdir()

    def close(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def patch_vendor_pages(self) -> None:
        """Change the vendor pages of the skin the way the agent does on a station."""
        from test_qml_patch_script import _run_qml_patch

        if not (self.work / "backup").exists():
            assert _run_qml_patch(self.work, self.gui, self.work / "backup", "apply")["state"] == "patched"

    def show(self, name: str, source: str, milliseconds: int = 2000, picture: Path | None = None) -> str:
        """Show QML source as a file of the skin; return what Qt and the page printed."""
        page = self.gui / f"{name}.qml"
        page.write_text(source)
        frame = self.work / "frame.fb"
        frame.write_bytes(bytes(800 * 480 * 4))
        variables = {
            "LD_LIBRARY_PATH": f"{self.root}/usr/lib:{self.root}/lib",
            "QWS_DISPLAY": f"LinuxFb:{frame}:nographicsmodeswitch", "QWS_KEYBOARD": "none",
            "QWS_MOUSE_PROTO": "none", "QML_IMPORT_PATH": f"{self.gui}:{self.work / 'imports'}",
            "QT_PLUGIN_PATH": "/usr/lib/qtopia/plugins", "QT_QWS_FONTDIR": "/usr/lib/fonts",
            "PROBE_DEPTH": "32", "HOME": str(self.work),
        }
        command = [self.qemu, "-L", str(self.root)]
        for key, value in variables.items():
            command += ["-E", f"{key}={value}"]
        command += [str(self.probe), str(page), str(picture or self.work / "frame.png"), str(milliseconds)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        output = result.stdout + result.stderr
        assert result.returncode == 0 and "PROBE_SAVED 1" in output, output[-1500:]
        return output


class Agent:
    """Stand-in for the agent's display listener: fixed answers by path, on the loopback."""

    def __init__(self, answers: dict[str, tuple[int, dict[str, object]]]):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status, body = answers.get(self.path.split("?")[0], (404, {"ok": False}))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.do_GET()

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def warnings(output: str) -> list[str]:
    return sorted({line.rsplit("/", 1)[-1] for line in output.splitlines() if WARNING.search(line)})
