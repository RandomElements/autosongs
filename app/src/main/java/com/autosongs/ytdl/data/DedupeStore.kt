package com.autosongs.ytdl.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Remembers which tracks were already downloaded so the watcher does not
 * re-download the same song on every loop.
 */
class DedupeStore(context: Context) {

    private val prefs = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** Returns true when [key] was NOT seen within [windowHours]. */
    fun shouldDownload(key: String, windowHours: Int): Boolean {
        val now = System.currentTimeMillis()
        val cutoff = now - windowHours * 3600_000L
        val entries = load().filterTo(mutableListOf()) { it.optLong("ts") >= cutoff }
        val seen = entries.any { it.optString("key") == key }
        if (!seen) {
            entries.add(JSONObject().put("key", key).put("ts", now))
        }
        save(entries)
        return !seen
    }

    private fun load(): MutableList<JSONObject> {
        val raw = prefs.getString(KEY, null) ?: return mutableListOf()
        return try {
            val arr = JSONArray(raw)
            (0 until arr.length()).map { arr.getJSONObject(it) }.toMutableList()
        } catch (t: Throwable) {
            mutableListOf()
        }
    }

    private fun save(entries: List<JSONObject>) {
        val arr = JSONArray()
        entries.forEach { arr.put(it) }
        prefs.edit().putString(KEY, arr.toString()).apply()
    }

    companion object {
        private const val FILE = "autosongs_dedupe"
        private const val KEY = "entries"
    }
}
