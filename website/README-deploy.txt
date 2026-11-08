AutoSongs website — autosongs.example
=================================

Contents
--------
  index.html            Landing page: hero, how it works, formats, feature
                        highlights, bridge platforms, FAQ, CTA.
  features.html         Feature tour: detection / formats / guard rails /
                        metadata / bridge / reliability.
  install.html          Full install guide: app sideload, bridge options
                        (Termux, Windows, Linux/macOS, spare-phone bridge app,
                        manual ytbridge.py), pairing, first run, troubleshooting.
  privacy.html          Plain-words privacy policy (data flow, permissions,
                        bridge caveats, third-party software).
  about.html            Project story, matching, under the hood, release table,
                        rights & responsibilities notice.
  404.html              Custom not-found page (absolute paths, noindex).
  assets/css/styles.css Single shared stylesheet. Dark navy theme built from
                        the brand logo (cyan -> violet -> magenta gradient).
                        No frameworks, no external fonts.
  assets/js/app.js      Vanilla JS: mobile menu (aria-expanded), copy buttons,
                        footer year, reveal-on-scroll. Progressive
                        enhancement only — every page works without it.
  assets/img/           Web-optimized brand assets generated from the 2048x2048
                        master logo at ../logo.jpg (kept OUTSIDE this folder on
                        purpose so the 1.7 MB source never gets deployed):
                          logo-hero.jpg (480, used on the landing page)
                          logo.png / logo-192.png / logo-96.png
                          favicon.ico (16/32/48), apple-touch-icon.png (180)
                          icon-192.png, icon-512.png, icon-maskable-512.png
                          og-image.png (1200x630 social card)
  site.webmanifest      PWA manifest (icons + theme colors).
  robots.txt            Allow all + sitemap pointer.
  sitemap.xml           The five indexable pages (404 excluded on purpose).
  version.json          Machine-readable release data: versionName 1.4.23,
                        versionCode 167, bridge core 1.3.24, canonical download
                        URLs, and measured release/core hashes and sizes.
  ytbridge.py           The bridge core fetched by the desktop launchers and
                        offered by the manual install option.
  downloads/            The five built release artifacts referenced by the
                        pages and version.json:
                          downloads/AutoSongs-1.4.23.apk
                          downloads/AutoSongsBridge-1.4.23.apk
                          downloads/AutoSongsBridgeSetup.exe
                          downloads/autosongs-bridge.sh
                          downloads/autosongs-bridge.cmd
  tests/app.test.js     Node test suite for assets/js/app.js (no framework):
                        run `node tests/app.test.js` from this folder. Not part
                        of the deployed site; exclude when copying if you want.

Deployment
----------
1. Copy this whole folder to the web root for https://autosongs.example (any static
   host: nginx, Caddy, GitHub Pages, Cloudflare Pages, S3). The five release
   artifacts are already in downloads/.
2. Serve the custom 404 page:
     nginx:   error_page 404 /404.html;
     Caddy:   handle_errors { rewrite * /404.html; file_server }
     GitHub Pages uses 404.html automatically.
3. No build step. Plain HTML/CSS/JS.

Updating the release version
----------------------------
Current release: 1.4.23 (versionCode 167). On a new release: find/replace
"1.4.23" across the HTML files, version.json and sitemap lastmod dates, rename
the download targets, and rebuild assets if the brand art changes.

Master artwork: ../logo.jpg (2048x2048). Web derivatives were
generated with Pillow; regenerate with an LANCZOS resize for any new size.
