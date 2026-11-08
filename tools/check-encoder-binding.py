#!/usr/bin/env python3
"""Checks that the mp3 encoder in the app is really wired up.

The system finds a native method by name:
`Java_<the class that declares it>_<the method>`. A companion object
changes that name - the methods would live in `LameEncoder$Companion` and
the library, which exports the plain name, would never be called.

This is not a guess: it happened. The app was published with the methods
in a companion object, so every phone quietly stopped making mp3s and the
app could only say "the encoder did not work".

So: find the class that declares the native methods in the built apk,
work out the name the system will look for, and check that the library
really exports it.
"""

import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
DEXDUMP = "/opt/android-sdk/build-tools/35.0.0/dexdump"

METHODS = ["nativeOpen", "nativeEncode", "nativeFlush", "nativeId3Tag", "nativeClose"]
ABIS = ["arm64-v8a", "armeabi-v7a", "x86_64"]


def dex_classes(apk):
    """Every class in the apk, with its method list."""
    with zipfile.ZipFile(apk) as z:
        blob = b"".join(z.read(n) for n in z.namelist() if n.endswith(".dex"))
    with open("/tmp/_encoder_binding.dex", "wb") as fh:
        fh.write(blob)
    out = subprocess.run([DEXDUMP, "-d", "/tmp/_encoder_binding.dex"],
                         capture_output=True).stdout.decode("utf-8", "replace")
    classes = {}
    for chunk in out.split("Class descriptor")[1:]:
        m = re.search(r":\s*'L([^;]+);'", chunk)
        if not m:
            continue
        classes[m.group(1)] = chunk
    return classes


def library_symbols(path):
    out = subprocess.run(["nm", "-D", "--defined-only", path],
                         capture_output=True, text=True).stdout
    return set(re.findall(r"\bJava_\S+", out))


def main():
    apk = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        APP, "app/build/outputs/apk/release/app-release.apk")
    if not os.path.exists(apk):
        print("no apk at %s" % apk)
        return 1

    classes = dex_classes(apk)
    owners = []
    for name, body in classes.items():
        for method in METHODS:
            if "name          : '%s'" % method in body:
                owners.append((name, method))
                break
    if not owners:
        print("FAIL  the apk has no native methods at all")
        return 1

    # every class that declares one of them must be a name the library
    # exports - and there must be only one such class
    declared_in = sorted(set(name for name, _ in owners))
    if len(declared_in) != 1:
        print("FAIL  the native methods are spread over %s" % declared_in)
        return 1
    owner = declared_in[0]
    mangled = owner.replace("/", "_")
    wanted = {"Java_%s_%s" % (mangled, m) for m in METHODS}

    for abi in ABIS:
        so = os.path.join(APP, "app/src/main/jniLibs", abi, "libmp3lame.so")
        if not os.path.exists(so):
            print("FAIL  no library for %s" % abi)
            return 1
        symbols = library_symbols(so)
        missing = wanted - symbols
        if missing:
            print("FAIL  %s does not export %s"
                  % (abi, ", ".join(sorted(missing))))
            print("      the app declares the native methods in %s" % owner)
            return 1
        print("OK  %s exports every name the app calls (%s)" % (abi, owner))

    print("the encoder is wired up correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
