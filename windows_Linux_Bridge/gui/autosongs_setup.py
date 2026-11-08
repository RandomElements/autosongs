"""AutoSongs Bridge Setup: the one-file installer.

Always opens the setup wizard. The app and the uninstaller are packed inside
this exe, and the wizard copies them to the chosen folder.
"""
import sys
import threading

from autosongs_bridge_app import SetupWizard, _crash_to_log


if __name__ == "__main__":
    sys.excepthook = _crash_to_log
    threading.excepthook = lambda args: _crash_to_log(args.exc_type, args.exc_value, args.exc_traceback)
    SetupWizard().run()
