package com.autosongs.bridge

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import java.io.File

/**
 * Moves the finished songs into the phone's own music library.
 *
 * The bridge writes them into this app's own folder, because an app
 * cannot write straight into a public folder on modern Android. This
 * copies them across and takes the copy out of the way afterwards, so
 * the same song is never in the library twice.
 */
object LibraryImporter {

    private const val TAG = "LibraryImporter"
    private const val FOLDER = "Music/AutoSongs"

    /**
     * Moves anything new into the library.
     *
     * @return how many files were moved.
     */
    fun sweep(context: Context): Int {
        val folder = BridgeRunner.library(context)
        val files = folder.listFiles()?.filter { it.isFile && it.length() > 0 }
            ?: return 0
        var moved = 0
        for (file in files) {
            if (copy(context, file)) {
                // The copy in the library is the real one now.
                file.delete()
                moved++
            }
        }
        return moved
    }

    /** How many songs are waiting to be moved. */
    fun waiting(context: Context): Int =
        BridgeRunner.library(context).listFiles()?.count { it.isFile && it.length() > 0 } ?: 0

    private fun copy(context: Context, file: File): Boolean = try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            copyModern(context, file)
        } else {
            copyOlder(context, file)
        }
    } catch (t: Throwable) {
        Log.w(TAG, "the song could not be moved into the library", t)
        false
    }

    /** Android 10 and later: MediaStore, with the file left pending. */
    private fun copyModern(context: Context, file: File): Boolean {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, file.name)
            put(MediaStore.MediaColumns.MIME_TYPE, mimeOf(file.name))
            put(MediaStore.MediaColumns.RELATIVE_PATH, FOLDER)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val collection = MediaStore.Files.getContentUri("external")
        val uri = resolver.insert(collection, values) ?: return false
        resolver.openOutputStream(uri)?.use { out ->
            file.inputStream().use { it.copyTo(out) }
        }
        // Only now is the file finished. Until then, nothing else on the
        // phone can see a half-written song.
        values.clear()
        values.put(MediaStore.MediaColumns.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
        return true
    }

    /** Android 9 and earlier: straight into the public Music folder. */
    private fun copyOlder(context: Context, file: File): Boolean {
        @Suppress("DEPRECATION")
        val folder = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC),
            "AutoSongs"
        )
        if (!folder.exists() && !folder.mkdirs()) return false
        val target = File(folder, file.name)
        file.copyTo(target, overwrite = true)
        return target.exists() && target.length() == file.length()
    }

    private fun mimeOf(name: String): String = when {
        name.endsWith(".mp3", true) -> "audio/mpeg"
        name.endsWith(".m4a", true) -> "audio/mp4"
        name.endsWith(".aac", true) -> "audio/aac"
        name.endsWith(".opus", true) -> "audio/ogg"
        name.endsWith(".ogg", true) -> "audio/ogg"
        name.endsWith(".flac", true) -> "audio/flac"
        name.endsWith(".mp4", true) -> "video/mp4"
        name.endsWith(".webm", true) -> "video/webm"
        else -> "application/octet-stream"
    }
}
