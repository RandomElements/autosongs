"""AutoSongs Bridge uninstaller.

Stops the tray app and the bridge, removes sign-in autostart and the Start
menu shortcut, and deletes the program folder. Optionally removes the
bridge's data folder (~/.autosongs: pairing key, logs, downloads).

  AutoSongsBridgeUninstall.exe          asks first, then uninstalls
  AutoSongsBridgeUninstall.exe --yes    no questions (scripts)
  AutoSongsBridgeUninstall.exe --yes --purge-data   also removes ~/.autosongs
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

IS_WIN = os.name == "nt"
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
FROZEN = bool(getattr(sys, "frozen", False))


def ask(question, default_yes):
    """A yes/no dialog. Returns the answer."""
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        return messagebox.askyesno(APP_NAME, question, default="yes" if default_yes else "no", parent=root)
    finally:
        root.destroy()


def say(title, text):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(title, text, parent=root)
        root.destroy()
    except Exception:  # noqa: BLE001 - no GUI available, the caller already printed
        print(text)


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


def stop_app():
    """Ask the running tray app to quit (it stops the bridge), then make sure nothing is left."""
    try:
        with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=2) as conn:
            conn.sendall(b"quit")
    except OSError:
        pass
    for _ in range(30):
        if not port_open(LOCK_PORT):
            break
        time.sleep(0.5)
    # Anything still running from the install folder is stopped too.
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


def remove_shortcuts():
    shutil.rmtree(START_DIR, ignore_errors=True)
    try:
        os.remove(OLD_SHORTCUT)
    except OSError:
        pass


def schedule_removal(folder, pid):
    """Delete the folder after this process has exited.

    The uninstaller lives inside the folder and stays locked while it runs, so
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
        fh.write((chr(13) + chr(10)).join(lines) + chr(13) + chr(10))
    subprocess.Popen(["cmd", "/c", bat], close_fds=True, creationflags=NO_WINDOW)


def remove_install_dir():
    if not os.path.isdir(INSTALL_DIR):
        return
    me = os.path.abspath(sys.executable if FROZEN else __file__)
    if me.lower().startswith(INSTALL_DIR.lower() + os.sep):
        schedule_removal(INSTALL_DIR, os.getpid())
    else:
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)


def main(argv):
    if not IS_WIN:
        print("This uninstaller is for Windows.")
        return 1
    assume_yes = "--yes" in argv
    purge = "--purge-data" in argv

    if not (os.path.isdir(INSTALL_DIR) or os.path.isdir(START_DIR) or os.path.exists(OLD_SHORTCUT)):
        say(APP_NAME, "AutoSongs Bridge is not installed.")
        return 0

    if not assume_yes:
        if not ask("Uninstall AutoSongs Bridge?", default_yes=False):
            return 0
        purge = ask("Also delete the bridge's data (pairing key, logs, downloads in %s)?" % DATA_DIR,
                    default_yes=False)

    stop_app()
    remove_autostart()
    remove_shortcuts()
    if purge and os.path.isdir(DATA_DIR):
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    remove_install_dir()

    if not assume_yes:
        say(APP_NAME, "AutoSongs Bridge has been uninstalled.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
