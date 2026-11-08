#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The sound must be asked for on its own, never with a picture.

yt-dlp's "bestaudio" means the best audio - and it may contain video.
For a music video the muxed stream wins, so the sound was taken out of
the video, and the video is longer than the song. A three minute song
came out as five minutes, and then the mp3 encoder made it ten.

So every chain that asks for sound now says that the format must have
no video in it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ytbridge


def test_the_sound_is_asked_for_on_its_own():
    for preset in ("audio_m4a", "audio_opus", "audio_mp3", "audio_original"):
        args = ytbridge._build_download_args(preset, 1080, False, False)
        fmt = args[args.index("-f") + 1]
        assert "vcodec=none" in fmt, (preset, fmt)
    print("OK  every sound chain asks for a format with no video in it")


def test_the_video_chain_takes_the_sound_on_its_own():
    args = ytbridge._build_download_args("video_720", 1080, False, False)
    fmt = args[args.index("-f") + 1]
    assert "bestaudio[ext=m4a][vcodec=none]" in fmt, fmt
    print("OK  the video chain takes the sound on its own too")


def test_the_plan_inside_the_app_says_the_same():
    for preset in ("audio_m4a", "audio_opus", "audio_mp3", "audio_original"):
        fmt, _note = ytbridge.api_download_plan(preset, 1080)
        assert fmt is not None, preset
        assert "vcodec=none" in fmt, (preset, fmt)
    print("OK  the plan inside the app asks for a format with no video in it")


def main():
    test_the_sound_is_asked_for_on_its_own()
    test_the_video_chain_takes_the_sound_on_its_own()
    test_the_plan_inside_the_app_says_the_same()
    print("the sound on its own: all good")


if __name__ == "__main__":
    main()
