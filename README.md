# AutoSongs — auto-download what plays on YouTube Music (ReVanced)

> **This is the public source release.** It is the working project with the
> private parts taken out: no signing key, no server keys, no address of the
> machine that hosts the releases. Every place where the app is told where to
> find its updates says **`autosongs.example`** — a placeholder domain
> reserved for exactly this. See
> [Publishing your own copy](#publishing-your-own-copy) before you build
> anything you want to ship.

AutoSongs listens to the media session of YouTube Music (or any app you allow),
notices each track as it plays, and downloads it through a local **yt-dlp**
bridge with the format you choose.

## Get the app

The app itself is built from this source and published by the project:

* **Website and downloads:** <https://autosongs.org>
  *(the real domain appears here on purpose - it is where the published
  app lives, and it is printed on the app's own About screen. The rest
  of this repository names a placeholder instead.)*
* **Releases:** the same builds are attached to this repository's Releases page
* **The bridge, on its own:** a single Python file (`bridge/ytbridge.py`) that
  runs on a PC, a NAS, a Termux phone or a spare Android device

## Support the project

AutoSongs is free, and it stays free — no account, no ads, no telemetry.
Making it costs time and money though: the hosting for the downloads and the
bridge, the release work, and the bug reports.

If it saves you time, you can support it on
**[Ko-fi](https://ko-fi.com/autosongs)**. It is entirely optional and buys
you nothing extra — the same app either way.

A bug report is worth just as much, if you have one.

```
YouTube Music (ReVanced)          Embedded / Termux / LAN box
        │ media session                  │
        ▼                                ▼
   AutoSongs app  ──HTTP──▶  ytbridge.py ──▶ yt-dlp ──▶ file
        │                                │
        └────── save into Music/AutoSongs ◀┘
```

## What you get

| Feature | Detail |
|---|---|
| Detection | Media sessions (title, artist, album, artwork, playback position) + media notifications as fallback |
| Formats | M4A 256k · Opus 160k · MP3 192k on-phone / 320k via ffmpeg bridge · original audio · 720p / 1080p / 4K video |
| Auto-download | Fires on every new track, as you listen |
| Guard rails | Min track length, min playback time, artist blocklist, dedupe window |
| Metadata | Title/artist/album tags and embedded cover art |
| Storage | Written into `Music/AutoSongs/` and indexed in MediaStore — visible in every music app |

## Install

### 1. The app

Grab `app-release.apk` from `app/build/outputs/apk/release/` (or `app-debug.apk`),
copy it to the phone and install it. You may need to allow "install from unknown
sources" for your file manager.

### 2. The yt-dlp bridge

AutoSongs includes its own `yt-dlp` bridge, enabled by default, so nothing
else has to be installed. Use an external bridge only when you want the
downloader to run somewhere else:

**Option A — the bridge inside the app (default)**

Leave **Bridge inside the app** enabled in Settings. The app runs Python and
`yt-dlp` itself; there is no Termux installation, host address, or pairing
code to set up.

**Option B — Termux on the same phone**

Install Termux, then:

```bash
pkg install python ffmpeg
pip install -U yt-dlp
```

Copy `bridge/ytbridge.py` into Termux (`~/autosongs/ytbridge.py`) and start it:

```bash
python ~/autosongs/ytbridge.py --port 8765
```

Or just run the helper script, which does all of it:

```bash
bash setup-termux.sh
```

**Option C — a PC / NAS / VPS on the same network**

```bash
python3 ytbridge.py --host 0.0.0.0 --port 8765 --token "your-secret"
```

Keep the bridge running (systemd, tmux, or `nohup`). Put it behind a firewall
or use `--token` if it is reachable from the internet.

**Option D — the one-file launcher**

The bridge also ships as a self-installing launcher, downloadable from the
AutoSongs page (or from `bridge/` in this repo):

* Linux / macOS / Termux: `autosongs-bridge.sh` — run with `sh autosongs-bridge.sh`
* Windows: `autosongs-bridge.cmd` — double-click it, or run it from a prompt

It checks for python 3, installs `yt-dlp` if needed, fetches the current
`ytbridge.py` into `~/.autosongs/` (`%USERPROFILE%\.autosongs\` on Windows),
starts the bridge and prints an eight-character code. Type that code into
AutoSongs (Settings → *The bridge on another machine*) and the two pair up.

### 3. Connect the app

Open AutoSongs:

1. Tap **Grant notification access** and enable AutoSongs in the system list.
2. Leave **Bridge inside the app** enabled in **Settings**. For an external
   bridge instead, turn that switch off and enter host `127.0.0.1` (Termux)
   or the LAN IP, port `8765`, and token if you set one.
3. Back on the main screen, pick a **Download format** and tap **Test bridge**.
   You should see `Bridge OK — yt-dlp <version>`.
4. Tap **Start watching**.

From now on every new song you play in YouTube Music is downloaded automatically
into `Music/AutoSongs/`.

## How matching works

YouTube Music's media session gives the *title* and *artist* of the track. The
bridge hands that pair to `yt-dlp` as a search query and picks the best match
(media sessions usually carry the exact video id, so the search resolves
cleanly).

You can tighten or loosen this:

* **Minimum track length** — skips ads and short clips.
* **Start downloading after N seconds of playback** — skips tracks you skip
  immediately.
* **Skip artists** — comma-separated artist names to ignore.
* **Skip re-downloading within N hours** — prevents re-downloading on loop.

## Notes

* Downloading is only as reliable as `yt-dlp` itself; when YouTube changes
  things, update `yt-dlp` (`pip install -U yt-dlp`).
* Keep the app off battery optimisation, and allow background activity, so the
  watcher is not killed while you listen.
* The bridge binds `0.0.0.0` by default so a LAN host works — restrict it with
  `--token` or a firewall if it is not on a trusted network.
* Use this only for content you are allowed to download (your own uploads,
  Creative Commons, public domain, or content you have rights to).

## Publishing your own copy

The release surface points at a placeholder domain. If you want to publish
your own build, these are the places that matter:

| What | Where |
|---|---|
| The address a release is published to | `tools/release-hosts.txt` |
| The app's list of update hosts | `app/src/main/java/com/autosongs/ytdl/bridge/BridgeVersion.kt` (`HOSTS`) |
| The bridge's own self-update address | `bridge/ytbridge.py` (`_UPDATE_URLS_DEFAULT`) |
| The desktop launchers' fetch address | `windows_Linux_Bridge/autosongs-bridge.sh`, `.cmd`, `gui/autosongs_bridge_app.py` (`HOSTS`) |
| The Termux installer | `bridge/install-termux.sh`, `bridge/setup-termux.sh` |
| The release feed the phone reads | `website/version.json` |
| The website's own links | `website/*.html` |

Search the tree for `autosongs.example` and replace it with your own domain.
After that, run the checks — they will tell you if an address was missed:

```bash
python tools/check-release-hosts.py
python tools/check-host-lists.py
python tools/check-no-retired-hosts.py
```

The domain must serve `version.json` (the release feed) and `ytbridge.py`
(the bridge core that remote bridges update themselves from), plus the
downloads the feed points at.

### The signing key is not here

The key that signs the app is deliberately absent. It is not a secret that
can be shared — anybody holding it could sign an "update" to the app and
have a phone install it. Make your own:

```bash
keytool -genkeypair -v -keystore keystore/autosongs-release.jks \
        -alias autosongs -keyalg RSA -keysize 2048 -validity 10000
cp keystore.properties.example keystore.properties
# fill in the passwords
```

Keep the `.jks` and its passwords private and backed up: without them you
cannot ship an update to an app that is already installed, because Android
only accepts an update signed by the key the app was signed with.

Without `keystore.properties` the release build falls back to the debug key.
That is fine for your own testing and wrong for anything you publish.

## Building from source

```bash
export ANDROID_HOME=/path/to/android-sdk
./gradlew :app:assembleDebug
./gradlew :app:assembleRelease
```

Requires JDK 17, Android SDK 35, and Python 3.11. If Chaquopy cannot find
Python 3.11 automatically (most often on Windows), set
`CHAQUOPY_BUILD_PYTHON` to the full path of that Python executable before
running Gradle.

Point the build at your SDK by copying `local.properties.example` to
`local.properties` and setting `sdk.dir` in it. That file is ignored by git
because it names a path on one machine.

## Layout

```
app/src/main/java/com/autosongs/ytdl/
  MainActivity.kt                  UI: status, format picker, bridge test
  SettingsActivity.kt              host/port/token, rules, storage
  data/AppSettings.kt              all preferences
  data/FormatPreset.kt             format choices
  data/DedupeStore.kt              "already downloaded" memory
  data/NowPlaying.kt               detected track model
  media/MediaSessionListenerService.kt   detection (sessions + notifications)
  media/TrackBus.kt                in-process event bus
  download/WatcherService.kt       foreground service: rules + saving
  bridge/BridgeClient.kt           HTTP client for the bridge
bridge/ytbridge.py                 the yt-dlp HTTP bridge
bridge/autosongs-bridge.sh         one-file launcher for Linux/macOS/Termux
bridge/autosongs-bridge.cmd        one-file launcher for Windows
bridge/setup-termux.sh             one-shot Termux setup
bridge/CookieStore                 (app side) the cookie jar the user picks
website/                           the static site: HTML, CSS, vanilla JS
tools/                             release and host checks
windows_Linux_Bridge/              the desktop bridge: tray app + launchers
```

## YouTube's sign-in demand

YouTube sometimes answers with "Sign in to confirm you're not a bot" instead
of the video. The cure is a cookie jar — the file a signed-in browser can
export — and the app can use one:

1. Export a `cookies.txt` from a signed-in browser.
2. Pick it in **Settings → YouTube sign-in (cookies)**. The app copies it
   into its own storage; it never keeps the picker's URI, which stops
   resolving when the app is killed.
3. The app hands it to the bridge over the same HTTP link the downloads use.
4. When the bridge reports that YouTube asked for a sign-in, the app sends
   the jar and runs the whole download again — once per track, so a jar that
   does not help cannot loop for ever.

The bridge also finds a jar on its own, without being told: next to the
bridge, in the work folder, in `~/.autosongs/`, in `~/autosongs/`, or in
`~/.config/yt-dlp/`. The desktop launchers use a `cookies.txt` sitting
beside them.

Use this only for content you are allowed to download, and only with an
account you own.
