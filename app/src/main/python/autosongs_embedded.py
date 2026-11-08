"""The bridge that runs inside the app.

The app starts this. Everything happens in the app's own Python, so there
is no Termux and no second program to install.
"""
import os
import sys
import threading

_server = None


def start(port=8765, workdir="", embedded=True):
    """Starts the bridge. Returns as soon as it is listening."""
    global _server
    if _server is not None:
        return True
    import ytbridge
    _server = ytbridge.make_server("127.0.0.1", int(port), workdir,
                                   embedded=bool(embedded))
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    return True


def stop():
    global _server
    if _server is not None:
        try:
            _server.shutdown()
        except Exception:
            pass
        _server = None
    return True


def version():
    import ytbridge
    return ytbridge.BRIDGE_VERSION


def yt_dlp_version():
    """The version of yt-dlp the bridge is using."""
    try:
        import yt_dlp
        return getattr(yt_dlp, "__version__", "") or ""
    except Exception:
        return ""


def use_ytdlp(directory):
    """Uses the yt-dlp in this folder instead of the one in the app.

    The app downloads the newest yt-dlp and puts it here. YouTube breaks
    yt-dlp every few months, and an old one cannot download anything - the
    symptom is "HTTP Error 403: Forbidden". Keeping this up to date is the
    difference between working and not.
    """
    if not directory or not os.path.isdir(directory):
        return False
    path = os.path.abspath(directory)
    if path not in sys.path:
        sys.path.insert(0, path)
    # The copy that came with the app must not win.
    for name in list(sys.modules):
        if name == "yt_dlp" or name.startswith("yt_dlp."):
            del sys.modules[name]
    try:
        import yt_dlp
        import ytbridge
        # The bridge has to use the same one.
        ytbridge.YTDL_PATH = os.path.join(path, "yt_dlp")
    except Exception:
        return False
    return True
