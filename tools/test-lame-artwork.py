#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The mp3 must carry the cover inside it.

Android reads the artwork for a track out of the file itself - there is
no separate place to put it - so an mp3 without a picture in its tag is
a track with no cover in the library and no cover in a file manager.

The cover comes from the media session, is shrunk to 256 pixels, and is
handed to the encoder, which puts it in the tag. This drives the same
JNI code the app uses and then reads the tag back, so it can tell
whether the picture really went in.
"""

import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "lame_duration", os.path.join(HERE, "test-lame-duration.py"))
_duration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_duration)
build_library = _duration.build_library
JAVA_MAIN = """
import com.autosongs.ytdl.audio.LameEncoder;
import java.io.FileOutputStream;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Encodes a tone with a picture in its tag and writes the mp3 out. */
public class LameArtworkTest {
    public static void main(String[] args) throws Exception {
        String out = args[0];
        String library = args[1];
        String picture = args[2];
        int rate = 44100;
        int channels = 2;
        int frames = rate;

        System.load(library);

        byte[] art = Files.readAllBytes(Paths.get(picture));

        long handle = LameEncoder.nativeOpen(rate, channels, 192,
                "A Tone", "AutoSongs", "The Test", art);
        if (handle == 0) {
            throw new IllegalStateException("the encoder would not open");
        }

        FileOutputStream file = new FileOutputStream(out);
        file.write(LameEncoder.nativeId3Tag(handle));

        int perChunk = 4096;
        short[] pcm = new short[perChunk * channels];
        int done = 0;
        while (done < frames) {
            int n = Math.min(perChunk, frames - done);
            for (int i = 0; i < n; i++) {
                double t = (done + i) / (double) rate;
                short v = (short) (Math.sin(2 * Math.PI * 440 * t) * 20000);
                pcm[i * channels] = v;
                pcm[i * channels + 1] = v;
            }
            file.write(LameEncoder.nativeEncode(handle, pcm, n * channels));
            done += n;
        }
        file.write(LameEncoder.nativeFlush(handle));
        LameEncoder.nativeClose(handle);
        file.close();
        System.out.println("wrote " + out + " with " + art.length + " bytes of picture");
    }
}
"""

JAVA_STANDIN = """package com.autosongs.ytdl.audio;

public class LameEncoder {
    public static native long nativeOpen(int sampleRate, int channels, int bitrate,
                                         String title, String artist, String album,
                                         byte[] artwork);
    public static native byte[] nativeEncode(long handle, short[] pcm, int values);
    public static native byte[] nativeFlush(long handle);
    public static native byte[] nativeId3Tag(long handle);
    public static native void nativeClose(long handle);
}
"""


def id3_frames(data):
    """The frames inside an ID3v2 tag."""
    if data[:3] != b"ID3":
        raise ValueError("no ID3 tag at the front")
    size = 0
    for byte in data[6:10]:
        size = (size << 7) | (byte & 0x7F)
    start = 10
    end = start + size
    frames = []
    i = start
    while i + 10 <= end:
        name = data[i:i + 4]
        if name == b"\x00\x00\x00\x00":
            break
        length = 0
        for byte in data[i + 4:i + 8]:
            length = (length << 7) | (byte & 0x7F)
        frames.append((name, data[i + 10:i + 10 + length]))
        i += 10 + length
    return frames


def make_picture(path):
    """A small real jpeg, so the tag holds something a player can show."""
    try:
        from PIL import Image
        image = Image.new("RGB", (64, 64), (200, 40, 60))
        image.save(path, "JPEG")
        return True
    except Exception:
        pass
    # A jpeg header is enough for the test: the encoder stores the bytes
    # as they are and does not look inside them.
    with open(path, "wb") as handle:
        handle.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
                     b"\xff\xdb\x00C\x00" + bytes(64) +
                     b"\xff\xd9")
    return False


def main():
    library = build_library()

    work = "/tmp/autosongs-lame-host/art"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    src = os.path.join(work, "src")
    os.makedirs(os.path.join(src, "com", "autosongs", "ytdl", "audio"))
    with io.open(os.path.join(src, "com", "autosongs", "ytdl", "audio",
                              "LameEncoder.java"), "w", encoding="utf-8") as handle:
        handle.write(JAVA_STANDIN)
    with io.open(os.path.join(src, "LameArtworkTest.java"), "w",
                 encoding="utf-8") as handle:
        handle.write(JAVA_MAIN)

    classes = os.path.join(work, "classes")
    os.makedirs(classes)
    subprocess.check_call(["javac", "-d", classes] +
                          [os.path.join(src, "com", "autosongs", "ytdl", "audio",
                                        "LameEncoder.java"),
                           os.path.join(src, "LameArtworkTest.java")])

    picture = os.path.join(work, "cover.jpg")
    real = make_picture(picture)
    with open(picture, "rb") as handle:
        picture_bytes = handle.read()

    mp3 = os.path.join(work, "tone.mp3")
    subprocess.check_call(["java", "-cp", classes, "LameArtworkTest",
                           mp3, library, picture])

    with open(mp3, "rb") as handle:
        data = handle.read()

    frames = id3_frames(data)
    names = [name.decode("ascii", "replace") for name, _body in frames]
    print("the tag holds: %s" % ", ".join(names))
    if "APIC" not in names:
        print("FAIL  the mp3 has no picture in its tag")
        return 1

    body = dict(frames)[b"APIC"]
    # the frame is: encoding, mime type, picture type, description, data
    mime_end = body.index(b"\x00", 1)
    mime = body[1:mime_end].decode("ascii", "replace")
    description_end = body.index(b"\x00", mime_end + 2)
    picture_data = body[description_end + 1:]
    if picture_data != picture_bytes:
        print("FAIL  the picture in the tag is not the picture that was handed over "
              "(%d bytes in the tag, %d handed over)"
              % (len(picture_data), len(picture_bytes)))
        return 1
    if mime != "image/jpeg":
        print("FAIL  the picture in the tag is called %s" % mime)
        return 1
    print("OK  the mp3 carries the picture: %d bytes of %s%s"
          % (len(picture_data), mime, "" if real else " (a stand-in)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
