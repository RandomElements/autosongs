package com.autosongs.ytdl

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.LayoutInflater
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.data.FormatPreset
import com.autosongs.ytdl.download.WatcherService
import com.autosongs.ytdl.embedded.YtDlpUpdater
import kotlinx.coroutines.launch

/**
 * The first-run setup, as a walk-through.
 *
 * The old version showed a welcome dialog and then a bare "what should
 * AutoSongs save?" list, and left the folder and the permissions to be
 * found later in Settings. That is the wrong order: the questions come
 * first and the answers second, so the first thing a new user meets is a
 * setting they have to hunt for.
 *
 * This walks it through in the order it has to happen:
 *
 *  1. where the songs go - the folder, and whether they stay on the phone
 *  2. what kind of file to save
 *  3. the two permissions Android needs
 *  4. a summary, and the downloader update that keeps a fresh install
 *     from failing with a 403 on its very first track
 *
 * Every answer is written to the settings as it is given, so leaving
 * half-way through does not lose anything. The permission steps check
 * what Android actually granted, not what the user says they did, and
 * they can be skipped - somebody who wants to set this up later is better
 * served by an app that lets them than one that nags.
 */
class SetupActivity : AppCompatActivity() {

    private lateinit var settings: AppSettings
    private lateinit var content: FrameLayout
    private lateinit var titleLabel: TextView
    private lateinit var subtitleLabel: TextView
    private lateinit var counterLabel: TextView
    private lateinit var backButton: Button
    private lateinit var skipButton: Button
    private lateinit var nextButton: Button

    /** Which step is on screen. The order is the order of the questions. */
    private var step = Step.WHERE

    private enum class Step(val layout: Int, val title: Int) {
        WHERE(R.layout.setup_step_where, R.string.setup_where_title),
        FORMAT(R.layout.setup_step_format, R.string.setup_format_title),
        ACCESS(R.layout.setup_step_access, R.string.setup_access_title),
        DONE(R.layout.setup_step_done, R.string.setup_done_title)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)
        settings = AppSettings.get(this)

        content = findViewById(R.id.setupContent)
        titleLabel = findViewById(R.id.setupTitle)
        subtitleLabel = findViewById(R.id.setupSubtitle)
        counterLabel = findViewById(R.id.setupCounter)
        backButton = findViewById(R.id.setupBack)
        skipButton = findViewById(R.id.setupSkip)
        nextButton = findViewById(R.id.setupNext)

        backButton.setOnClickListener { goBack() }
        skipButton.setOnClickListener { skipToTheEnd() }
        nextButton.setOnClickListener { goForward() }

        show(Step.WHERE)
    }

    /**
     * Puts a step on screen.
     *
     * Each step is its own layout, inflated here, so that a step can be
     * as complicated as it needs to be without the whole walk-through
     * becoming one enormous activity.
     */
    private fun show(which: Step) {
        step = which
        content.removeAllViews()
        val view = LayoutInflater.from(this).inflate(which.layout, content, true)
        content.addView(view)

        titleLabel.setText(which.title)
        subtitleLabel.setText(subtitleFor(which))
        counterLabel.text = getString(R.string.setup_counter, which.ordinal + 1, Step.values().size)

        backButton.visibility = if (which == Step.WHERE) View.INVISIBLE else View.VISIBLE
        // The last step finishes the setup rather than moving on.
        nextButton.setText(
            if (which == Step.DONE) R.string.setup_start else R.string.setup_next
        )
        // Skipping only makes sense while there is something left to skip
        // to. On the last step the buttons are the finish.
        skipButton.visibility = if (which == Step.DONE) View.GONE else View.VISIBLE

        when (which) {
            Step.WHERE -> buildWhereStep()
            Step.FORMAT -> buildFormatStep()
            Step.ACCESS -> buildAccessStep()
            Step.DONE -> buildDoneStep()
        }
    }

    private fun subtitleFor(which: Step): Int = when (which) {
        Step.WHERE -> R.string.setup_where_subtitle
        Step.FORMAT -> R.string.setup_format_subtitle
        Step.ACCESS -> R.string.setup_access_subtitle
        Step.DONE -> R.string.setup_done_subtitle
    }

    // ---- the steps --------------------------------------------------------

    /**
     * Where the songs are kept.
     *
     * The folder is the one that matters and it is asked first, because
     * it is the answer people are least able to guess: the app writes
     * into the shared Music folder so every music player sees the files,
     * and the exact path is shown as it is typed.
     */
    private fun buildWhereStep() {
        val group = findViewById<RadioGroup>(R.id.saveLocationGroup)
        val toPhone = findViewById<RadioButton>(R.id.saveToPhoneRadio)
        val toBridge = findViewById<RadioButton>(R.id.saveToBridgeRadio)
        val folder = findViewById<EditText>(R.id.folderInput)
        val pathLabel = findViewById<TextView>(R.id.folderPathLabel)

        if (settings.saveLocation == AppSettings.SAVE_BRIDGE) {
            toBridge.isChecked = true
        } else {
            toPhone.isChecked = true
        }
        folder.setText(settings.folderName)

        fun showPath() {
            val name = folder.text.toString().trim().ifEmpty { "AutoSongs" }
            val dir = if (settings.preset.isVideo) "Movies" else "Music"
            pathLabel.text = getString(R.string.setup_folder_path, dir, name)
        }
        showPath()

        // A bridge inside the app cannot keep a library of its own - the
        // file comes back to the phone either way - so that answer is only
        // offered when the bridge is somewhere else.
        val remote = !settings.isEmbedded
        toBridge.isEnabled = remote
        findViewById<TextView>(R.id.saveToBridgeHint).visibility =
            if (remote) View.GONE else View.VISIBLE
        findViewById<TextView>(R.id.saveToBridgeHint).text = getString(
            R.string.setup_bridge_not_available
        )

        group.setOnCheckedChangeListener { _, which ->
            settings.saveLocation = if (which == R.id.saveToBridgeRadio) {
                AppSettings.SAVE_BRIDGE
            } else {
                AppSettings.SAVE_LOCAL
            }
        }
        folder.addTextChangedListener(SimpleTextWatcher { text ->
            settings.folderName = text.trim().ifEmpty { "AutoSongs" }
            showPath()
        })
    }

    /**
     * What kind of file to save.
     *
     * Each choice carries its own explanation, because "M4A 256 kbps" on
     * its own does not tell somebody whether that is the good choice for
     * them.
     */
    private fun buildFormatStep() {
        val group = findViewById<RadioGroup>(R.id.formatGroup)
        val description = findViewById<TextView>(R.id.formatDescription)

        group.removeAllViews()
        val presets = FormatPreset.values()
        presets.forEachIndexed { index, preset ->
            val button = RadioButton(this)
            button.id = View.generateViewId()
            button.text = preset.label
            button.textSize = 15f
            button.setPadding(0, 24, 0, 24)
            button.isChecked = preset == settings.preset
            button.setOnClickListener {
                settings.preset = preset
                description.text = preset.description
            }
            group.addView(button)
            if (index == 0) description.text = preset.description
        }

        group.setOnCheckedChangeListener { _, checkedId ->
            val button = group.findViewById<RadioButton>(checkedId) ?: return@setOnCheckedChangeListener
            val preset = presets.firstOrNull { it.label == button.text.toString() }
            if (preset != null) {
                settings.preset = preset
                description.text = preset.description
            }
        }
    }

    /**
     * The two permissions Android needs.
     *
     * Both are on one screen because they are one question - "may this
     * app watch and keep running" - and the user should not have to
     * remember what step two was about when they come back from the
     * first one.
     *
     * The status is read from Android rather than remembered, because the
     * user can revoke a permission outside the app and a stale "granted"
     * is worse than no answer at all.
     */
    private fun buildAccessStep() {
        findViewById<Button>(R.id.grantAccessButton).setOnClickListener {
            try {
                startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            } catch (_: Throwable) {
                Toast.makeText(this, R.string.setup_could_not_open, Toast.LENGTH_SHORT).show()
            }
        }
        findViewById<Button>(R.id.appInfoButton).setOnClickListener {
            openAppInfo()
        }
        refreshAccessStatus()
    }

    /**
     * The summary, and the one thing that has to happen before the first
     * track works.
     *
     * A fresh install carries whatever yt-dlp was current when the build
     * was made. YouTube breaks yt-dlp every few months, and the result of
     * an old one is a 403 that looks exactly like a network problem. So
     * the last step offers the update rather than leaving the user to
     * discover it as their first failure.
     */
    private fun buildDoneStep() {
        val summary = findViewById<TextView>(R.id.setupSummary)
        val where = if (settings.saveLocation == AppSettings.SAVE_BRIDGE) {
            getString(R.string.setup_summary_bridge)
        } else {
            val dir = if (settings.preset.isVideo) "Movies" else "Music"
            getString(R.string.setup_summary_phone, dir, settings.folderName)
        }
        summary.text = getString(
            R.string.setup_summary_body,
            where,
            settings.preset.label,
            settings.preset.description
        )

        findViewById<Button>(R.id.updateYtDlpButton).setOnClickListener {
            val button = it as Button
            button.isEnabled = false
            button.text = getString(R.string.setup_updating)
            lifecycleScope.launch {
                val newest = YtDlpUpdater.update(this@SetupActivity)
                button.isEnabled = true
                button.text = getString(R.string.setup_update_done)
                Toast.makeText(
                    this@SetupActivity,
                    if (newest != null) getString(R.string.setup_updated_to, newest)
                    else getString(R.string.setup_already_current),
                    Toast.LENGTH_LONG
                ).show()
            }
        }
    }

    // ---- moving between the steps ----------------------------------------

    private fun goForward() {
        val next = when (step) {
            Step.WHERE -> Step.FORMAT
            Step.FORMAT -> Step.ACCESS
            Step.ACCESS -> Step.DONE
            Step.DONE -> {
                finishSetup()
                return
            }
        }
        show(next)
    }

    private fun goBack() {
        val previous = when (step) {
            Step.WHERE -> return
            Step.FORMAT -> Step.WHERE
            Step.ACCESS -> Step.FORMAT
            Step.DONE -> Step.ACCESS
        }
        show(previous)
    }

    /**
     * Skips to the end.
     *
     * The answers given so far are already saved. Skipping the permission
     * step is allowed on purpose: somebody who would rather come back to
     * it later is better served by an app that lets them than by one that
     * insists.
     */
    private fun skipToTheEnd() {
        show(Step.DONE)
    }

    /**
     * Finishes.
     *
     * The watcher is started here rather than left to the home screen, so
     * that "Set up and start" means what it says.
     */
    private fun finishSetup() {
        settings.seenIntro = true
        requestNotificationPermissionIfNeeded()
        WatcherService.start(this)
        Toast.makeText(this, R.string.setup_finished, Toast.LENGTH_LONG).show()
        finish()
    }

    override fun onResume() {
        super.onResume()
        // The permission step is the only one whose answer can change
        // while the app is in the background, so it is the only one that
        // has to be re-read.
        if (step == Step.ACCESS) refreshAccessStatus()
    }

    /**
     * Reads what Android actually granted.
     *
     * The user can revoke a permission from the system settings without
     * ever opening the app, so this is asked of Android rather than
     * remembered.
     */
    private fun refreshAccessStatus() {
        val access = hasNotificationAccess()
        val mediaStatus = findViewById<TextView>(R.id.mediaAccessStatus)
        mediaStatus.text = if (access) {
            getString(R.string.setup_media_access_ok)
        } else {
            getString(R.string.setup_media_access_missing)
        }
        findViewById<Button>(R.id.grantAccessButton).visibility =
            if (access) View.GONE else View.VISIBLE

        val unrestricted = isUnrestricted()
        val batteryStatus = findViewById<TextView>(R.id.batteryStatus)
        batteryStatus.text = if (unrestricted) {
            getString(R.string.setup_battery_ok)
        } else {
            getString(R.string.setup_battery_missing)
        }
        findViewById<Button>(R.id.appInfoButton).visibility =
            if (unrestricted) View.GONE else View.VISIBLE
    }

    private fun hasNotificationAccess(): Boolean =
        runCatching {
            NotificationManagerCompat.getEnabledListenerPackages(this)
                .contains(packageName)
        }.getOrDefault(false)

    /**
     * Whether the app is exempt from battery optimisation.
     *
     * Aggressive battery managers are the most common reason the watcher
     * stops in the middle of a session, so this is worth asking about.
     */
    private fun isUnrestricted(): Boolean = runCatching {
        val power = getSystemService(PowerManager::class.java)
        power != null && power.isIgnoringBatteryOptimizations(packageName)
    }.getOrDefault(false)

    private fun openAppInfo() {
        try {
            startActivity(Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                android.net.Uri.fromParts("package", packageName, null)
            ))
        } catch (_: Exception) {
            Toast.makeText(this, R.string.setup_could_not_open, Toast.LENGTH_SHORT).show()
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    /** A text watcher that only wants the text. */
    private class SimpleTextWatcher(private val onChanged: (String) -> Unit) :
        android.text.TextWatcher {
        override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
        override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
        override fun afterTextChanged(s: android.text.Editable?) {
            onChanged(s?.toString() ?: "")
        }
    }
}
