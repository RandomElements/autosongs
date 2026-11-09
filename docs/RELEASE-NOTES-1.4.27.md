# AutoSongs 1.4.27

## The setup is clear of the phone's own bars

From Android 15 the system draws the app edge to edge, so the status bar
and the navigation bar are painted over the app rather than beside it.
That put the walk-through's Back / Skip / Next row underneath the
three-button navigation bar — the buttons were visible but a tap on
"Next" went to the phone's own back button — and the screen title
underneath the clock.

The walk-through, the home screen and the settings screen now pad
themselves by the height of the status bar, the navigation bar and the
display cutout, so nothing sits underneath the phone's own controls.

## The permissions step starts with the app settings page

On Android 13 and newer, an app installed from a file rather than from
the Play Store has notification access locked. The switch that unlocks it
— "Allow restricted settings" — lives only in the app's own settings
page, so being sent to the notification-access list first meant being
shown a greyed-out toggle with nothing to explain it.

The step now opens with the app settings page and says what to turn on
there, then notification access, then the battery exemption. The button
stays available even once the battery exemption is granted, because it is
also the way back to that switch.

## The format you pick is the format you get

The home screen is built before the first-run walk-through draws over it,
and the format spinner was never re-read afterwards. Choosing MP3, Opus
or anything other than M4A therefore came back to a home screen still
showing M4A: the file that would be downloaded was the one chosen, but
the app said otherwise, which is indistinguishable from the choice being
thrown away. The saved format is re-read on resume, and the setup's own
radio list ticks the saved choice instead of always ticking the first.

## Everything in 1.4.26 is still here

- The bridge explains what went wrong when a tunnel cannot be made.
- A phone can claim a pairing code on a plain network again.
- The first run is a walk-through, with every answer saved as it is
  given.
- The bridge can be reached from another network through a Cloudflare
  tunnel, and a bridge reachable from outside requires its key on every
  request.

## Install

- App: `AutoSongs-1.4.27.apk` (Android 8.0 or newer)
- Bridge app: `AutoSongsBridge-1.4.26.apk` (unchanged in this release)
- Desktop bridge: `AutoSongsBridgeSetup.exe`

Every download is at <https://autosongs.example>, and the sha256 of each
file is in <https://autosongs.example/version.json>.
