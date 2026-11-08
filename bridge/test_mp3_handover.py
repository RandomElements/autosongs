#!/usr/bin/env python3
"""A bridge without ffmpeg must hand the sound over, not refuse the job.

The phone has an mp3 encoder of its own now, so the bridge never has to
re-encode anything. A bridge that tries anyway only produces an error -
"the mp3 conversion failed - ffmpeg is required" - and the user is left
with nothing at all.

That is exactly what was reported: the file was saved as M4A, and the
message blamed ffmpeg.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ytbridge  # noqa: E402


def main():
    original = ytbridge.has_ffmpeg
    try:
        # a bridge with ffmpeg re-encodes, as before
        ytbridge.has_ffmpeg = lambda: True
        args = ytbridge.build_download_args("audio_mp3", 1080, False, False)
        assert "--extract-audio" in args, \
            "with ffmpeg the bridge should re-encode"
        assert "mp3" in args, \
            "with ffmpeg the bridge should ask yt-dlp for an mp3"

        # a bridge without ffmpeg hands the sound over untouched
        ytbridge.has_ffmpeg = lambda: False
        args = ytbridge.build_download_args("audio_mp3", 1080, False, False)
        assert "--extract-audio" not in args, \
            "without ffmpeg the bridge cannot re-encode, so it must not ask"
        assert "mp3" not in args, \
            "without ffmpeg the bridge must not ask yt-dlp for an mp3"
        assert any("bestaudio" in a for a in args), \
            "the sound should still be asked for"
    finally:
        ytbridge.has_ffmpeg = original

    print("the sound is handed over for an mp3 request: all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
