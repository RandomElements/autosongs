package com.autosongs.ytdl

import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat

/**
 * Keeps a screen clear of the phone's own status and navigation bars.
 *
 * From Android 15 the app is drawn edge to edge whether it asks to be or
 * not: the clock and the three navigation buttons are painted on top of
 * the app instead of beside it. Without this, the title sits under the
 * clock and "Next" sits under the back button, and the phone's button
 * gets the tap.
 *
 * The inset is the height of the bars themselves, so padding the root by
 * it moves the app's content back where it was before edge-to-edge.
 * The keyboard is counted too, since it covers the same part of the
 * screen while it is open.
 *
 * @param rootPaddingPx padding the layout already wants on all four
 *   sides - 16dp on the scrolling screens - so that setting the insets
 *   here does not throw it away.
 */
fun applyBarInsets(activity: AppCompatActivity, root: View, rootPaddingPx: Int = 0) {
    WindowCompat.setDecorFitsSystemWindows(activity.window, false)
    ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
        val bars = insets.getInsets(
            WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
        )
        val keyboard = insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
        view.setPadding(
            rootPaddingPx + bars.left,
            rootPaddingPx + bars.top,
            rootPaddingPx + bars.right,
            rootPaddingPx + maxOf(bars.bottom, keyboard)
        )
        insets
    }
}

/** The same padding converted from dp, for callers that think in dp. */
fun AppCompatActivity.dp(value: Int): Int =
    (value * resources.displayMetrics.density + 0.5f).toInt()
