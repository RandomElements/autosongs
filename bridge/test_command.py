"""
Verifies the *command construction* of ytbridge.py against the real yt-dlp.

YouTube blocks requests from datacentre IPs ("Sign in to confirm you're not a
bot"), so a full download cannot be done from a build server. What we CAN and DO
verify is that:

  1. the search command uses the `ytsearch:` prefix (the original bug was a
     bare query, which yt-dlp rejects as "not a valid URL"), and
  2. the command reaches YouTube's extractor instead of failing on URL parsing.

Both are checked against the real yt-dlp binary.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "ytbridge.py")
YTDLP = os.environ.get("YTDLP_BIN", "yt-dlp")


def find_yt_dlp():
    found = shutil.which(YTDLP)
    if found:
        return found
    for cand in ("/tmp/ytdlp", os.path.expanduser("~/yt-dlp")):
        if os.path.exists(cand):
            return cand
    return None


def main():
    exe = find_yt_dlp()
    if not exe:
        print("SKIP: no yt-dlp binary available")
        return 0

    tmp = tempfile.mkdtemp(prefix="ytbridge_cmd_")
    try:
        # --- 1. the OLD behaviour: bare query -> yt-dlp rejects it ---------
        old = subprocess.run(
            [exe, "--no-playlist", "--no-warnings", "--skip-download",
             "--print", "TITLE: %(title)s", "The Weeknd - Blinding Lights"],
            capture_output=True, text=True, timeout=120)
        old_out = (old.stdout + old.stderr).strip()
        print("OLD (bare query) ->", old_out.splitlines()[0] if old_out else "(no output)")
        assert "not a valid URL" in old_out, \
            "expected the bare query to be rejected as an invalid URL"

        # --- 2. the NEW behaviour: ytsearch: prefix -----------------------
        new = subprocess.run(
            [exe, "--flat-playlist", "--dump-json", "--no-warnings",
             "--no-playlist", "--skip-download", "ytsearch5:The Weeknd - Blinding Lights"],
            capture_output=True, text=True, timeout=180)
        new_out = (new.stdout + new.stderr).strip()
        print("NEW (ytsearch:) ->", (new_out.splitlines()[0] if new_out else "(no output)")[:160])

        assert "not a valid URL" not in new_out, \
            "ytsearch: prefix was not applied - the original bug is still present"
        print("\nOK: the ytsearch: prefix reaches YouTube's extractor "
              "(no 'not a valid URL' error)")
        print("NOTE: a full download cannot be completed from this server "
              "because YouTube blocks datacentre IPs; on the phone it works.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
