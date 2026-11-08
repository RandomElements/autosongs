#!/usr/bin/env python3
"""Proves the bridge's in-process path really downloads.

This is the path the app uses: yt-dlp called through its own Python
interface instead of as a command. If this works, the app has everything
it needs inside one APK.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ytbridge  # noqa: E402


def main():
    ytbridge.EMBEDDED = True
    work = tempfile.mkdtemp(prefix="apicheck_")
    ytbridge.WORKDIR = work
    ytbridge.TOKEN = ""

    print("== search")
    found = ytbridge.search_candidates("Rick Astley Never Gonna Give You Up", 3)
    for e in found:
        print("   %-14s %-52s %-22s %ss" % (
            e.get("id", ""), (e.get("title") or "")[:52],
            (e.get("channel") or "")[:22], e.get("duration", 0)))
    if not found:
        print("FAIL  nothing was found")
        return 1
    if not ytbridge.EMBEDDED:
        print("FAIL  the bridge did not switch to the in-process path")
        return 1

    print("== download")
    url = "https://www.youtube.com/watch?v=" + found[0]["id"]
    outdir = os.path.join(work, "job1")
    os.makedirs(outdir, exist_ok=True)

    ok, title, artist, path, err, note = ytbridge.api_download_attempt(
        url, outdir, "audio_m4a", "audio_m4a", False, False)
    print("   ok      :", ok)
    print("   title   :", title)
    print("   artist  :", artist)
    print("   file    :", path)
    print("   error   :", err)
    print("   note    :", note)
    if not ok:
        print("FAIL  the download did not work")
        return 1
    if not path or not os.path.exists(path):
        print("FAIL  there is no file")
        return 1
    size = os.path.getsize(path)
    print("   size    : %.2f MB" % (size / 1048576.0))
    if size < 100000:
        print("FAIL  the file is too small to be a song")
        return 1

    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
