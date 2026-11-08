#!/usr/bin/env python3
"""AutoSongs Bridge - tray app, with the Windows setup wizard implementation.

AutoSongsBridge.exe opens the tray app. AutoSongsBridgeSetup.exe uses the
SetupWizard below to install that app and its uninstaller. The tray app starts
and stops the bridge, shows the pairing code, and sets where music goes.

Options:
  --tray            start hidden in the tray and start the bridge (used at sign-in)
  --uninstall       (Windows) run the uninstaller from the install folder
"""
import json
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
from tkinter import ttk, filedialog, messagebox

import pystray
from PIL import Image, ImageDraw

IS_WIN = os.name == "nt"
FROZEN = bool(getattr(sys, "frozen", False))
APP_NAME = "AutoSongs Bridge"
APP_EXE_NAME = "AutoSongsBridge.exe"
UNINSTALL_NAME = "AutoSongsBridgeUninstall.exe"
# Donate target: the AutoSongs Ko-fi page.
DONATE_URL = "https://ko-fi.com/autosongs"
PORT = 8765
LOCK_PORT = 47865  # single-instance guard; a second launch just shows the window
HOME = os.path.expanduser("~")
DIR = os.path.join(HOME, ".autosongs")
BRIDGE = os.path.join(DIR, "ytbridge.py")
LOG = os.path.join(DIR, "bridge.log")
CONFIG = os.path.join(DIR, "config.json")
DEFAULT_MUSIC = os.path.join(HOME, "Music")

# The bridge core is published only at AutoSongs' own site; the old
# throwaway host names are gone from this launcher so it can never pick
# up an old published copy.
HOSTS = [
    "https://autosongs.example",
]

SELF = os.path.abspath(sys.executable if FROZEN else __file__)
LOCALAPP = os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
DEFAULT_INSTALL = os.path.join(LOCALAPP, APP_NAME)
PROGRAMS_DIR = os.path.join(APPDATA, "Microsoft", "Windows", "Start Menu", "Programs")
START_MENU = os.path.join(PROGRAMS_DIR, APP_NAME)
OLD_SHORTCUT = os.path.join(PROGRAMS_DIR, APP_NAME + ".lnk")  # left by earlier builds
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "AutoSongsBridge"
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
    # A cookie jar makes YouTube treat this computer like a signed-in
    # browser, which is the reliable way past the "Sign in to confirm
    # you're not a bot" refusal. The path comes from the settings, so the
    # jar the user chose is the one that is used.
    jar = load_config().get("cookies_file") or ""
    if jar and os.path.isfile(jar):
        env["YTBRIDGE_COOKIES"] = jar
    else:
        env.pop("YTBRIDGE_COOKIES", None)
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


def ps_quote(text):
    """A value safe inside a single-quoted PowerShell string."""
    return str(text).replace("'", "''")


def same_dir(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def load_config():
    cfg = {}
    try:
        with open(CONFIG, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        pass
    cfg.setdefault("music_dir", DEFAULT_MUSIC)
    cfg.setdefault("cookies_file", "")
    # Whether to open a tunnel to the internet. Off by default: it puts
    # the bridge on a public address, and that is the user's call.
    cfg.setdefault("tunnel", False)
    return cfg


def save_config(cfg):
    os.makedirs(DIR, exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


def bridge_cookie_status(port=PORT):
    """What the bridge says about cookies: (in use, where from).

    The bridge looks for a jar on its own, so it is asked rather than
    guessed - the answer says where the jar came from.
    """
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/cookies" % port,
                                    timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return bool(data.get("cookies")), (data.get("source") or "")
    except Exception:
        return False, ""


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


def pip_install_yt_dlp(py):
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
        if not pip_install_yt_dlp(py):
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


def desktop_dir():
    try:
        r = run_quiet(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"], 30)
        path = r.stdout.strip()
        if r.returncode == 0 and path and os.path.isdir(path):
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.join(HOME, "Desktop")


def make_shortcut(lnk, target, workdir):
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
          "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.Save()") % (
        ps_quote(lnk), ps_quote(target), ps_quote(workdir))
    r = run_quiet(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], 60)
    if r.returncode != 0 or not os.path.exists(lnk):
        raise RuntimeError("could not create shortcut %s: %s" % (
            os.path.basename(lnk), (r.stderr or r.stdout).strip()))


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


def autostart_command(exe=None):
    exe = exe or SELF
    if IS_WIN:
        return '"%s" --tray' % exe
    return '"%s" "%s" --tray' % (sys.executable, exe)


def set_autostart(on, exe=None):
    if IS_WIN:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if on:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, autostart_command(exe))
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
        # The tunnel's address, when there is one.
        self.public_url = ""
        self.user_stop = False

    def snapshot(self):
        with self.lock:
            return {"state": self.state, "message": self.message, "short": self.short,
                    "long": self.long, "address": self.address,
                    "public_url": self.public_url}

    def active(self):
        return self.snapshot()["state"] in ("starting", "running")

    def start(self):
        with self.lock:
            if self.state in ("starting", "running"):
                return
            self.state = "starting"
            self.message = "Getting ready..."
            self.short = self.long = self.address = self.public_url = ""
            self.user_stop = False
        try:
            py = prepare(lambda m: self._say(m))
        except BaseException as exc:  # noqa: BLE001 - shown in the window
            import traceback
            log_line(traceback.format_exc())
            self._fail(str(exc) or type(exc).__name__)
            return
        music = load_config()["music_dir"]
        try:
            os.makedirs(music, exist_ok=True)
        except OSError as exc:
            self._fail("The music folder cannot be used: %s" % exc)
            return
        with self.lock:
            if self.user_stop:
                self.state = "stopped"
                self.message = "Stopped."
                return
        cmd = py + [BRIDGE, "--pair", "--port", str(PORT), "--library-dir", music]
        # The tunnel is read when the bridge starts, so it is passed on
        # the command line here. Without this the checkbox saves the
        # setting and nothing else - the bridge would come up exactly as
        # it did before and the user would think it was broken.
        if load_config().get("tunnel"):
            cmd.append("--tunnel")
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
                    if "reachable at" in line:
                        # The tunnel's address. The phone cannot find a
                        # bridge on another network by looking for it, so
                        # this is shown next to the code.
                        #
                        # The lock is not taken again here: it is not
                        # re-entrant, and taking it twice from the same
                        # thread would wait for itself and stop the
                        # bridge's output from ever being read again.
                        self.public_url = line.split("reachable at", 1)[1].strip()
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


def port_in_use(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


def send_to_running(message):
    try:
        with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=2) as conn:
            conn.sendall(message.encode("ascii"))
        return True
    except OSError:
        return False


# ----------------------------------------------------------- install
def bundled(name):
    """A file packed into this exe (PyInstaller unpacks it to _MEIPASS)."""
    path = os.path.join(getattr(sys, "_MEIPASS", ""), name)
    if not os.path.exists(path):
        raise RuntimeError("this build does not contain " + name)
    return path


def do_install(s, log):
    """Install with the choices in s. Called by the setup wizard.

    s keys: install_dir, music_dir, uninstaller, startmenu, desktop, boot.
    The app and the uninstaller come from the bundle of the running exe.
    """
    target = os.path.abspath(s["install_dir"])
    exe = os.path.join(target, APP_EXE_NAME)
    log("Stopping AutoSongs Bridge if it is running...")
    if send_to_running("quit"):
        for _ in range(40):
            if not port_in_use(LOCK_PORT):
                break
            threading.Event().wait(0.5)
    log("Creating %s" % target)
    os.makedirs(target, exist_ok=True)
    log("Copying program files...")
    shutil.copy2(bundled(APP_EXE_NAME), exe)
    if s["uninstaller"]:
        log("Adding the uninstaller...")
        shutil.copy2(bundled(UNINSTALL_NAME), os.path.join(target, UNINSTALL_NAME))
    if s["startmenu"]:
        log("Creating Start menu shortcuts...")
        if os.path.exists(OLD_SHORTCUT):
            os.remove(OLD_SHORTCUT)
        make_shortcut(os.path.join(START_MENU, APP_NAME + ".lnk"), exe, target)
        if s["uninstaller"]:
            make_shortcut(os.path.join(START_MENU, APP_NAME + " - Uninstall.lnk"),
                          os.path.join(target, UNINSTALL_NAME), target)
    if s["desktop"]:
        log("Creating the desktop icon...")
        make_shortcut(os.path.join(desktop_dir(), APP_NAME + ".lnk"), exe, target)
    log("Setting start when I sign in: " + ("on" if s["boot"] else "off"))
    set_autostart(bool(s["boot"]), exe)
    music = os.path.abspath(s["music_dir"])
    log("Making the music folder %s" % music)
    os.makedirs(music, exist_ok=True)
    cfg = load_config()
    cfg["install_dir"] = target
    cfg["music_dir"] = music
    save_config(cfg)
    log("Installed.")


class SetupWizard:
    """Welcome > location > add-ons > music folder > install > finish."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME + " Setup")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self.body = ttk.Frame(self.root, padding=20)
        self.body.pack(fill="both", expand=True)
        bar = ttk.Frame(self.root, padding=(20, 0, 20, 16))
        bar.pack(fill="x")
        self.btn_cancel = ttk.Button(bar, text="Cancel", width=12, command=self.cancel)
        self.btn_cancel.pack(side="left")
        self.btn_next = ttk.Button(bar, text="Next >", width=12, command=self.on_next)
        self.btn_next.pack(side="right")
        self.btn_back = ttk.Button(bar, text="< Back", width=12, command=self.back)
        self.btn_back.pack(side="right", padx=6)

        self.install_dir = tk.StringVar(value=DEFAULT_INSTALL)
        self.music_dir = tk.StringVar(value=load_config()["music_dir"])
        self.opt = {
            "uninstaller": tk.BooleanVar(value=True),
            "startmenu": tk.BooleanVar(value=True),
            "desktop": tk.BooleanVar(value=True),
            "boot": tk.BooleanVar(value=True),
        }
        self.open_after = tk.BooleanVar(value=True)
        self.pages = [self.page_welcome, self.page_location, self.page_addons,
                      self.page_music, self.page_install, self.page_finish]
        self.index = 0
        self.busy = False
        self.logq = queue.Queue()
        self.nav = {}
        self.show()

    # navigation -----------------------------------------------------
    def show(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.nav = {"next": "Next >", "cmd": self.advance, "back": self.index > 0}
        self.pages[self.index]()
        self.btn_next.config(text=self.nav["next"], state="disabled" if self.busy else "normal")
        self.btn_back.config(state="normal" if self.nav["back"] and not self.busy else "disabled")
        self.btn_cancel.config(state="disabled" if self.busy else "normal")

    def on_next(self):
        self.nav["cmd"]()

    def advance(self):
        if not self.check_page():
            return
        self.index += 1
        self.show()

    def back(self):
        if self.index > 0 and not self.busy:
            self.index -= 1
            self.show()

    def cancel(self):
        if self.busy:
            return
        self.root.destroy()

    def check_page(self):
        if self.index == 1:
            path = self.install_dir.get().strip()
            if not path or not os.path.isabs(path):
                messagebox.showerror(APP_NAME, "Choose a full folder path for the program.", parent=self.root)
                return False
        if self.index == 3:
            path = self.music_dir.get().strip()
            if not path or not os.path.isabs(path):
                messagebox.showerror(APP_NAME, "Choose a full folder path for downloaded music.", parent=self.root)
                return False
        return True

    # pages ----------------------------------------------------------
    def page_welcome(self):
        ttk.Label(self.body, text="Welcome to AutoSongs Bridge Setup", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(self.body, wraplength=460, justify="left", text=(
            "This installs AutoSongs Bridge on this computer. Your phone uses it to download "
            "songs to this PC.\n\nClick Next to continue.")).pack(anchor="w", pady=(12, 0))

    def page_location(self):
        ttk.Label(self.body, text="Install location", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(self.body, text="Where should AutoSongs Bridge be installed?").pack(anchor="w", pady=(8, 6))
        row = ttk.Frame(self.body)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.install_dir, width=52).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self.browse_install).pack(side="left", padx=(6, 0))

    def browse_install(self):
        chosen = filedialog.askdirectory(parent=self.root, initialdir=os.path.dirname(self.install_dir.get()) or HOME,
                                         title="Choose the install folder")
        if chosen:
            self.install_dir.set(os.path.join(os.path.normpath(chosen), APP_NAME))

    def page_addons(self):
        ttk.Label(self.body, text="Add-ons", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(self.body, text="Choose what to set up:").pack(anchor="w", pady=(8, 6))
        ttk.Checkbutton(self.body, text="Uninstaller (remove AutoSongs Bridge later)",
                        variable=self.opt["uninstaller"]).pack(anchor="w", pady=2)
        ttk.Checkbutton(self.body, text="Start menu shortcuts", variable=self.opt["startmenu"]).pack(anchor="w", pady=2)
        ttk.Checkbutton(self.body, text="Desktop icon", variable=self.opt["desktop"]).pack(anchor="w", pady=2)
        ttk.Checkbutton(self.body, text="Start AutoSongs Bridge when I sign in (boot)",
                        variable=self.opt["boot"]).pack(anchor="w", pady=2)
        ttk.Label(self.body, wraplength=460, foreground="#666", justify="left", text=(
            "Windows does not let installers pin apps to the taskbar. When the bridge runs, its "
            "icon is in the tray, and you can pin it from the Start menu.")).pack(anchor="w", pady=(12, 0))

    def page_music(self):
        ttk.Label(self.body, text="Downloaded music", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(self.body, text="Where should downloaded music be saved?").pack(anchor="w", pady=(8, 6))
        row = ttk.Frame(self.body)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.music_dir, width=52).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self.browse_music).pack(side="left", padx=(6, 0))
        ttk.Label(self.body, wraplength=460, foreground="#666", justify="left", text=(
            "You can change this later from the app window.")).pack(anchor="w", pady=(10, 0))

    def browse_music(self):
        chosen = filedialog.askdirectory(parent=self.root, initialdir=self.music_dir.get() or DEFAULT_MUSIC,
                                         title="Choose the folder for downloaded music")
        if chosen:
            self.music_dir.set(os.path.normpath(chosen))

    def page_install(self):
        self.nav["next"] = "Install"
        self.nav["cmd"] = self.start_install
        ttk.Label(self.body, text="Ready to install", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        summary = [
            "Program folder: " + self.install_dir.get(),
            "Music folder: " + self.music_dir.get(),
            "Uninstaller: " + ("yes" if self.opt["uninstaller"].get() else "no"),
            "Start menu: " + ("yes" if self.opt["startmenu"].get() else "no"),
            "Desktop icon: " + ("yes" if self.opt["desktop"].get() else "no"),
            "Start when I sign in: " + ("yes" if self.opt["boot"].get() else "no"),
        ]
        ttk.Label(self.body, text="\n".join(summary), justify="left").pack(anchor="w", pady=(8, 10))
        self.progress = ttk.Progressbar(self.body, mode="indeterminate", length=460)
        self.progress.pack(anchor="w")
        self.log_text = tk.Text(self.body, height=7, width=62, state="disabled", wrap="word")
        self.log_text.pack(anchor="w", pady=(8, 0))

    def start_install(self):
        settings = {
            "install_dir": self.install_dir.get().strip(),
            "music_dir": self.music_dir.get().strip(),
            "uninstaller": self.opt["uninstaller"].get(),
            "startmenu": self.opt["startmenu"].get(),
            "desktop": self.opt["desktop"].get(),
            "boot": self.opt["boot"].get(),
        }
        self.busy = True
        self.btn_next.config(state="disabled")
        self.btn_back.config(state="disabled")
        self.btn_cancel.config(state="disabled")
        self.progress.start(12)

        def worker():
            try:
                do_install(settings, lambda m: self.logq.put(("log", m)))
                self.logq.put(("done", None))
            except Exception as exc:  # noqa: BLE001 - shown in the wizard
                log_line("install failed: %s" % exc)
                self.logq.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.poll_install()

    def poll_install(self):
        finished = None
        while True:
            try:
                kind, text = self.logq.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log_text.config(state="normal")
                self.log_text.insert("end", text + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
            else:
                finished = (kind, text)
        if finished is None:
            self.root.after(150, self.poll_install)
            return
        self.progress.stop()
        self.busy = False
        kind, text = finished
        if kind == "done":
            self.index += 1
            self.show()
        else:
            messagebox.showerror(APP_NAME, "Install did not finish:\n\n" + text, parent=self.root)
            self.show()

    def page_finish(self):
        self.nav["next"] = "Finish"
        self.nav["cmd"] = self.finish
        self.nav["back"] = False
        ttk.Label(self.body, text="AutoSongs Bridge is installed", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(self.body, wraplength=460, justify="left", text=(
            "Installed in:\n" + self.install_dir.get())).pack(anchor="w", pady=(12, 10))
        ttk.Checkbutton(self.body, text="Open AutoSongs Bridge", variable=self.open_after).pack(anchor="w")

    def finish(self):
        if self.open_after.get():
            exe = os.path.join(self.install_dir.get().strip(), APP_EXE_NAME)
            subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True, **hidden_kwargs())
        self.root.destroy()

    def run(self):
        self.root.mainloop()


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
        ttk.Label(frame, textvariable=self.detail_var, wraplength=420).pack(anchor="w", pady=(2, 12))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.btn_toggle = ttk.Button(row, text="Start bridge", command=lambda: self.q.put("toggle"), width=14)
        self.btn_toggle.pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Pair phone...", command=lambda: self.q.put("pair"), width=14).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Open log", command=lambda: self.q.put("log"), width=10).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Donate", command=lambda: self.q.put("donate"), width=10).pack(side="left")

        music = ttk.Frame(frame)
        music.pack(fill="x", pady=(14, 0))
        ttk.Label(music, text="Music folder:").pack(side="left")
        self.music_var = tk.StringVar(value=load_config()["music_dir"])
        ttk.Label(music, textvariable=self.music_var, wraplength=300).pack(side="left", padx=6)
        ttk.Button(music, text="Change...", command=self.change_music).pack(side="right")

        # The cookie jar. YouTube sometimes answers with "Sign in to confirm
        # you're not a bot" instead of the video, and a jar - the file a
        # signed-in browser can export - is what gets past it.
        jar = ttk.Frame(frame)
        jar.pack(fill="x", pady=(10, 0))
        ttk.Label(jar, text="cookies.txt:").pack(side="left")
        self.cookie_var = tk.StringVar(value=self.cookie_label())
        ttk.Label(jar, textvariable=self.cookie_var, wraplength=300).pack(side="left", padx=6)
        ttk.Button(jar, text="Choose...", command=self.change_cookies).pack(side="right")
        ttk.Button(jar, text="Remove", command=self.remove_cookies).pack(side="right", padx=(6, 0))

        # Reaching the bridge from another network. Off by default: it
        # puts the bridge on a public address, and that is the user's
        # decision, not the app's.
        self.tunnel_var = tk.BooleanVar(value=bool(load_config().get("tunnel")))
        tunnel_box = ttk.Checkbutton(
            frame,
            text="Reach this bridge from anywhere (opens a tunnel)",
            variable=self.tunnel_var, command=self.toggle_tunnel)
        tunnel_box.pack(anchor="w", pady=(14, 0))
        ttk.Label(
            frame,
            text="For a phone that is not on this network. Needs cloudflared "
                 "next to the bridge or in the user folder. The address "
                 "changes each time the bridge starts.",
            wraplength=340, foreground="#666666").pack(anchor="w", pady=(2, 0))

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
            pystray.MenuItem("Reach from anywhere", lambda i, it: self.q.put("tunnel"),
                             checked=lambda it: bool(load_config().get("tunnel"))),
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

    def toggle_tunnel_from_tray(self):
        """The tray menu flips the tunnel, and the window shows it."""
        self.tunnel_var.set(not bool(load_config().get("tunnel")))
        self.toggle_tunnel()
        self.show()

    def toggle_tunnel(self):
        """Turns the tunnel on or off, and says what happens now.

        The setting is read when the bridge starts, so changing it while
        the bridge is running does nothing until it is restarted - which
        is said out loud, because a checkbox that appears to do nothing
        is worse than no checkbox.
        """
        cfg = load_config()
        cfg["tunnel"] = bool(self.tunnel_var.get())
        save_config(cfg)
        if self.bridge.active():
            self.detail_var.set(
                "The tunnel setting is saved. Stop the bridge and start it "
                "again for it to take effect.")
        else:
            self.detail_var.set(
                "The tunnel is on. The bridge will be given a public "
                "address next time it starts.")

    def change_music(self):
        cfg = load_config()
        chosen = filedialog.askdirectory(parent=self.root, initialdir=cfg["music_dir"],
                                         title="Choose the folder for downloaded music")
        if not chosen:
            return
        cfg["music_dir"] = os.path.normpath(chosen)
        save_config(cfg)
        self.music_var.set(cfg["music_dir"])
        self.detail_var.set("Music folder changed. It is used the next time the bridge starts.")

    def cookie_label(self):
        """What to show about the cookie jar.

        The bridge is asked, because the bridge looks for a jar on its own
        and is the one that uses it. The answer says where it came from.
        """
        chosen = load_config().get("cookies_file") or ""
        in_use, source = bridge_cookie_status()
        if in_use and source:
            return "%s (in use)" % source
        if chosen:
            return os.path.basename(chosen)
        return "none - YouTube may ask you to sign in"

    def change_cookies(self):
        """Chooses a cookie jar, or takes the one that is there away."""
        cfg = load_config()
        chosen = filedialog.askopenfilename(
            parent=self.root, initialdir=os.path.dirname(cfg.get("cookies_file") or "") or HOME,
            title="Choose your cookies.txt",
            filetypes=[("Cookie jars", "*.txt"), ("All files", "*.*")])
        if not chosen:
            return
        chosen = os.path.normpath(chosen)
        try:
            with open(chosen, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(4096)
        except OSError as exc:
            messagebox.showerror(APP_NAME, "That file could not be read: %s" % exc,
                                 parent=self.root)
            return
        if "Netscape HTTP Cookie File" not in head and "#HttpOnly_" not in head:
            # A file that is not a jar would make every download fail in a
            # way that is much harder to explain than this.
            messagebox.showerror(
                APP_NAME,
                "That file is not a cookies.txt file.\n\n"
                "A cookie jar starts with a line saying:\n"
                "# Netscape HTTP Cookie File",
                parent=self.root)
            return
        cfg["cookies_file"] = chosen
        save_config(cfg)
        self.cookie_var.set(self.cookie_label())
        self.detail_var.set(
            "Cookie jar chosen. It is used the next time the bridge starts.")

    def remove_cookies(self):
        cfg = load_config()
        cfg["cookies_file"] = ""
        save_config(cfg)
        self.cookie_var.set(self.cookie_label())
        self.detail_var.set("The cookie jar was removed.")

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
        # Which code to use depends on how the bridge is reached, and
        # getting it wrong means the phone pairs with nothing.
        self.pair_which = tk.StringVar(value="Type this code:")
        ttk.Label(f, textvariable=self.pair_which,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 0))
        self.pair_short = tk.StringVar(value="--------")
        ttk.Label(f, textvariable=self.pair_short, font=("Consolas", 26, "bold")).pack(anchor="w")
        ttk.Button(f, text="Copy code", command=lambda: self.copy(self.pair_short.get())).pack(anchor="w", pady=(4, 0))
        self.pair_long_label = tk.StringVar(
            value="If the phone cannot find the bridge, paste this long code:")
        ttk.Label(f, textvariable=self.pair_long_label,
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
        public = snap.get("public_url") or ""
        self.pair_short.set(snap["short"] or "--------")
        self.pair_long.set(snap["long"])
        if public:
            # The bridge is on the internet. The phone is not on this
            # network, so the eight characters are not enough - the long
            # code carries the address and the key.
            self.pair_which.set("Paste this long code:")
            self.pair_long_label.set(
                "This bridge is on the internet, so the phone cannot find "
                "it by itself.\nPaste this long code - it carries the "
                "address and the key:")
            self.pair_addr.set("Reachable at: " + public)
        else:
            self.pair_which.set("Type this code:")
            self.pair_long_label.set(
                "If the phone cannot find the bridge, paste this long code:")
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
        elif action == "tunnel":
            self.toggle_tunnel_from_tray()
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
            self.handle(action)
            if action == "quit":
                return

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


# --------------------------------------------------------- main
def main(argv):
    if IS_WIN and "--uninstall" in argv:
        unins = os.path.join(os.path.dirname(SELF), UNINSTALL_NAME)
        if os.path.exists(unins):
            subprocess.Popen([unins], cwd=os.path.dirname(unins), close_fds=True, **hidden_kwargs())
        else:
            print("Uninstaller not found at " + unins)
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
