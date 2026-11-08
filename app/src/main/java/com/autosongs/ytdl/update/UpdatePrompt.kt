package com.autosongs.ytdl.update

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.appcompat.app.AlertDialog

/**
 * The parts of an update check that both screens need.
 */
object UpdatePrompt {

    /** The build number of the app that is running. */
    fun currentVersionCode(context: Context): Int = try {
        @Suppress("DEPRECATION")
        context.packageManager.getPackageInfo(context.packageName, 0).versionCode
    } catch (_: Throwable) {
        0
    }

    /** The name of the build that is running, e.g. "1.4.2". */
    fun currentVersionName(context: Context): String = try {
        @Suppress("DEPRECATION")
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: ""
    } catch (_: Throwable) {
        ""
    }

    /** The newest release the feed knows about, or null if nobody answered. */
    suspend fun newest(context: Context, customFeedUrl: String): Release? {
        val extra = if (customFeedUrl.isBlank()) emptyList() else listOf(customFeedUrl)
        return AppUpdate.fetchNewest(extra)
    }

    /**
     * Asks the user whether to download a newer build.
     *
     * The download is handed to the browser rather than done by the app.
     * Installing an APK from inside an app needs a permission that looks
     * alarming and a setting the user has to allow; letting the browser do
     * it keeps the app clean and works the way people expect.
     */
    fun ask(activity: Activity, release: Release) {
        val notes = release.notes.trim()
        val message = buildString {
            append("AutoSongs ${release.versionName} is out.\n\n")
            if (notes.isNotEmpty()) append(notes).append("\n\n")
            append("Download it?")
        }
        AlertDialog.Builder(activity)
            .setTitle("A newer AutoSongs")
            .setMessage(message)
            .setPositiveButton("Download") { _, _ -> open(activity, release.apkUrl) }
            .setNegativeButton("Later", null)
            .show()
    }

    private fun open(activity: Activity, url: String) {
        try {
            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (_: Exception) {
            Toast.makeText(activity, "Could not open the link", Toast.LENGTH_SHORT).show()
        }
    }
}
