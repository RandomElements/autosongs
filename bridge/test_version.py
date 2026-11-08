#!/usr/bin/env python3
"""The bridge must recognise an outdated yt-dlp.

An yt-dlp that is more than a few months old cannot download from YouTube at
all: every attempt ends in "HTTP Error 403: Forbidden". The phone in
question was running 2026.06.09 while the fix for that wave of 403s landed
in 2026.08.19. So the bridge has to notice the version, not just the error.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ytbridge  # noqa: E402

FAILED = []


def check(name, condition):
    if condition:
        print("   OK %s" % name)
    else:
        print("   FAIL %s" % name)
        FAILED.append(name)


def fake_version(value):
    """Pretend yt-dlp reports this version."""
    ytbridge._YTDLP_CACHE["version"] = value
    ytbridge._YTDLP_CACHE["at"] = 9e9  # far in the future: always fresh


print("== an old yt-dlp must be recognised")
fake_version("2026.06.09")
check("2026.06.09 is outdated", ytbridge.yt_dlp_is_outdated() is True)

print("== a current yt-dlp must be left alone")
fake_version("2026.10.26")
check("2026.10.26 is fine", ytbridge.yt_dlp_is_outdated() is False)

print("== the boundary version")
fake_version("2026.08.19")
check("2026.08.19 is fine", ytbridge.yt_dlp_is_outdated() is False)
fake_version("2026.08.18")
check("2026.08.18 is outdated", ytbridge.yt_dlp_is_outdated() is True)

print("== the version must be compared as a date, not as text")
# "2026.10.26" sorts before "2026.08.19" alphabetically, so a plain string
# comparison would call October older than August and break the check.
fake_version("2026.10.01")
check("October is newer than August", ytbridge.yt_dlp_is_outdated() is False)
fake_version("2027.01.01")
check("next year is newer", ytbridge.yt_dlp_is_outdated() is False)
fake_version("2025.12.31")
check("last year is older", ytbridge.yt_dlp_is_outdated() is True)

print("== odd versions must not crash")
fake_version("")
check("an empty version is not outdated", ytbridge.yt_dlp_is_outdated() is False)
fake_version("unknown")
check("'unknown' is not outdated", ytbridge.yt_dlp_is_outdated() is False)
fake_version("2026.10")
check("a partial version is not outdated", ytbridge.yt_dlp_is_outdated() is False)
fake_version("nightly")
check("a nightly build is not outdated", ytbridge.yt_dlp_is_outdated() is False)

print("== the minimum version is a real yt-dlp release")
check("the minimum has three numbers", len(ytbridge.MIN_YTDLP.split(".")) == 3)
check("the minimum is in the past", ytbridge.MIN_YTDLP < "2026.10.26")

print("== /health must tell the app that yt-dlp is too old")
source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "ytbridge.py"), encoding="utf-8").read()
check("health reports yt_dlp_outdated", '"yt_dlp_outdated"' in source)
check("health reports the minimum", '"yt_dlp_min"' in source)

print("== a failed download must try to update yt-dlp first")
check("the job retries after updating", "yt_dlp_is_outdated()" in source)
check("the update is logged", "updating it now" in source)

if FAILED:
    print("\nFAILED: %s" % ", ".join(FAILED))
    sys.exit(1)
print("\nPASS")
