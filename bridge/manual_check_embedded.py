#!/usr/bin/env python3
"""The whole job, the way the app inside the phone runs it.

The bridge inside the app cannot start programs, so it calls yt-dlp as a
library. This runs exactly that path: search, download, check the file,
and hand it over. It needs the network, so it is a manual check rather
than part of the test suite.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ytbridge  # noqa: E402


def main():
    work = tempfile.mkdtemp(prefix="embedded_")
    ytbridge.EMBEDDED = True
    ytbridge.WORKDIR = work
    ytbridge.TOKEN = ""
    ytbridge.CLIENTS_OVERRIDE = ""

    job = "job1"
    ytbridge.JOBS[job] = {}
    title = "Never Gonna Give You Up"
    artist = "Rick Astley"

    print("== running the job (search + download + hand over)")
    ytbridge.run_job(job, "Rick Astley - Never Gonna Give You Up",
                      "audio_m4a", 1080, True, True, title, artist, 213)

    state = ytbridge.JOBS[job]
    print("   status   :", state.get("status"))
    print("   title    :", state.get("title"))
    print("   artist   :", state.get("artist"))
    print("   file     :", state.get("file"))
    print("   note     :", state.get("note"))
    print("   error    :", state.get("error"))

    if state.get("status") != "done":
        print("FAIL  the job did not finish")
        return 1
    path = state.get("file") or ""
    if not path or not os.path.isfile(path):
        print("FAIL  there is no file")
        return 1
    size = os.path.getsize(path)
    print("   size     : %.2f MB" % (size / 1048576.0))
    if size < 100000:
        print("FAIL  the file is too small to be a song")
        return 1

    print("\n== the video preset must refuse politely")
    job2 = "job2"
    ytbridge.JOBS[job2] = {}
    ytbridge.run_job(job2, "Rick Astley - Never Gonna Give You Up",
                      "video_720", 720, True, True, title, artist, 213)
    state2 = ytbridge.JOBS[job2]
    print("   status   :", state2.get("status"))
    print("   error    :", state2.get("error"))
    if state2.get("status") != "error":
        print("FAIL  a video must not be pretended to work")
        return 1

    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
