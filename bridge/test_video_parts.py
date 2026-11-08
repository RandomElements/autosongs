#!/usr/bin/env python3
"""A video downloaded inside the app arrives in two pieces.

Joining the picture and the sound needs ffmpeg, and an app cannot run a
program. So the bridge hands over the two streams separately and the phone
joins them with MediaMuxer.

That means the bridge has to be able to say "here is the picture" and
"here is the sound" - and the rescue path has to find them again after a
restart, when the job list is gone but the files are still on disk.

This test puts two files on disk, pretends the bridge has a job with
both of them, and asks for each one.
"""

import json
import os
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ytbridge  # noqa: E402

PICTURE = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40
SOUND = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 40


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(port, path):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d%s" % (port, path), timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    tmp = tempfile.mkdtemp(prefix="ytbridge_parts_")
    work = os.path.join(tmp, "downloads")
    os.makedirs(work)

    picture_path = os.path.join(work, "Some Artist - Some Song.video.mp4")
    sound_path = os.path.join(work, "Some Artist - Some Song.audio.m4a")
    with open(picture_path, "wb") as fh:
        fh.write(PICTURE)
    with open(sound_path, "wb") as fh:
        fh.write(SOUND)

    port = free_port()
    server = ytbridge.make_server("127.0.0.1", port, workdir=work, embedded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # a job that finished in two pieces
        ytbridge.JOBS["job1"] = {
            "status": "done",
            "percent": 100,
            "title": "Some Song",
            "artist": "Some Artist",
            "has_file": True,
            "parts": True,
            "file_video": picture_path,
            "file_audio": sound_path,
        }

        # 1. the app can see that the job is in two pieces
        status, body = get(port, "/job/job1")
        assert status == 200, "the job did not answer: %s" % status
        job = json.loads(body.decode("utf-8"))
        assert job.get("parts") is True, "the job does not say it is in pieces"
        assert job.get("has_file") is True, "the job does not say it has a file"
        print("OK  the job says it produced two pieces")

        # 2. the picture comes on its own
        status, body = get(port, "/file/job1?part=video")
        assert status == 200, "the picture did not come: %s" % status
        assert body == PICTURE, "the picture is the wrong bytes"
        print("OK  the picture is handed over on its own")

        # 3. and so does the sound
        status, body = get(port, "/file/job1?part=audio")
        assert status == 200, "the sound did not come: %s" % status
        assert body == SOUND, "the sound is the wrong bytes"
        print("OK  the sound is handed over on its own")

        # 4. there is no joined file - the phone does that
        status, body = get(port, "/file/job1")
        assert status == 404, "a joined file was invented: %s" % status
        print("OK  there is no joined file - the phone joins the two")

        # 5. after a restart the job is gone but the files are still there
        status, body = get(
            port, "/find?name=Some%20Artist%20-%20Some%20Song&part=video")
        assert status == 200, "the picture was not found: %s" % status
        assert body == PICTURE, "the rescue found the wrong picture"
        print("OK  the picture is found again after a restart")

        status, body = get(
            port, "/find?name=Some%20Artist%20-%20Some%20Song&part=audio")
        assert status == 200, "the sound was not found: %s" % status
        assert body == SOUND, "the rescue found the wrong sound"
        print("OK  the sound is found again after a restart")

        # 6. a part that was never asked for is not handed over
        status, body = get(port, "/file/job1?part=lyrics")
        assert status == 404, "an unknown part was invented: %s" % status
        print("OK  an unknown part is refused")

    finally:
        server.shutdown()
        server.server_close()

    print("video parts: all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
