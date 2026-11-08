# AutoSongs 1.4.23 — YouTube sign-in support

**The problem:** YouTube sometimes answers with *"Sign in to confirm you're not a bot"* instead of the video. Every download fails, and the usual advice — update yt-dlp — does not help, because the refusal is not about being out of date. It is YouTube asking for proof that you are a real signed-in listener.

**The fix:** give the app your cookies.

Pick a `cookies.txt` in **Settings → YouTube sign-in (cookies)**. The app copies it into its own storage and hands it to the bridge by itself. When the bridge reports that YouTube asked for a sign-in, the app sends the jar and runs the whole download again — once per track, so a jar that does not get past the refusal cannot loop for ever.

The refusal can land in the *search* as well as in the download, which is why the retry re-runs the entire job rather than just the fetch.

---

## Downloads

| File | What it is | SHA-256 |
|---|---|---|
| `AutoSongs-1.4.23.apk` | The app. Android 8.0+. The bridge is built in — nothing else to install. | `c12fc192c7d51328fb2ffd0c6ea5e6ef163be588f5d76d3b38f61f9820abd19c` |
| `AutoSongsBridge-1.4.23.apk` | The bridge as a standalone app, for a spare phone or tablet. | `5affa10c0f35f46de5b6dc8b787b515bef29e15890426dee8aa40299a90ef679` |
| `AutoSongsBridgeSetup.exe` | Windows installer for the desktop bridge. | `1b5a2534df4573f4091a7c00e1f1d2556c80c0b999331a5a76380f52af730908` |
| `autosongs-bridge.sh` | Linux / macOS / Termux launcher. One file, no install. | — |
| `autosongs-bridge.cmd` | Windows launcher. One file, no install. | — |

`SHA256SUMS.txt` is attached with all five hashes. The two APKs and the setup are signed with the same release key as every build since 1.4.17, so **you can update in place** — install over the top and your settings carry over.

The bridge core (`ytbridge.py`) is now **1.4.0**. It reports what it knows about cookies over `/health` and `/cookies`, so the app can tell you where the jar came from instead of guessing.

## Where the cookie jar is looked for

In order, so you do not have to configure anything:

1. The path you picked in Settings
2. `YTBRIDGE_COOKIES`
3. Next to the bridge
4. The bridge's work folder
5. `~/.autosongs/`
6. `~/autosongs/`
7. `~/.config/yt-dlp/`

For the desktop bridge, a `cookies.txt` sitting next to `autosongs-bridge.sh` or `autosongs-bridge.cmd` is used automatically. The tray app has a button for choosing one.

## Install

The app is a direct APK, not a store listing — Android will ask you to allow installs from your file manager or browser once.

1. Download `AutoSongs-1.4.23.apk` to the phone and open it.
2. Tap **Grant notification access** and enable AutoSongs in the system list. This is how the app sees the track that is playing.
3. Leave **Bridge inside the app** enabled in Settings.
4. Pick a download format, tap **Test bridge** — you should see `Bridge OK — yt-dlp <version>`.
5. Tap **Start watching**.

**One battery setting matters:** exclude AutoSongs from battery optimisation and allow background activity, or Android may kill the watcher mid-session.

Full guide: https://autosongs.example/install.html

## What AutoSongs does

It watches Android's media sessions, notices each track as it plays in YouTube Music (ReVanced) or any app you allow, and downloads it through a local yt-dlp bridge into `Music/AutoSongs/` — tagged with title, artist, album and cover art, indexed through MediaStore so every music app on the phone sees it. No account, no cloud, no server in between.

Formats: M4A 256k, Opus 160k, MP3 192k on-phone (320k through an ffmpeg bridge), original audio untouched, or 720p / 1080p / 4K video.

## Support

AutoSongs is free and always will be — no account, no ads, no telemetry. Making it costs time and money though: the hosting for the downloads and the bridge, the release work, and the bug reports.

If it saves you time: **https://ko-fi.com/autosongs**

A bug report is worth just as much, if you have one: https://github.com/<your-account>/AutoSongs/issues

---

*Use it only for content you are allowed to download — your own uploads, Creative Commons or public-domain material, or anything else your local law and licences permit. Not affiliated with YouTube or Google LLC.*
