# AutoSongs 1.4.25

## The bridge explains itself when a tunnel cannot be made

Cloudflare limits how many quick tunnels one network may make in a
short time. A person who starts the bridge a few times in a row runs
into that, and until now the only thing they were told was that the
tunnel stopped before it was ready - which says nothing about what to
do.

The bridge now reads what Cloudflare said and explains it: wait a
minute and start it again. It does the same for the two other things
that can stop a tunnel: cloudflared not being installed where the
bridge can find it, and cloudflared needing to be signed in.

## Everything in 1.4.24 is still here

- The first run is a walk-through: where the songs go, what kind of
  file to save, the permissions Android needs, and a summary.
- The bridge can be reached from another network through a Cloudflare
  tunnel, so a phone on cellular can reach a bridge on a home computer
  without opening anything on the home network.
- A bridge that is reachable from outside requires its key on every
  request, including the two pairing answers that are open on a local
  network.

## Install

- App: `AutoSongs-1.4.25.apk` (Android 8.0 or newer)
- Bridge app: `AutoSongsBridge-1.4.25.apk`
- Desktop bridge: `AutoSongsBridgeSetup.exe`

Every download is at <https://autosongs.example>, and the sha256 of each
file is in <https://autosongs.example/version.json>.
