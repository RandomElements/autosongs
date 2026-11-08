#!/usr/bin/env bash
# Builds the MP3 encoder that ships inside the app.
#
# Android has no MP3 encoder of its own - MediaCodec can decode MP3 but
# cannot produce one - so the app carries LAME, a small LGPL library, and
# calls it through the JNI layer in lame_jni.cpp. This compiles both into one
# shared library per device type and drops it where gradle picks it up.
#
# The built libraries are committed, so building the app normally does not
# need the NDK. Run this again when the LAME version changes.
#
#   ./build-lame.sh /path/to/lame-3.100
#
# LAME 3.100 comes from
#   https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz
set -euo pipefail

NDK=${NDK:-/opt/android-sdk/ndk/27.2.12479018}
API=${API:-26}
HERE="$(cd "$(dirname "$0")" && pwd)"
LAME_SRC=${1:-/workspace/build/lame/lame-3.100}
OUT="$HERE/../jniLibs"

if [ ! -d "$NDK" ]; then
    echo "No NDK at $NDK. Install one with:"
    echo "  sdkmanager --sdk_root=/opt/android-sdk 'ndk;27.2.12479018'"
    exit 1
fi
if [ ! -d "$LAME_SRC/libmp3lame" ]; then
    echo "No LAME source at $LAME_SRC"
    echo "Unpack lame-3.100.tar.gz there and run this again."
    exit 1
fi

TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
STRIP="$TOOLCHAIN/bin/llvm-strip"

build_one() {
    abi=$1
    triple=$2
    cc="$TOOLCHAIN/bin/${triple}${API}-clang"
    if [ ! -x "$cc" ]; then
        echo "no compiler for $abi ($cc)"
        return 1
    fi
    dir="$OUT/$abi"
    mkdir -p "$dir"
    work="$(mktemp -d)"
    echo "==> $abi"

    # -fvisibility=hidden keeps LAME's own symbols to ourselves; only the
    # JNI entry points are exported.
    flags="-O2 -fPIC -shared -fvisibility=hidden -ffunction-sections -fdata-sections
           -DHAVE_CONFIG_H -I$LAME_SRC/libmp3lame -I$LAME_SRC/include -I$HERE"

    objects=()
    for f in "$LAME_SRC"/libmp3lame/*.c; do
        obj="$work/$(basename "${f%.c}").o"
        # shellcheck disable=SC2086
        "$cc" $flags -c "$f" -o "$obj"
        objects+=("$obj")
    done
    # shellcheck disable=SC2086
    "$cc" $flags -c "$HERE/lame_jni.cpp" -o "$work/lame_jni.o"
    objects+=("$work/lame_jni.o")

    # -lm is not optional: LAME uses cos, sin, pow, log and friends, and
    # on Android those live in libm.so, which is a library of its own.
    # Without it the phone fails at load time with
    # "cannot locate symbol \"cos\"" - the library looks fine on the
    # desktop and is broken on every phone.
    # shellcheck disable=SC2086
    "$cc" -shared -o "$dir/libmp3lame.so" "${objects[@]}" \
        -Wl,--gc-sections -Wl,-z,max-page-size=16384 -lm -ldl
    "$STRIP" "$dir/libmp3lame.so"
    rm -rf "$work"
    ls -l "$dir/libmp3lame.so"

    # every symbol the library wants must be in a library Android has
    "$HERE/check-android-symbols.py" "$dir/libmp3lame.so" "$abi"
}

build_one arm64-v8a aarch64-linux-android
build_one armeabi-v7a armv7a-linux-androideabi
build_one x86_64 x86_64-linux-android

echo
echo "==> what the app will carry"
du -ch "$OUT"/*/libmp3lame.so | tail -1
