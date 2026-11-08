#!/usr/bin/env python3
"""Checks that a shared library only wants symbols Android really has.

A library can be built perfectly on a desktop and still fail on every
phone: the desktop has libm folded into libc, Android keeps it in
libm.so of its own. Link without it and the library builds, installs and
then the phone refuses it with

    UnsatisfiedLinkError: dlopen failed: cannot locate symbol "cos"

which is exactly what happened to the mp3 encoder. The build must never
be able to produce that again, so after every build this looks at every
symbol the library leaves undefined and asks the Android libraries
whether they have it.

    check-android-symbols.py <library.so> <abi>
"""

import os
import re
import subprocess
import sys

NDK = os.environ.get("NDK", "/opt/android-sdk/ndk/27.2.12479018")
API = os.environ.get("API", "26")

TRIPLES = {
    # the compiler says armv7a-linux-androideabi, but the libraries live
    # in a directory the NDK calls arm-linux-androideabi
    "arm64-v8a": "aarch64-linux-android",
    "armeabi-v7a": "arm-linux-androideabi",
    "x86_64": "x86_64-linux-android",
}

# the libraries Android gives an app
SYSTEM_LIBS = ["libc.so", "libm.so", "libdl.so", "liblog.so"]


def toolchain():
    return os.path.join(NDK, "toolchains", "llvm", "prebuilt", "linux-x86_64")


def run(args):
    out = subprocess.run(args, capture_output=True, text=True)
    return out.stdout


def undefined_symbols(so_path):
    readelf = os.path.join(toolchain(), "bin", "llvm-readelf")
    text = run([readelf, "--dyn-syms", so_path])
    found = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[6] == "UND":
            name = parts[7].split("@")[0]
            if name:
                found.add(name)
    return found


def provided_symbols(abi):
    readelf = os.path.join(toolchain(), "bin", "llvm-readelf")
    triple = TRIPLES.get(abi)
    if not triple:
        sys.exit("unknown abi: %s" % abi)
    base = os.path.join(toolchain(), "sysroot", "usr", "lib", triple, API)
    names = set()
    for lib in SYSTEM_LIBS:
        path = os.path.join(base, lib)
        if not os.path.exists(path):
            continue
        text = run([readelf, "--dyn-syms", path])
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 8 and parts[6] != "UND":
                names.add(parts[7].split("@")[0])
    return names


def main():
    if len(sys.argv) != 3:
        print("usage: check-android-symbols.py <library.so> <abi>")
        return 2
    so_path, abi = sys.argv[1], sys.argv[2]

    wanted = undefined_symbols(so_path)
    have = provided_symbols(abi)
    missing = sorted(wanted - have)

    if missing:
        print("FAIL  %s wants symbols Android does not have:" % os.path.basename(so_path))
        for name in missing:
            print("        %s" % name)
        print("      link the library that has them (-lm for the maths ones)")
        return 1

    print("OK  %s: every symbol it wants (%d) is in Android's libraries"
          % (abi, len(wanted)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
