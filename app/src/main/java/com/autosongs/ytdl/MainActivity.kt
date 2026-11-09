package com.autosongs.ytdl

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CompoundButton
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.autosongs.ytdl.bridge.BridgeClient
import java.io.File
import com.autosongs.ytdl.embedded.EmbeddedBridge
import com.autosongs.ytdl.embedded.YtDlpUpdater
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.data.FormatPreset
import com.autosongs.ytdl.data.watchedApps
import com.autosongs.ytdl.download.WatcherService
import com.autosongs.ytdl.media.MediaSessionProbe
import com.autosongs.ytdl.media.TrackBus
import com.autosongs.ytdl.update.AppUpdate
import com.autosongs.ytdl.update.Support
import com.autosongs.ytdl.update.UpdatePrompt
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private lateinit var settings: AppSettings

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        applyBarInsets(this, findViewById(R.id.mainRoot), dp(16))
        settings = AppSettings.get(this)

        bindPresets()
        bindToggles()
        bindButtons()
        showBuildInfo()
        showTheIntroOnce()
        startStatusTicker()
        startTheBridge()
        keepYtDlpCurrent()
        checkForUpdatesInBackground()
    }

    /**
     * Walks a new user through the setup, once.
     *
     * The questions come in the order they have to be answered - where
     * the songs go, what kind of file, then the two permissions - and
     * each answer is written down as it is given. Somebody who would
     * rather come back to this later can skip it and the home screen has
     * everything on it.
     *
     * The wizard is a whole activity rather than a chain of dialogs
     * because it has to survive the user going off to Android's own
     * settings screens and coming back.
     */
    private fun showTheIntroOnce() {
        if (settings.seenIntro) return
        startActivity(Intent(this, SetupActivity::class.java))
    }

    /**
     * Asks whether to bring the downloader up to date.
     *
     * YouTube breaks yt-dlp every few months, and an old one cannot
     * download anything at all - which looks like a network problem rather
     * than an old program, so nobody suspects the version.
     */
    private fun askToUpdateYtDlp() {
        AlertDialog.Builder(this)
            .setTitle(R.string.yt_dlp_update_title)
            .setMessage(R.string.yt_dlp_update_message)
            .setPositiveButton(R.string.yt_dlp_update_now) { _, _ -> updateYtDlpNow() }
            .setNegativeButton(R.string.yt_dlp_update_later, null)
            .show()
    }

    private fun updateYtDlpNow() {
        lifecycleScope.launch {
            val newest = YtDlpUpdater.update(this@MainActivity)
            Toast.makeText(this@MainActivity,
                if (newest != null) "yt-dlp is now $newest"
                else "yt-dlp is already up to date, or PyPI could not be reached",
                Toast.LENGTH_LONG).show()
        }
    }

    /**
     * Starts the bridge that lives inside the app.
     *
     * This is the whole point of the embedded bridge: there is nothing to
     * install and nothing to paste. When the user has chosen a bridge on
     * another machine instead, the app stays out of the way.
     */
    private fun startTheBridge() {
        if (!settings.isEmbedded) return
        if (EmbeddedBridge.start(this)) {
            Log.i("AutoSongs", "the bridge inside the app was started")
        } else {
            Log.e("AutoSongs", "the bridge inside the app could not be started")
        }
    }

    /**
     * Keeps yt-dlp up to date.
     *
     * YouTube breaks yt-dlp every few months and an old one cannot download
     * anything at all - it fails with "HTTP Error 403: Forbidden", which
     * looks like a network problem. So the app fetches the newest yt-dlp
     * itself and puts it in front of the one that came with the APK.
     */
    private fun keepYtDlpCurrent() {
        if (!settings.isEmbedded) return
        lifecycleScope.launch {
            val newest = YtDlpUpdater.update(this@MainActivity) ?: return@launch
            Toast.makeText(this@MainActivity, "yt-dlp is now $newest",
                Toast.LENGTH_SHORT).show()
        }
    }

    override fun onResume() {
        super.onResume()
        // The walk-through can change the format while this screen waits
        // behind it, so the spinner is re-read rather than trusted.
        showSavedPreset()
        refreshStatus()
        maybeAutoStart()
    }

    /**
     * Refreshes the detection panel twice a second. This makes it obvious
     * whether the app is actually seeing media sessions.
     */
    private fun startStatusTicker() {
        lifecycleScope.launch {
            while (true) {
                refreshDetection()
                delay(500)
            }
        }
    }

    private fun refreshDetection() {
        val detected = findViewById<TextView>(R.id.detectedLabel)
        val sessionLabel = findViewById<TextView>(R.id.sessionStateLabel)

        val watched = watchedApps(settings)

        val result = MediaSessionProbe.scan(this, watched)

        if (!result.accessible) {
            sessionLabel.text = if (hasNotificationAccess()) {
                "… Notification access is on but the listener is not connected.\n" +
                    "Switch AutoSongs off and on in the notification access list."
            } else {
                "✗ No media access — tap \"Grant notification access\" below"
            }
            detected.text = "Cannot read media sessions yet."
            return
        }

        sessionLabel.text = "✓ Media access working — ${result.sessions} active session(s)"

        val lastError = TrackBus.lastError
        val lastStatus = TrackBus.lastStatus
        if (lastError.isNotBlank()) {
            findViewById<TextView>(R.id.lastResultLabel).apply {
                visibility = View.VISIBLE
                text = "Last download failed:\n$lastError"
            }
        } else if (lastStatus.isNotBlank()) {
            findViewById<TextView>(R.id.lastResultLabel).apply {
                visibility = View.VISIBLE
                text = "Last download: $lastStatus"
            }
        }

        val best = result.best
        detected.text = if (best == null) {
            "No track seen yet.\n\nPlay something in YouTube Music; the title and artist\nwill appear here within a second."
        } else {
            "Now playing:\n${best.track.title}\n${best.track.artist}\n(app: ${best.track.packageName})"
        }
    }

    // ---- presets -----------------------------------------------------------

    private fun bindPresets() {
        val spinner = findViewById<Spinner>(R.id.presetSpinner)
        val presets = FormatPreset.values()

        spinner.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item, presets.map { it.label }
        )
        showSavedPreset()

        spinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(
                parent: AdapterView<*>?, view: View?, position: Int, id: Long
            ) {
                settings.preset = presets[position]
                findViewById<TextView>(R.id.presetDescription).text =
                    presets[position].description
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    /**
     * Points the format spinner at what is actually saved.
     *
     * The spinner is built once, in onCreate, and this screen is created
     * *before* the first-run walk-through draws over it. So somebody who
     * picks MP3 in the setup would come back to a spinner still showing
     * the M4A that was saved when the home screen was built - the file
     * they get would be MP3, but the app would say otherwise, which is
     * indistinguishable from the choice being thrown away. Re-reading it
     * on resume keeps the two in step.
     */
    private fun showSavedPreset() {
        val spinner = findViewById<Spinner>(R.id.presetSpinner)
        val presets = FormatPreset.values()
        val index = presets.indexOf(settings.preset).coerceAtLeast(0)

        if (spinner.selectedItemPosition != index) spinner.setSelection(index)
        findViewById<TextView>(R.id.presetDescription).text = presets[index].description
    }

    private fun bindToggles() {
        val auto = findViewById<CompoundButton>(R.id.autoDownloadSwitch)
        auto.isChecked = settings.autoDownload
        auto.setOnCheckedChangeListener { _, checked -> settings.autoDownload = checked }

        val embedMeta = findViewById<CompoundButton>(R.id.embedMetadataSwitch)
        embedMeta.isChecked = settings.embedMetadata
        embedMeta.setOnCheckedChangeListener { _, checked -> settings.embedMetadata = checked }

        val embedThumb = findViewById<CompoundButton>(R.id.embedThumbnailSwitch)
        embedThumb.isChecked = settings.embedThumbnail
        embedThumb.setOnCheckedChangeListener { _, checked -> settings.embedThumbnail = checked }
    }

    private fun bindButtons() {
        findViewById<Button>(R.id.startButton).setOnClickListener {
            requestNotificationPermissionIfNeeded()
            // Restart the watcher so it picks up the current preset & settings
            WatcherService.stop(this)
            WatcherService.start(this)
            refreshStatus()
        }

        findViewById<Button>(R.id.stopButton).setOnClickListener {
            WatcherService.stop(this)
            refreshStatus()
        }

        findViewById<Button>(R.id.grantAccessButton).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }

        findViewById<Button>(R.id.specialPermissionsButton)?.setOnClickListener {
            openAppInfo()
        }

        findViewById<Button>(R.id.settingsButton).setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        findViewById<Button>(R.id.supportButton)?.setOnClickListener {
            openUrl(Support.DONATE_URL)
        }

        // The bridge on another machine. The user runs it on their computer,
        // it shows eight characters, and this pairs with it - the phone
        // finds the bridge by itself.
        findViewById<Button>(R.id.pairRemoteButton)?.setOnClickListener {
            PairBridgeDialog.show(this)
        }
    }

    /**
     * Opens this app's own page in Android's settings.
     *
     * That page is where "Special permissions" lives. On most phones both
     * notification access and the battery setting hide in there, and a user
     * who cannot get notifications working has to go there before the
     * notification list does anything. So both buttons are on the screen,
     * one tap apart.
     */
    private fun openAppInfo() {
        try {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                android.net.Uri.fromParts("package", packageName, null)))
        } catch (_: Exception) {
            Toast.makeText(this, "Could not open the app settings", Toast.LENGTH_SHORT).show()
        }
    }

    /**
     * Starts the watcher automatically. Notification access is optional now:
     * the app reads media sessions directly, so it works either way.
     */
    private fun maybeAutoStart() {
        if (WatcherService.isRunning) return
        requestNotificationPermissionIfNeeded()
        WatcherService.start(this)
        refreshStatus()
    }

    // ---- status ------------------------------------------------------------

    private fun refreshStatus() {
        val access = hasNotificationAccess()
        findViewById<TextView>(R.id.notificationAccessLabel).text = if (access) {
            "✓ Notification access granted"
        } else {
            "✗ Notification access needed to detect playing songs"
        }
        findViewById<Button>(R.id.grantAccessButton).visibility =
            if (access) View.GONE else View.VISIBLE

        findViewById<TextView>(R.id.serviceStateLabel).text =
            if (WatcherService.isRunning) "● Watching for new tracks" else "○ Watcher stopped"
    }

    private fun hasNotificationAccess(): Boolean =
        runCatching {
            NotificationManagerCompat.getEnabledListenerPackages(this)
                .contains(packageName)
        }.getOrDefault(false)

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    /** Shows the installed build so support requests are unambiguous. */
    private fun showBuildInfo() {
        val info = try {
            packageManager.getPackageInfo(packageName, 0)
        } catch (t: Throwable) {
            null
        }
        val versionName = info?.versionName ?: "?"
        @Suppress("DEPRECATION")
        val versionCode = info?.versionCode ?: 0
        findViewById<TextView>(R.id.buildInfoLabel).text =
            getString(R.string.build_info, versionName, versionCode)
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    /**
     * Opens a web address in the browser.
     */
    private fun openUrl(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url)))
        } catch (_: Exception) {
            toast("Could not open the link")
        }
    }

    /**
     * Looks for a newer build, once a day.
     *
     * The dialog only appears when there is something to download, and the
     * check is remembered, so opening the app does not go online every
     * time. A release that is handed out directly has no store to do this
     * for us, so the app asks the release feed itself.
     */
    private fun checkForUpdatesInBackground() {
        val now = System.currentTimeMillis()
        if (now - settings.lastUpdateCheck < ONE_DAY_MS) return
        settings.lastUpdateCheck = now
        lifecycleScope.launch {
            val current = UpdatePrompt.currentVersionCode(this@MainActivity)
            val newest = UpdatePrompt.newest(this@MainActivity, settings.customFeedUrl)
                ?: return@launch
            if (AppUpdate.isNewer(newest, current)) {
                UpdatePrompt.ask(this@MainActivity, newest)
            }
        }
    }

    private companion object {
        const val ONE_DAY_MS = 24L * 60 * 60 * 1000
    }
}
