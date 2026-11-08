"""The bridge, running as an app of its own.

The app starts this. It is the same bridge the AutoSongs app carries
inside it, but listening on the network so a phone can reach it.

Two things are different from the bridge inside the app:

  - it listens on every interface, not just this phone's own loopback
  - it shows a code, so a phone can find it and pair with it by itself
"""
import threading

_server = None
_pair_code = ""
_token = ""
_port = 8765


def start(port=8765, workdir="", library=""):
    """Starts the bridge and returns the code to type on the phone."""
    global _server, _pair_code, _token, _port
    if _server is not None:
        return _pair_code

    import ytbridge

    # The key is made once and kept, so a phone that is paired stays
    # paired after this app is closed and opened again.
    _token = ytbridge.load_or_make_secret()
    _pair_code = ytbridge.make_pair_code()
    _port = int(port)

    # The bridge reads this when a phone calls out and asks who is there.
    ytbridge.PAIR_CODE = _pair_code

    _server = ytbridge.make_server(
        "0.0.0.0", int(port), workdir, embedded=False,
        token=_token, library_dir=library)
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()

    # A phone that cannot hear a broadcast will look around the network
    # instead, and this is what answers it.
    ytbridge.start_pair_responder(int(port))
    return _pair_code


def stop():
    global _server
    if _server is not None:
        try:
            _server.shutdown()
        except Exception:
            pass
        _server = None
    return True


def code():
    """The eight characters the phone types."""
    return _pair_code


def address():
    """Where the phone should look for this bridge."""
    import ytbridge
    return "%s:%d" % (ytbridge.lan_address(), _port)


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
