"""AutoSongs Bridge uninstaller (Windows).

A window with a checkbox for each thing to remove. Nothing is removed until
you press Uninstall. Start menu entries, the desktop icon, sign-in autostart,
the program files and the bridge's data folder are each optional.

  AutoSongsBridgeUninstall.exe          opens the window
  AutoSongsBridgeUninstall.exe --yes    removes all of it, no window (scripts)
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk, messagebox

IS_WIN = os.name == "nt"
FROZEN = bool(getattr(sys, "frozen", False))
APP_NAME = "AutoSongs Bridge"
HOME = os.path.expanduser("~")
DATA_DIR = os.path.join(HOME, ".autosongs")
LOCK_PORT = 47865
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "AutoSongsBridge"
LOCALAPP = os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
INSTALL_DIR = os.path.join(LOCALAPP, APP_NAME)
PROGRAMS_DIR = os.path.join(APPDATA, "Microsoft", "Windows", "Start Menu", "Programs")
START_DIR = os.path.join(PROGRAMS_DIR, APP_NAME)
OLD_SHORTCUT = os.path.join(PROGRAMS_DIR, APP_NAME + ".lnk")  # left by earlier builds
NO_WINDOW = 0x08000000


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


def stop_app():
    """Ask the tray app to quit (it stops the bridge), then stop anything left."""
    try:
        with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=2) as conn:
            conn.sendall(b"quit")
    except OSError:
        pass
    for _ in range(30):
        if not port_open(LOCK_PORT):
            break
        time.sleep(0.5)
    subprocess.run(["taskkill", "/F", "/IM", "AutoSongsBridge.exe", "/T"],
                   capture_output=True, creationflags=NO_WINDOW)
    time.sleep(1)


def remove_autostart():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_NAME)
    except OSError:
        pass


def remove_start_menu():
    shutil.rmtree(START_DIR, ignore_errors=True)
    try:
        os.remove(OLD_SHORTCUT)
    except OSError:
        pass


def remove_desktop_icon():
    for base in (os.path.join(HOME, "Desktop"), os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop")):
        try:
            os.remove(os.path.join(base, APP_NAME + ".lnk"))
        except OSError:
            pass


def schedule_removal(folder, pid):
    """Delete the program folder after this process exits.

    The uninstaller lives inside that folder and stays locked while it runs, so
    a batch file waits for this process to exit, then deletes the folder with
    retries. The batch file deletes itself at the end.
    """
    bat = os.path.join(tempfile.gettempdir(), "autosongs-bridge-cleanup.cmd")
    lines = [
        "@echo off",
        ":wait",
        'tasklist /FI "PID eq %d" 2>nul | find "%d" >nul' % (pid, pid),
        "if not errorlevel 1 (ping -n 2 127.0.0.1 >nul & goto wait)",
        "set /a tries=0",
        ":retry",
        'rmdir /s /q "%s" >nul 2>&1' % folder,
        'if not exist "%s" goto done' % folder,
        "set /a tries+=1",
        "if %tries% geq 30 goto done",
        "ping -n 2 127.0.0.1 >nul",
        "goto retry",
        ":done",
        '(goto) 2>nul & del /f /q "%~f0"',
    ]
    with open(bat, "w", encoding="ascii", newline="") as fh:
        fh.write("\r\n".join(lines) + "\r\n")
    subprocess.Popen(["cmd", "/c", bat], close_fds=True, creationflags=NO_WINDOW)


def remove_program_files():
    if not os.path.isdir(INSTALL_DIR):
        return
    me = os.path.abspath(sys.executable if FROZEN else __file__)
    if me.lower().startswith(INSTALL_DIR.lower() + os.sep):
        schedule_removal(INSTALL_DIR, os.getpid())
    else:
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)


def remove_data():
    shutil.rmtree(DATA_DIR, ignore_errors=True)


def run_selected(sel, log=print):
    """Remove the parts chosen in sel (a dict of name -> bool)."""
    log("Stopping AutoSongs Bridge...")
    stop_app()
    if sel["autostart"]:
        log("Removing start when I sign in...")
        remove_autostart()
    if sel["startmenu"]:
        log("Removing Start menu entries...")
        remove_start_menu()
    if sel["desktop"]:
        log("Removing the desktop icon...")
        remove_desktop_icon()
    if sel["data"]:
        log("Removing bridge data (pairing key, logs, config, downloads)...")
        remove_data()
    if sel["program"]:
        log("Removing the program files...")
        remove_program_files()
    log("Done.")


def installed_items():
    """Which parts are actually present, so the window only offers what can be removed."""
    return {
        "program": os.path.isdir(INSTALL_DIR),
        "startmenu": os.path.isdir(START_DIR) or os.path.exists(OLD_SHORTCUT),
        "desktop": os.path.exists(os.path.join(HOME, "Desktop", APP_NAME + ".lnk")),
        "autostart": _autostart_present(),
        "data": os.path.isdir(DATA_DIR),
    }


def _autostart_present():
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
        return True
    except OSError:
        return False


ITEMS = [
    ("program", "Program files", "Removes %s (the app and this uninstaller)." % INSTALL_DIR),
    ("startmenu", "Start menu entries", "Removes the AutoSongs Bridge Start menu folder."),
    ("desktop", "Desktop icon", "Removes the AutoSongs Bridge desktop shortcut."),
    ("autostart", "Start when I sign in", "Removes the sign-in entry."),
    ("data", "Bridge data (optional)", "Removes %s: pairing key, log, config and any downloads kept there. "
                                       "Music in your music folder is not touched." % DATA_DIR),
]


class UninstallWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME + " - Uninstall")
        self.root.resizable(False, False)
        present = installed_items()
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Uninstall AutoSongs Bridge", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Choose what to remove. Nothing is removed until you click Uninstall.",
                  wraplength=460).pack(anchor="w", pady=(6, 12))

        self.vars = {}
        for key, label, desc in ITEMS:
            present_here = present.get(key, False)
            var = tk.BooleanVar(value=present_here and key != "data")
            self.vars[key] = var
            state = "normal" if present_here else "disabled"
            ttk.Checkbutton(frame, text=label + ("" if present_here else "  (not found)"),
                            variable=var, state=state).pack(anchor="w", pady=(4, 0))
            ttk.Label(frame, text=desc, foreground="#666", wraplength=440).pack(anchor="w", padx=(22, 0))

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(18, 0))
        ttk.Button(bar, text="Select all", command=self.select_all).pack(side="left")
        ttk.Button(bar, text="Clear all", command=self.clear_all).pack(side="left", padx=6)
        ttk.Button(bar, text="Cancel", width=12, command=self.root.destroy).pack(side="right")
        ttk.Button(bar, text="Uninstall", width=12, command=self.uninstall).pack(side="right", padx=6)

    def select_all(self):
        for key, var in self.vars.items():
            if str(self._state(key)) != "disabled":
                var.set(True)

    def clear_all(self):
        for var in self.vars.values():
            var.set(False)

    def _state(self, key):
        return "normal" if installed_items().get(key) else "disabled"

    def uninstall(self):
        sel = {k: v.get() for k, v in self.vars.items()}
        if not any(sel.values()):
            messagebox.showinfo(APP_NAME, "Nothing is selected.", parent=self.root)
            return
        names = [label for key, label, _ in ITEMS if sel[key]]
        if not messagebox.askyesno(APP_NAME, "Remove these?\n\n- " + "\n- ".join(names), parent=self.root):
            return
        self.root.destroy()
        run_selected(sel)
        done = tk.Tk()
        done.withdraw()
        messagebox.showinfo(APP_NAME, "AutoSongs Bridge has been uninstalled.", parent=done)
        done.destroy()

    def run(self):
        self.root.mainloop()


def main(argv):
    if not IS_WIN:
        print("This uninstaller is for Windows.")
        return 1
    if "--yes" in argv:
        run_selected({"program": True, "startmenu": True, "desktop": True,
                      "autostart": True, "data": "--keep-data" not in argv})
        return 0
    if not any(installed_items().values()):
        messagebox.showinfo(APP_NAME, "AutoSongs Bridge is not installed.")
        return 0
    UninstallWindow().run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
