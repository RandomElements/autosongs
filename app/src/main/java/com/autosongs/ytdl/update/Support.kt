package com.autosongs.ytdl.update

/**
 * The addresses the app offers the user.
 *
 * Two things make a release that is handed out directly feel like a store:
 * a way to say "thank you", and a way to find out that there is a newer
 * build. Both are here.
 */
object Support {

    /**
     * Where the "Support AutoSongs" button goes.
     *
     * This is the one line to change when the donation page is set up. A
     * Ko-fi page keeps its address forever, so the link in the app keeps
     * working for as long as the app exists.
     */
    const val DONATE_URL = "https://ko-fi.com/autosongs"

    /**
     * The page with the downloads, the notes and the donation links.
     *
     * This is the user's own server, and it keeps this address forever,
     * so the page in an installed app is still the page that has the
     * newest release on it.
     */
    const val PROJECT_URL = "https://autosongs.example"
}
