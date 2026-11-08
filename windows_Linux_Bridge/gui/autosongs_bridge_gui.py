#!/usr/bin/env python3
"""AutoSongs bridge - tray app for Windows and Linux.

Starts and stops the bridge, shows the pairing code, and keeps an icon in
the system tray. The bridge runs as a child process so that Stop is a clean
kill and the bridge's own output lands in ~/.autosongs/bridge.log.

Options:
  --tray        start hidden in the tray and start the bridge (used at sign-in)
  --uninstall   (Windows) stop the app, remove autostart and the install folder
  --no-install  (Windows, packaged build) run in place instead of installing
"""
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request

import tkinter as tk
from tkinter import ttk

import pystray
from PIL import Image, ImageDraw

IS_WIN = os.name == "nt"
FROZEN = bool(getattr(sys, "frozen", False))
APP_NAME = "AutoSongs Bridge"
# Donate target: the AutoSongs Ko-fi page.
DONATE_URL = "https://ko-fi.com/autosongs"
PORT = 8765
LOCK_PORT = 47865  # single-instance guard; a second launch just shows the window
HOME = os.path.expanduser("~")
DIR = os.path.join(HOME, ".autosongs")
BRIDGE = os.path.join(DIR, "ytbridge.py")
LOG = os.path.join(DIR, "bridge.log")

# The bridge core is published only at AutoSongs' own site; the old
# throwaway host names are gone from this launcher so it can never pick
# up an old published copy.
HOSTS = [
    "https://autosongs.example",
]

SELF = os.path.abspath(sys.executable if FROZEN else __file__)
if IS_WIN:
    INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local")),
                               "AutoSongs Bridge")
    INSTALL_EXE = os.path.join(INSTALL_DIR, "AutoSongsBridge.exe")
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    RUN_NAME = "AutoSongsBridge"
else:
    INSTALL_DIR = os.path.join(HOME, ".local", "share", "autosongs-bridge")
    INSTALL_EXE = os.path.join(INSTALL_DIR, "autosongs_bridge_gui.py")
    AUTOSTART_FILE = os.path.join(HOME, ".config", "autostart", "autosongs-bridge.desktop")

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if IS_WIN else 0

# The lines the bridge prints when it starts (see print_pairing_banner).
SHORT_RE = re.compile(r"^\s{4,}([0-9A-HJKMNP-TV-Z]{8})\s*$")
LONG_RE = re.compile(r"^\s{4,}([0-9A-Z]{4,}(?:-[0-9A-Z]+)+)\s*$")
ADDR_RE = re.compile(r"^\s*Address:\s*(\S+)\s*$")

COLORS = {
    "stopped": (110, 118, 129),
    "starting": (210, 153, 34),
    "running": (46, 160, 67),
    "error": (207, 34, 46),
}
STATE_TEXT = {"stopped": "Stopped", "starting": "Starting...", "running": "Running", "error": "Error"}


# ----------------------------------------------------------------- helpers
def child_env():
    """The environment for the python children.

    A frozen build (PyInstaller) sets variables that would point a normal
    python at the bundled runtime, so those are removed for the children.
    """
    env = dict(os.environ)
    if FROZEN:
        for key in list(env):
            if key.startswith("_PYI") or key.startswith("_MEI") or key in (
                    "PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"):
                env.pop(key, None)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def hidden_kwargs():
    if IS_WIN:
        return {"creationflags": NO_WINDOW}
    return {}


def log_line(text):
    os.makedirs(DIR, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(str(text).rstrip() + "\n")


def run_quiet(cmd, timeout=120):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=child_env(), **hidden_kwargs())


def find_python():
    """A python 3 that can run the bridge. Returns the command as a list."""
    cands = [] if FROZEN else [[sys.executable]]
    cands += [["py", "-3"], ["python"], ["python3"]] if IS_WIN else [["python3"]]
    for cand in cands:
        if cand[0] != sys.executable and not shutil.which(cand[0]):
            continue
        try:
            r = run_quiet(cand + ["-c", "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)"], 30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            # Ask for the real executable. "py -3" is a launcher that would
            # otherwise be the process we kill, leaving the bridge running.
            try:
                real = run_quiet(cand + ["-c", "import sys; print(sys.executable)"], 30).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                real = ""
            return [real] if real and os.path.exists(real) else cand
    return None


def has_yt_dlp(py):
    try:
        r = run_quiet(py + ["-c", "import yt_dlp, sys; print(sys.executable)"], 60)
    except (OSError, subprocess.SubprocessError):
        return False
    log_line("  yt-dlp check via %s: rc=%s %s" % (" ".join(py), r.returncode,
                                                  (r.stdout or r.stderr).strip()[-200:]))
    return r.returncode == 0


def pip_install_yt_dlp(py, log):
    in_venv = (not FROZEN) and sys.prefix != sys.base_prefix and py[0] == sys.executable
    tries = [[]] if in_venv else ([["--user"]] if IS_WIN else [["--user"], ["--user", "--break-system-packages"]])
    for extra in tries:
        r = run_quiet(py + ["-m", "pip", "install", *extra, "--upgrade", "yt-dlp"], 900)
        log_line("pip rc=%s" % r.returncode)
        log_line((r.stdout or "")[-2000:])
        log_line((r.stderr or "")[-2000:])
        if r.returncode == 0 and has_yt_dlp(py):
            return True
    return False


def bridge_version(blob):
    """The BRIDGE_VERSION a bridge source declares, as a tuple, or None."""
    if isinstance(blob, bytes):
        blob = blob.decode("utf-8", "replace")
    m = re.search(r'^BRIDGE_VERSION = "([^"]+)"', blob, re.M)
    if not m:
        return None
    return tuple(int(p) if p.isdigit() else 0 for p in m.group(1).split("."))


def fmt_version(v):
    return ".".join(str(p) for p in v) if v else "no version"


def fetch_bridge(log):
    """Fetch the published bridge.

    Never downgrades: a copy that is already here is replaced only by a
    remote copy declaring a strictly newer version (a file with no declared
    version also never overwrites a local copy). The first fetch, when
    nothing is installed here, puts any valid copy in place as before.
    """
    os.makedirs(DIR, exist_ok=True)
    tmp = BRIDGE + ".new"
    local_ver = None
    if os.path.exists(BRIDGE):
        try:
            with open(BRIDGE, "rb") as fh:
                local_ver = bridge_version(fh.read())
        except OSError:
            local_ver = None
    for host in HOSTS:
        try:
            with urllib.request.urlopen(host + "/ytbridge.py", timeout=90) as resp:
                data = resp.read()
        except Exception as exc:  # noqa: BLE001 - try the next host
            log("  %s: %s" % (host, exc))
            continue
        if b"def make_server" not in data:
            continue
        remote_ver = bridge_version(data)
        if local_ver is not None and (remote_ver is None or remote_ver <= local_ver):
            log("  %s serves %s; keeping the %s copy that is already here."
                % (host, fmt_version(remote_ver), fmt_version(local_ver)))
            continue
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, BRIDGE)
        return True
    return False


def prepare(log):
    """Make sure python, yt-dlp and the bridge are in place. Returns the python command."""
    log("Looking for python 3...")
    py = find_python()
    log("  python: %s" % (" ".join(py) if py else "none"))
    if not py:
        raise RuntimeError("Python 3 was not found. Install it (Windows: winget install "
                           "Python.Python.3) and start the bridge again.")
    log("Checking yt-dlp...")
    if not has_yt_dlp(py):
        log("Installing yt-dlp...")
        if not pip_install_yt_dlp(py, log):
            raise RuntimeError("yt-dlp would not install. Details are in " + LOG)
    log("Fetching the bridge...")
    if not fetch_bridge(log):
        if not os.path.exists(BRIDGE):
            raise RuntimeError("The bridge could not be fetched and there is no copy. Check the network.")
        log("Using the copy of the bridge that is already here.")
    return py


def make_icon(state):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, 62, 62), fill=COLORS[state] + (255,))
    # A music note, so the icon reads as AutoSongs.
    draw.rectangle((38, 14, 42, 42), fill=(255, 255, 255, 255))
    draw.ellipse((22, 38, 42, 54), fill=(255, 255, 255, 255))
    draw.polygon([(42, 14), (50, 20), (50, 27), (42, 22)], fill=(255, 255, 255, 255))
    return img


# -------------------------------------------------------------- autostart
def autostart_enabled():
    if IS_WIN:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, RUN_NAME)
            return True
        except OSError:
            return False
    return os.path.exists(AUTOSTART_FILE)


def autostart_command():
    launcher = INSTALL_EXE if (IS_WIN and os.path.exists(INSTALL_EXE)) else SELF
    if IS_WIN:
        return '"%s" --tray' % launcher
    return '"%s" "%s" --tray' % (sys.executable, launcher)


def set_autostart(on):
    if IS_WIN:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if on:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_NAME)
                except OSError:
                    pass
        return
    if on:
        os.makedirs(os.path.dirname(AUTOSTART_FILE), exist_ok=True)
        with open(AUTOSTART_FILE, "w", encoding="utf-8") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=%s\nComment=Tray app for the AutoSongs bridge\n"
                     "Exec=%s\nTerminal=false\nX-GNOME-Autostart-enabled=true\n" % (APP_NAME, autostart_command()))
    else:
        try:
            os.remove(AUTOSTART_FILE)
        except OSError:
            pass


# ----------------------------------------------------------- the bridge
class Bridge:
    """Runs ytbridge.py --pair as a child process and tracks its state."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.state = "stopped"
        self.message = "Not running."
        self.short = ""
        self.long = ""
        self.address = ""
        self.user_stop = False

    def snapshot(self):
        with self.lock:
            return {"state": self.state, "message": self.message, "short": self.short,
                    "long": self.long, "address": self.address}

    def active(self):
        return self.snapshot()["state"] in ("starting", "running")

    def start(self):
        with self.lock:
            if self.state in ("starting", "running"):
                return
            self.state = "starting"
            self.message = "Getting ready..."
            self.short = self.long = self.address = ""
            self.user_stop = False
        try:
            py = prepare(lambda m: self._say(m))
        except BaseException as exc:  # noqa: BLE001 - shown in the window
            import traceback
            log_line(traceback.format_exc())
            self._fail(str(exc) or type(exc).__name__)
            return
        with self.lock:
            if self.user_stop:
                self.state = "stopped"
                self.message = "Stopped."
                return
        cmd = py + [BRIDGE, "--pair", "--port", str(PORT)]
        log_line("--- starting bridge: " + " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=DIR,
                env=child_env(), **hidden_kwargs())
        except OSError as exc:
            self._fail("Could not start the bridge: %s" % exc)
            return
        with self.lock:
            self.proc = proc
            self.message = "Starting the bridge..."
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()

    def _say(self, text):
        with self.lock:
            self.message = text
        log_line(text)

    def _fail(self, text):
        with self.lock:
            self.state = "error"
            self.message = text
        log_line("error: " + text)

    def _pump(self, proc):
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                log_line(line)
                with self.lock:
                    if "listening on" in line:
                        self.state = "running"
                        self.message = "Listening on port %d" % PORT
                    m = SHORT_RE.match(line)
                    if m:
                        self.short = m.group(1)
                    m = LONG_RE.match(line)
                    if m:
                        self.long = m.group(1)
                    m = ADDR_RE.match(line)
                    if m:
                        self.address = m.group(1)
        finally:
            rc = proc.wait()
            with self.lock:
                if self.proc is proc:
                    self.proc = None
                if self.user_stop:
                    self.state = "stopped"
                    self.message = "Stopped."
                else:
                    self.state = "error"
                    self.message = "The bridge quit (exit %s). Details are in the log." % rc
                    log_line(self.message)

    def stop(self):
        with self.lock:
            self.user_stop = True
            proc = self.proc
            self.state = "stopped"
            self.message = "Stopped."
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(8)
            except subprocess.TimeoutExpired:
                proc.kill()


# -------------------------------------------------------- single instance
def acquire_lock():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        sock.close()
        return None
    sock.listen(5)
    return sock


def send_to_running(message):
    try:
        with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=2) as conn:
            conn.sendall(message.encode("ascii"))
        return True
    except OSError:
        return False


# ------------------------------------------------------------------- GUI
class App:
    def __init__(self, tray_only, lock_sock):
        self.bridge = Bridge()
        self.q = queue.Queue()
        self.icon = None
        self.icon_state = None
        self.pair_win = None
        self.lock_sock = lock_sock

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.q.put("hide"))

        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=APP_NAME, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.status_var = tk.StringVar(value="Stopped")
        self.detail_var = tk.StringVar(value="Not running.")
        ttk.Label(frame, textvariable=self.status_var, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        ttk.Label(frame, textvariable=self.detail_var, wraplength=360).pack(anchor="w", pady=(2, 12))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.btn_toggle = ttk.Button(row, text="Start bridge", command=lambda: self.q.put("toggle"), width=14)
        self.btn_toggle.pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Pair phone...", command=lambda: self.q.put("pair"), width=14).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Open log", command=lambda: self.q.put("log"), width=10).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Donate", command=lambda: self.q.put("donate"), width=10).pack(side="left")

        self.autostart_var = tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(frame, text="Start when I sign in", variable=self.autostart_var,
                        command=self.toggle_autostart).pack(anchor="w", pady=(14, 0))
        ttk.Button(frame, text="Hide to tray", command=lambda: self.q.put("hide")).pack(anchor="e", pady=(12, 0))

        if tray_only:
            self.root.withdraw()
        self.start_tray()
        threading.Thread(target=self._listen_lock, daemon=True).start()
        self.tick()

        if tray_only:
            self.q.put("toggle")

    # tray -----------------------------------------------------------
    def start_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show window", lambda i, it: self.q.put("show"), default=True),
            pystray.MenuItem(lambda it: "Stop bridge" if self.bridge.active() else "Start bridge",
                             lambda i, it: self.q.put("toggle")),
            pystray.MenuItem("Pair phone...", lambda i, it: self.q.put("pair")),
            pystray.MenuItem("Start when I sign in", lambda i, it: self.q.put("autostart"),
                             checked=lambda it: autostart_enabled()),
            pystray.MenuItem("Open log", lambda i, it: self.q.put("log")),
            pystray.MenuItem("Donate...", lambda i, it: self.q.put("donate")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda i, it: self.q.put("quit")),
        )
        self.icon = pystray.Icon("autosongs-bridge", make_icon("stopped"), APP_NAME, menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def _listen_lock(self):
        # A second launch connects here and asks the running copy to show or quit.
        while True:
            try:
                conn, _ = self.lock_sock.accept()
            except OSError:
                return
            with conn:
                data = conn.recv(64).decode("ascii", "ignore").strip()
            self.q.put(data or "show")

    # actions --------------------------------------------------------
    def toggle_bridge(self):
        if self.bridge.active():
            threading.Thread(target=self.bridge.stop, daemon=True).start()
        else:
            threading.Thread(target=self.bridge.start, daemon=True).start()

    def toggle_autostart(self):
        set_autostart(self.autostart_var.get())
        self.autostart_var.set(autostart_enabled())

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def open_log(self):
        os.makedirs(DIR, exist_ok=True)
        open(LOG, "a", encoding="utf-8").close()
        if IS_WIN:
            os.startfile(LOG)  # noqa: S606 - opening the user's own log
        else:
            subprocess.Popen(["xdg-open", LOG])

    def open_donate(self):
        import webbrowser
        webbrowser.open(DONATE_URL)

    def quit(self):
        self.bridge.stop()
        if self.icon is not None:
            self.icon.stop()
        self.root.destroy()

    def open_pair(self):
        if self.pair_win is not None and self.pair_win.winfo_exists():
            self.pair_win.lift()
            return
        w = tk.Toplevel(self.root)
        w.title("Pair a phone")
        w.resizable(False, False)
        f = ttk.Frame(w, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="On the phone: AutoSongs > Settings > Pair remote bridge",
                  font=("Segoe UI", 10)).pack(anchor="w")
        ttk.Label(f, text="Type this code:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 0))
        self.pair_short = tk.StringVar(value="--------")
        ttk.Label(f, textvariable=self.pair_short, font=("Consolas", 26, "bold")).pack(anchor="w")
        ttk.Button(f, text="Copy code", command=lambda: self.copy(self.pair_short.get())).pack(anchor="w", pady=(4, 0))
        ttk.Label(f, text="If the phone cannot find the bridge, paste this long code:",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(12, 0))
        self.pair_long = tk.StringVar(value="")
        ttk.Entry(f, textvariable=self.pair_long, width=60, state="readonly").pack(anchor="w", fill="x")
        ttk.Button(f, text="Copy long code", command=lambda: self.copy(self.pair_long.get())).pack(anchor="w", pady=(4, 0))
        self.pair_addr = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.pair_addr).pack(anchor="w", pady=(12, 0))
        self.pair_note = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.pair_note, wraplength=460, foreground="#666").pack(anchor="w", pady=(4, 0))
        self.pair_win = w
        if not self.bridge.active():
            threading.Thread(target=self.bridge.start, daemon=True).start()

    def copy(self, text):
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def update_pair(self, snap):
        if self.pair_win is None or not self.pair_win.winfo_exists():
            return
        self.pair_short.set(snap["short"] or "--------")
        self.pair_long.set(snap["long"])
        self.pair_addr.set("Address: " + snap["address"] if snap["address"] else "")
        if snap["short"]:
            self.pair_note.set("A new code is made each time the bridge starts. Stop and start the bridge for a new one.")
        else:
            self.pair_note.set("Waiting for the bridge to start... " + snap["message"])

    # loop -----------------------------------------------------------
    def handle(self, action):
        if action == "toggle":
            self.toggle_bridge()
        elif action == "pair":
            self.open_pair()
        elif action in ("show", "hide"):
            self.show() if action == "show" else self.root.withdraw()
        elif action == "log":
            self.open_log()
        elif action == "donate":
            self.open_donate()
        elif action == "autostart":
            self.toggle_autostart()
        elif action == "quit":
            self.quit()

    def tick(self):
        if not self.root.winfo_exists():
            return
        while True:
            try:
                action = self.q.get_nowait()
            except queue.Empty:
                break
            if action == "quit":
                self.handle(action)
                return
            self.handle(action)

        snap = self.bridge.snapshot()
        state = snap["state"]
        self.status_var.set(STATE_TEXT[state])
        self.detail_var.set(snap["message"])
        self.btn_toggle.config(text="Stop bridge" if state in ("starting", "running") else "Start bridge")
        self.update_pair(snap)
        if self.icon is not None and state != self.icon_state:
            self.icon_state = state
            self.icon.icon = make_icon(state)
            self.icon.title = "%s: %s" % (APP_NAME, STATE_TEXT[state])
        self.autostart_var.set(autostart_enabled())
        self.root.after(400, self.tick)

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------- install / main
def same_file(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


UNINSTALL_NAME = "AutoSongsBridgeUninstall.exe"


def make_shortcut(lnk, target, workdir):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
          "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.Save()") % (lnk, target, workdir)
    r = run_quiet(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], 60)
    if r.returncode != 0 or not os.path.exists(lnk):
        raise RuntimeError("could not create Start menu shortcut: " + (r.stderr or r.stdout).strip())


def bundled_uninstaller():
    """The uninstaller is packed inside this exe; it is copied out at install time."""
    path = os.path.join(getattr(sys, "_MEIPASS", ""), UNINSTALL_NAME)
    if not os.path.exists(path):
        raise RuntimeError("this build does not contain the uninstaller")
    return path


def install_windows():
    """Copies the app and its uninstaller into place, adds Start menu entries and sign-in autostart."""
    uninstaller_src = bundled_uninstaller()
    start_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME)
    os.makedirs(INSTALL_DIR, exist_ok=True)
    shutil.copy2(SELF, INSTALL_EXE)
    shutil.copy2(uninstaller_src, os.path.join(INSTALL_DIR, UNINSTALL_NAME))
    os.makedirs(start_dir, exist_ok=True)
    old = os.path.join(os.path.dirname(start_dir), APP_NAME + ".lnk")
    if os.path.exists(old):
        os.remove(old)
    make_shortcut(os.path.join(start_dir, APP_NAME + ".lnk"), INSTALL_EXE, INSTALL_DIR)
    make_shortcut(os.path.join(start_dir, APP_NAME + " - Uninstall.lnk"),
                  os.path.join(INSTALL_DIR, UNINSTALL_NAME), INSTALL_DIR)
    set_autostart(True)
    subprocess.Popen([INSTALL_EXE], cwd=INSTALL_DIR, close_fds=True, **hidden_kwargs())


def uninstall_windows():
    unins = os.path.join(INSTALL_DIR, UNINSTALL_NAME)
    if os.path.exists(unins):
        subprocess.Popen([unins], cwd=INSTALL_DIR, close_fds=True, **hidden_kwargs())
    else:
        print("Uninstaller not found at " + unins)


def main(argv):
    if "--uninstall" in argv:
        if IS_WIN:
            uninstall_windows()
        else:
            print("On Linux, use the installer's --uninstall option.")
        return 0

    if IS_WIN and FROZEN and "--no-install" not in argv and not same_file(SELF, INSTALL_EXE):
        install_windows()
        return 0

    lock = acquire_lock()
    if lock is None:
        send_to_running("show")
        return 0
    App(tray_only="--tray" in argv, lock_sock=lock).run()
    return 0


def _crash_to_log(exc_type, exc, tb):
    import traceback
    try:
        log_line("GUI crashed:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.excepthook = _crash_to_log
    threading.excepthook = lambda args: _crash_to_log(args.exc_type, args.exc_value, args.exc_traceback)
    sys.exit(main(sys.argv[1:]))
