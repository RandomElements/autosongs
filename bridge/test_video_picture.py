#!/usr/bin/env python3
"""A match with no picture must not be saved as a video.

This is the bug that showed up on the phone: the search found an
"official audio" first (its title fits the song better), that match has
no picture at all, and the format chain used to end in "best" - which,
for a match with no picture, is the sound. The sound carries the album
cover, so the phone joined it and saved an mp4 with the cover as a still
picture and the song playing with it.

So:

  - the bridge says whether a download has a picture,
  - the picture part never falls back to the sound,
  - a match without a picture is skipped and the next match is tried,
  - when no match has a picture, the bridge says so plainly.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ytbridge  # noqa: E402


def test_stream_flags():
    assert ytbridge._stream_flags({"vcodec": "h264", "acodec": "none"}) == \
        (True, False)
    assert ytbridge._stream_flags({"vcodec": "none", "acodec": "mp4a.40.2"}) == \
        (False, True)
    assert ytbridge._stream_flags({"vcodec": "none", "acodec": "none"}) == \
        (False, False)
    # a merged download carries two formats
    merged = {"requested_formats": [
        {"vcodec": "h264", "acodec": "none"},
        {"vcodec": "none", "acodec": "mp4a.40.2"}]}
    assert ytbridge._stream_flags(merged) == (True, True)
    print("OK  the bridge can tell a picture from a sound")


def test_the_picture_never_falls_back_to_the_sound():
    src = open(os.path.join(HERE, "ytbridge.py"), encoding="utf-8").read()
    # the chain for the picture must not end in "best": for a match with no
    # picture that is the sound, and the sound carries the album cover
    assert '"bestvideo[height<=%d][ext=mp4]/bestvideo[height<=%d]/best" % (q, q)' \
        not in src
    assert '"bestvideo[height<=%d][ext=mp4]/bestvideo[height<=%d]" % (q, q)' in src
    print("OK  the picture never falls back to the sound")


def test_a_match_without_a_picture_is_skipped():
    """The job tries the matches one after the other."""
    tmp = tempfile.mkdtemp(prefix="ytbridge_video_")
    outdir = os.path.join(tmp, "job")
    os.makedirs(outdir)

    calls = []

    def fake_part(url, outdir, fmt, fallback_fmt, suffix, clients, progress,
                  info):
        """Stands in for the download: the first match has no picture."""
        calls.append(url)
        if len(calls) == 1:
            # a sound file with the album cover in it
            path = os.path.join(outdir, "Sound.video.m4a")
            with open(path, "wb") as fh:
                fh.write(b"\x00\x00\x00\x18ftypM4A ")
            return {"ok": True, "filepath": path, "title": "A Song",
                    "artist": "An Artist", "error": "", "note": "",
                    "has_video": False, "has_audio": True}
        path = os.path.join(outdir, "Video.video.mp4")
        with open(path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypmp42")
        return {"ok": True, "filepath": path, "title": "A Song",
                "artist": "An Artist", "error": "", "note": "",
                "has_video": True, "has_audio": False}

    def fake_audio_part(url, outdir, fmt, fallback_fmt, suffix, clients,
                        progress, info):
        path = os.path.join(outdir, "Video.audio.m4a")
        with open(path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypM4A ")
        return {"ok": True, "filepath": path, "title": "A Song",
                "artist": "An Artist", "error": "", "note": "",
                "has_video": False, "has_audio": True}

    saved = {}
    original_part = ytbridge._api_download_part
    ytbridge._api_download_part = fake_part
    try:
        # the sound part is fetched through the same helper, so the fake
        # has to tell the two apart
        def both(url, outdir, fmt, fallback_fmt, suffix, clients, progress,
                 info):
            if suffix == ".video":
                return fake_part(url, outdir, fmt, fallback_fmt, suffix,
                                 clients, progress, info)
            return fake_audio_part(url, outdir, fmt, fallback_fmt, suffix,
                                   clients, progress, info)
        ytbridge._api_download_part = both

        def update(**kw):
            saved.update(kw)

        ytbridge.WORKDIR = tmp
        ytbridge._run_embedded_video_job(
            "job1", ["https://youtube/watch?v=audio_only",
                     "https://youtube/watch?v=real_video"],
            outdir, "video_1080", 1080, update)
    finally:
        ytbridge._api_download_part = original_part

    assert saved.get("status") == "done", saved
    assert saved.get("parts") is True, saved
    assert saved.get("file_video", "").endswith(".video.mp4"), saved
    assert saved.get("file_audio", "").endswith(".audio.m4a"), saved
    assert len(calls) == 2, ("the first match has no picture, so it is "
                             "skipped and the second one is used")
    # the sound of the skipped match must not be left behind, or the
    # rescue path could later mistake it for a picture
    assert not os.path.exists(os.path.join(outdir, "Sound.video.m4a")), \
        "the file of the skipped match is still there"
    print("OK  a match without a picture is skipped and the next one is used")


def test_no_picture_anywhere_is_said_plainly():
    tmp = tempfile.mkdtemp(prefix="ytbridge_video_")
    outdir = os.path.join(tmp, "job")
    os.makedirs(outdir)

    def fake_part(url, outdir, fmt, fallback_fmt, suffix, clients, progress,
                  info):
        path = os.path.join(outdir, "Sound.video.m4a")
        with open(path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypM4A ")
        return {"ok": True, "filepath": path, "title": "A Song",
                "artist": "An Artist", "error": "", "note": "",
                "has_video": False, "has_audio": True}

    original_part = ytbridge._api_download_part
    ytbridge._api_download_part = fake_part
    saved = {}
    try:
        ytbridge.WORKDIR = tmp
        ytbridge._run_embedded_video_job(
            "job2", ["https://youtube/watch?v=one",
                     "https://youtube/watch?v=two"],
            outdir, "video_1080", 1080, lambda **kw: saved.update(kw))
    finally:
        ytbridge._api_download_part = original_part

    assert saved.get("status") == "error", saved
    assert "no picture" in (saved.get("error") or ""), saved
    print("OK  when no match has a picture the bridge says so")


def test_the_official_video_is_asked_for_by_name():
    """The official video is often not in the results at all."""
    asked = []

    def fake_search(query, depth=None):
        asked.append(query)
        if "official video" in query:
            return [{"id": "vid", "title": "A Song (Official Video)",
                     "artist": "An Artist", "duration": 200}]
        return [{"id": "aud", "title": "A Song", "artist": "An Artist",
                 "duration": 200}]

    original = ytbridge.search_candidates
    ytbridge.search_candidates = fake_search
    try:
        found = ytbridge.search_candidates_with_video(
            "A Song - An Artist", [{"id": "aud", "title": "A Song",
                                    "artist": "An Artist", "duration": 200}])
    finally:
        ytbridge.search_candidates = original

    assert asked == ["A Song - An Artist official video"], asked
    # the video comes first, so it is tried before the audio that has no
    # picture at all
    assert found[0]["id"] == "vid", found
    assert found[1]["id"] == "aud", found
    # and nothing is listed twice
    ids = [c["id"] for c in found]
    assert len(ids) == len(set(ids)), ids
    print("OK  the official video is asked for by name and tried first")


def test_a_failing_search_does_not_stop_the_job():
    def fake_search(query, depth=None):
        raise RuntimeError("YouTube said no")

    original = ytbridge.search_candidates
    ytbridge.search_candidates = fake_search
    try:
        found = ytbridge.search_candidates_with_video(
            "A Song", [{"id": "aud", "title": "A Song"}])
    finally:
        ytbridge.search_candidates = original
    assert len(found) == 1, found
    print("OK  a failing search for the video leaves the other results alone")


def main():
    test_stream_flags()
    test_the_picture_never_falls_back_to_the_sound()
    test_a_match_without_a_picture_is_skipped()
    test_no_picture_anywhere_is_said_plainly()
    test_the_official_video_is_asked_for_by_name()
    test_a_failing_search_does_not_stop_the_job()
    print("video picture: all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
