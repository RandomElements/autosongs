# Changelog

## 1.4.27 — Setup clear of the system bars, and the format you actually chose

**The setup no longer hides behind the phone's own controls.** From
Android 15 the app is drawn edge to edge, so the three-button navigation
bar sat over the walk-through's Back / Skip / Next row and the clock sat
over the title — a tap on "Next" went to the phone's back button instead.
The walk-through, the home screen and the settings screen now pad
themselves by the status bar, navigation bar and display-cutout insets
(and by the keyboard, since the folder name is typed in on the first
step).

**The permissions step opens with the app settings page.** On Android 13
and newer an app installed from a file rather than the Play Store has
notification access locked until "Allow restricted settings" is turned
on, and that switch lives only in the app's own settings page. Being sent
to the notification-access list first meant looking at a greyed-out
toggle with nothing to explain it. App settings, then notification
access, then the battery exemption.

**The format chosen in the first run is the format the home screen
shows.** The spinner was built before the walk-through covered it and was
never re-read, so MP3 (or Opus, or anything but M4A) came back as M4A once
the walk-through finished. The file was always right; the label was not.
The saved format is re-read on resume, and the setup's own radio list
ticks the saved choice instead of always ticking the first.

## 1.4.24 — A proper setup, and a bridge that works from anywhere

**The setup is a walk-through now.** The first run used to show a welcome
message and then a bare list of file types, and left the folder and the
permissions to be found later in Settings — the wrong order, because the
questions come first and the answers second. It now asks, in the order the
questions have to be answered: where the songs go and what folder they go
in, what kind of file to save, the two permissions Android needs, and then
a summary. Each answer is saved as it is given, and the permission step
reads what Android actually granted rather than what it remembers.

**The bridge can be reached from another network.** A new tunnel option
opens a Cloudflare tunnel, so a phone on cellular can reach a bridge on a
home computer. The bridge stays bound to the machine it is on and nothing
on the home network has to be opened up; no router has to be touched. The
bridge's own key is required on every request once it is reachable from
outside, the two pairing answers that are open on a local network are
closed, and a bridge with no key is refused rather than allowed.

**The source is MIT licensed**, and `THIRD-PARTY-NOTICES.md` says what is
bundled and under what terms. LAME is LGPL-2.0 and is a separate library,
so it can be replaced; the notices say how.

* **The first run is a walk-through.** It used to show a welcome
  message and a bare list of file types, and leave the folder and the
  permissions to be found later in Settings. It now asks, in the order
  the questions have to be answered: where the songs go and what folder
  they go in, what kind of file to save, the two permissions Android
  needs, and then a summary. Each answer is saved as it is given, and
  the permission step reads what Android actually granted rather than
  what it remembers.
* **The bridge can be reached from another network.** A new tunnel
  option opens a Cloudflare tunnel, so a phone on cellular can reach a
  bridge on a home computer. Nothing on the home network has to be
  opened up and no router has to be touched. The bridge's own key is
  required for every request once it is reachable from outside, and the
  two pairing answers that are open on a local network are closed.
* **The source is MIT licensed**, and `THIRD-PARTY-NOTICES.md` says
  what is bundled and under what terms. LAME is LGPL-2.0 and is a
  separate library, so it can be replaced; the notices say how.

## 1.4.23 — YouTube sign-in support

YouTube sometimes answers with **"Sign in to confirm you're not a bot"**
instead of the video. This release fixes that.

* **Pick a `cookies.txt` in Settings.** The app copies it into its own
  storage and hands it to the bridge by itself. When the bridge reports
  that YouTube asked for a sign-in, the app sends the jar and runs the
  whole download again — the refusal can land in the search as well as in
  the download.
* **The retry is bounded to one per track**, so a jar that does not get
  past the refusal cannot loop for ever.
* **The desktop bridge uses a `cookies.txt` next to it.** Put the file
  beside `autosongs-bridge.sh` or `autosongs-bridge.cmd` and it is used.
  The tray app has a button for choosing one.
* **The bridge finds a jar on its own** when it is not told: next to the
  bridge, in the work folder, in `~/.autosongs/`, in `~/autosongs/` or in
  `~/.config/yt-dlp/`.
* The bridge core is now **1.4.0**. It reports what it knows about
  cookies in `/health` and over `/cookies`, so the app can tell you where
  the jar came from instead of guessing.

## Earlier

* Media-session detection, with media notifications as a fallback.
* M4A 256k, Opus 160k, MP3 192k on-phone or 320k through an ffmpeg bridge,
  original audio, and 720p / 1080p / 4K video.
* Guard rails: minimum track length, minimum seconds played, an artist
  blocklist and a dedupe window.
* Title, artist and album tags plus embedded cover art, written through
  MediaStore so the files show up in every music app on the phone.
* The bridge runs inside the app by default — no Termux, no second
  machine, no pairing code.

---

If AutoSongs saves you time, you can support it on
[Ko-fi](https://ko-fi.com/autosongs). It is free to use and always will be.
