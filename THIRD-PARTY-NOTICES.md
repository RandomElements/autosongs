# Third-party software

AutoSongs is MIT licensed (see `LICENSE`). The pieces below are not part of
AutoSongs and carry their own licences.

## LAME — the MP3 encoder

| | |
|---|---|
| Component | `libmp3lame.so`, built from LAME 3.100 |
| Version | 3.100 |
| Licence | GNU Lesser General Public License v2.0 (LGPL-2.0) |
| Licence text | [`app/src/main/assets/LICENSES/LAME-LGPL-2.0.txt`](app/src/main/assets/LICENSES/LAME-LGPL-2.0.txt) — also inside the app, under Settings → Open source licences |
| Source | <https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz> |
| Build script | [`app/src/main/cpp/build-lame.sh`](app/src/main/cpp/build-lame.sh) |
| The exact commit and patch set | none — the tree is used as published, unmodified |

### Why it is here

Android has no MP3 encoder of its own. `MediaCodec` can decode MP3 but
cannot produce one, so the app carries LAME and calls it through the JNI
layer in `app/src/main/cpp/lame_jni.cpp`.

### How the LGPL obligations are met

The obligations come from section 6 of the LGPL-2.0, which is what
applies to a work that links an LGPL library. Its words, from the copy of
the licence that ships inside the app
(`app/src/main/assets/LICENSES/LAME-LGPL-2.0.txt`):

> you may also compile or link a "work that uses the Library" with the
> Library to produce a work containing portions of the Library, and
> distribute that work under terms of your choice, **provided that the
> terms permit modification of the work for the customer's own use and
> reverse engineering for debugging such modifications.**
>
> You must give prominent notice with each copy of the work that the
> Library is used in it and that the Library and its use are covered by
> this License. You must supply a copy of this License.

Here is how each part is satisfied.

**The work is distributed under terms of your choice.** AutoSongs is MIT
licensed. MIT permits modification for your own use and says nothing that
restricts reverse engineering, and this project adds no such restriction.

**Prominent notice that the Library is used and is covered by the
licence.** The app's Settings screen has an **Open source licences**
button, and the text it opens names LAME, its version, its licence, and
says that the library and its use in the app are covered by that licence.
The full licence text is inside the app at
`assets/LICENSES/LAME-LGPL-2.0.txt`.

**A copy of the licence is supplied.** The same file, inside the app, and
at the path above in this repository.

**The source of the Library is obtainable.** The version is LAME 3.100.
The source tarball is at the SourceForge address above, and the script
that compiles it for Android is in this repository at
`app/src/main/cpp/build-lame.sh`. Running that script with the source
unpacked produces the `libmp3lame.so` that ships in the APK.

**The Library can be replaced, and the work relinked.** LAME is a separate
shared library, not compiled into the app's own code. The APK's
`lib/<abi>/libmp3lame.so` can be replaced with a build of your own —
including one with different settings, or a different MP3 encoder
entirely — by unpacking the APK, substituting the file, and re-signing it.
Nothing in AutoSongs's own code has to change, because the only interface
between them is the small JNI shim in `lame_jni.cpp`.

### The source of the "work that uses the Library"

Section 6 also asks, for an executable linked with the Library, for the
complete machine-readable "work that uses the Library" — the app itself —
so that the Library can be modified and relinked.

**This repository is that source.** The whole of AutoSongs is here under
the MIT licence: the Android app in `app/`, the bridge in `bridge/`, the
bridge app in `bridgeapp/`, the desktop launchers in
`windows_Linux_Bridge/`, and the website in `website/`. Building it is
described in the README.

The one thing a person needs that is not in the repository is the
signing key, because a key that ships can sign an "update" to the app
that a phone would install. A person who wants to sign their own build
makes their own key — `keystore.properties.example` says how — and the
build falls back to the debug key until they do.

### A note on the version

LAME 3.100's `libmp3lame` is LGPL-2.0. Some later LAME releases are
dual-licensed LGPL-2.0 / GPL-2.0. This app uses the LGPL terms, so the
combined work stays under terms that permit this.

## yt-dlp — the downloader

| | |
|---|---|
| Component | `yt-dlp`, run by the bridge |
| Licence | The Unlicense (public domain) |
| Source | <https://github.com/yt-dlp/yt-dlp> |

The Unlicense places the work in the public domain. It imposes no
obligation on AutoSongs and no obligation on you. The version used is
whatever `pip install yt-dlp` fetched at the time — the app updates it
itself, so the version in a given install varies.

`yt-dlp` may pull in `yt-dlp-ejs`, which bundles MIT- and ISC-licensed
components. Both are permissive licences that require only that the
copyright notice travels with the code; the upstream projects keep those
notices in their own source trees, and that is where they are read from.

## ffmpeg — optional, not bundled

The bridge will use `ffmpeg` for 320 kbps MP3 and for joining video and
audio. It is **not** bundled with AutoSongs and it is **not** installed by
it. If your copy of ffmpeg is built with the GPL, the GPL applies to that
copy of ffmpeg — which is a matter between you and the build you chose,
and does not affect AutoSongs or LAME.

## What is not third-party

The Python bridge in `bridge/ytbridge.py`, the Android app, the desktop
launchers, the tray app and the website are all part of AutoSongs and are
covered by the MIT licence in `LICENSE`.
