#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Encodes a known tone and measures the mp3 that comes out.

This is the test that was missing. The encoder was checked by "did it
produce some bytes" - and it did, and the bytes were a proper mp3, and
the track was twice as long as it should have been with half of it
noise, because LAME was told there were twice as many frames as there
were. Every check passed and the music was wrong.

So: encode three seconds of a 440 Hz tone, read the mp3 back, and count
its frames. The length has to be three seconds. A phone is not needed,
and this runs in a second.

The same JNI code that ships in the app is built for the desktop and
called through the same functions, so what is measured here is what the
phone does.
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CPP = os.path.join(HERE, "..", "app", "src", "main", "cpp")
LAME_SRC = "/workspace/build/lame/lame-3.100"
JAVA_HOME = os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64")
WORK = "/tmp/autosongs-lame-host"

JAVA_STANDIN = """package com.autosongs.ytdl.audio;

/**
 * The same native methods the app declares, so the JNI library can be
 * called from a plain desktop program. The system looks a native method
 * up by the name of the class that declares it, so the name has to be
 * exactly the one the app uses.
 */
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

JAVA_MAIN = """
import com.autosongs.ytdl.audio.LameEncoder;
import java.io.FileOutputStream;

/** Encodes a known number of seconds of a tone and writes the mp3 out. */
public class LameDurationTest {
    public static void main(String[] args) throws Exception {
        String out = args[0];
        String library = args[1];
        int rate = 44100;
        int channels = 2;
        int seconds = 3;
        int frames = rate * seconds;

        System.load(library);

        long handle = LameEncoder.nativeOpen(rate, channels, 192,
                "A Tone", "AutoSongs", "The Test", null);
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
            // The values are handed over as they are - the JNI layer
            // counts the frames, because that is what LAME wants.
            file.write(LameEncoder.nativeEncode(handle, pcm, n * channels));
            done += n;
        }
        file.write(LameEncoder.nativeFlush(handle));
        LameEncoder.nativeClose(handle);
        file.close();
        System.out.println("wrote " + out);
    }
}
"""

# MPEG-1 layer III bitrates, in kbit/s
BITRATES = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
RATES = [44100, 48000, 32000]


def mp3_length(path):
    """Reads an mp3 and says how many seconds of sound it holds."""
    with open(path, "rb") as handle:
        data = handle.read()

    start = 0
    if data[:3] == b"ID3":
        size = 0
        for byte in data[6:10]:
            size = (size << 7) | (byte & 0x7F)
        start = 10 + size

    frames = 0
    samples = 0
    rate = 44100
    i = start
    while i + 4 <= len(data):
        head = data[i:i + 4]
        if head[0] != 0xFF or (head[1] & 0xE0) != 0xE0:
            i += 1
            continue
        version = (head[1] >> 3) & 0x03
        layer = (head[1] >> 1) & 0x03
        bitrate_index = (head[2] >> 4) & 0x0F
        rate_index = (head[2] >> 2) & 0x03
        padding = (head[2] >> 1) & 0x01
        if version != 3 or layer != 1 or bitrate_index in (0, 15) or rate_index == 3:
            i += 1
            continue
        bitrate = BITRATES[bitrate_index] * 1000
        rate = RATES[rate_index]
        length = (144 * bitrate) // rate + padding
        samples += 1152
        frames += 1
        i += length
    return frames, samples / float(rate)


def build_library():
    """Builds the JNI library for the desktop. The phone's version is the
    same code, compiled for the phone."""
    os.makedirs(WORK, exist_ok=True)
    library = os.path.join(WORK, "libmp3lame.so")
    sources = [os.path.join(CPP, "lame_jni.cpp")]
    for name in sorted(os.listdir(os.path.join(LAME_SRC, "libmp3lame"))):
        if name.endswith(".c"):
            sources.append(os.path.join(LAME_SRC, "libmp3lame", name))

    newest = max(os.path.getmtime(s) for s in sources + [os.path.join(CPP, "config.h")])
    if os.path.exists(library) and os.path.getmtime(library) > newest:
        return library

    include = "-I%s/libmp3lame -I%s/include -I%s -I%s/include -I%s/include/linux" % (
        LAME_SRC, LAME_SRC, CPP, JAVA_HOME, JAVA_HOME)
    flags = "-O2 -fPIC -shared -fvisibility=hidden -DHAVE_CONFIG_H %s" % include
    objects = []
    work = tempfile.mkdtemp()
    try:
        for source in sources:
            obj = os.path.join(work, os.path.basename(source) + ".o")
            subprocess.check_call(["gcc", "-c"] + flags.split() + [source, "-o", obj])
            objects.append(obj)
        subprocess.check_call(["gcc", "-shared", "-o", library] + objects +
                              ["-lm", "-ldl"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return library


def main():
    if not os.path.isdir(LAME_SRC):
        print("no LAME source at %s - skipping" % LAME_SRC)
        return 0
    library = build_library()

    src = os.path.join(WORK, "src")
    os.makedirs(os.path.join(src, "com", "autosongs", "ytdl", "audio"), exist_ok=True)
    with io.open(os.path.join(src, "com", "autosongs", "ytdl", "audio",
                              "LameEncoder.java"), "w", encoding="utf-8") as handle:
        handle.write(JAVA_STANDIN)
    with io.open(os.path.join(src, "LameDurationTest.java"), "w",
                 encoding="utf-8") as handle:
        handle.write(JAVA_MAIN)

    classes = os.path.join(WORK, "classes")
    shutil.rmtree(classes, ignore_errors=True)
    os.makedirs(classes)
    subprocess.check_call(["javac", "-d", classes] +
                          [os.path.join(src, "com", "autosongs", "ytdl", "audio",
                                        "LameEncoder.java"),
                           os.path.join(src, "LameDurationTest.java")])

    mp3 = os.path.join(WORK, "tone.mp3")
    subprocess.check_call(["java", "-cp", classes, "LameDurationTest", mp3, library])

    frames, seconds = mp3_length(mp3)
    print("the mp3 holds %d frames, %.2f seconds" % (frames, seconds))
    if frames == 0:
        print("FAIL  the mp3 has no frames in it")
        return 1
    if abs(seconds - 3.0) > 0.15:
        print("FAIL  three seconds of sound came out as %.2f seconds" % seconds)
        return 1
    print("OK  three seconds of sound came out as %.2f seconds" % seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
