package com.autosongs.ytdl

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import androidx.activity.result.contract.ActivityResultContracts
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.autosongs.ytdl.bridge.BridgeClient
import com.autosongs.ytdl.bridge.CookieStore
import com.autosongs.ytdl.bridge.PairingCode
import com.autosongs.ytdl.data.AppSettings
import com.autosongs.ytdl.data.MusicApps
import com.autosongs.ytdl.update.AppUpdate
import com.autosongs.ytdl.update.Support
import com.autosongs.ytdl.update.UpdatePrompt
import com.google.android.material.materialswitch.MaterialSwitch
import kotlinx.coroutines.launch

class SettingsActivity : AppCompatActivity() {

    private lateinit var settings: AppSettings
    private lateinit var packagesInput: EditText
    private lateinit var packagesBox: LinearLayout
    private lateinit var packagesHint: TextView
    private lateinit var host: EditText
    private lateinit var port: EditText
    private lateinit var token: EditText
    private lateinit var embeddedSwitch: MaterialSwitch
    private lateinit var pairingCode: EditText
    private lateinit var watchAllSwitch: MaterialSwitch
    private lateinit var feedUrl: EditText
    private lateinit var updateLabel: TextView
    private lateinit var cookiesStatus: TextView

    /**
     * Picks the cookie jar.
     *
     * The types are wide because a cookie jar usually has no extension at
     * all, and the picker would then refuse to show it.
     */
    private val chooseCookies = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri == null) return@registerForActivityResult
        lifecycleScope.launch {
            val file = CookieStore.importJar(this@SettingsActivity, uri)
            if (file == null) {
                Toast.makeText(this@SettingsActivity, R.string.cookies_not_a_jar,
                    Toast.LENGTH_LONG).show()
                showCookieState()
                return@launch
            }
            Toast.makeText(this@SettingsActivity, R.string.cookies_imported,
                Toast.LENGTH_SHORT).show()
            // The bridge has to be told as well, so a download that is
            // waiting for a jar does not have to wait for the next one.
            pushJarToBridge()
            showCookieState()
        }
    }

    /**
     * The address is only used when the bridge is somewhere else. When the
     * bridge is inside the app the fields are greyed out - there is nothing
     * to type.
     */
    private fun applyMode() {
        val on = embeddedSwitch.isChecked
        host.isEnabled = !on
        port.isEnabled = !on
        token.isEnabled = !on
        // A bridge inside the app has no library folder of its own that
        // the user would ever find, so there is nothing to choose.
        findViewById<RadioButton>(R.id.saveToBridgeRadio)?.isEnabled = !on
        findViewById<RadioButton>(R.id.saveToPhoneRadio)?.isEnabled = !on
        host.setText(if (on) "" else settings.bridgeHost)
        port.setText(if (on) "" else settings.bridgePort.toString())
        token.setText(if (on) "" else settings.bridgeToken)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)
        applyBarInsets(this, findViewById(R.id.settingsRoot), dp(16))
        settings = AppSettings.get(this)

        host = findViewById<EditText>(R.id.hostInput)
        port = findViewById<EditText>(R.id.portInput)
        token = findViewById<EditText>(R.id.tokenInput)
        embeddedSwitch = findViewById<MaterialSwitch>(R.id.embedded)
        pairingCode = findViewById<EditText>(R.id.pairingCodeInput)
        watchAllSwitch = findViewById<MaterialSwitch>(R.id.watchAllSwitch)
        val folder = findViewById<EditText>(R.id.folderInput)
        val blocklist = findViewById<EditText>(R.id.blocklistInput)
        val minDuration = findViewById<SeekBar>(R.id.minDurationSeek)
        val minDurationLabel = findViewById<TextView>(R.id.minDurationLabel)
        val dedupe = findViewById<SeekBar>(R.id.dedupeSeek)
        val dedupeLabel = findViewById<TextView>(R.id.dedupeLabel)
        val minPlay = findViewById<SeekBar>(R.id.minPlaybackSeek)
        val minPlayLabel = findViewById<TextView>(R.id.minPlaybackLabel)
        val deleteAfter = findViewById<MaterialSwitch>(R.id.deleteAfterSwitch)
        packagesInput = findViewById(R.id.packagesInput)
        packagesBox = findViewById(R.id.packagesBox)
        packagesHint = findViewById(R.id.packagesHint)
        feedUrl = findViewById<EditText>(R.id.feedUrlInput)
        updateLabel = findViewById<TextView>(R.id.updateLabel)
        feedUrl.setText(settings.customFeedUrl)

        embeddedSwitch.isChecked = settings.isEmbedded
        applyMode()
        embeddedSwitch.setOnCheckedChangeListener { _, _ -> applyMode() }

        // The bridge shows a code. The user pastes it here and the two are
        // paired: the address and the key both come out of the code, so
        // there is nothing to get wrong.
        findViewById<Button>(R.id.pairButton).setOnClickListener {
            val code = pairingCode.text.toString().trim()
            if (code.isEmpty()) {
                Toast.makeText(this, R.string.pairing_nothing,
                    Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            try {
                val pairing = PairingCode.parse(code)
                settings.bridgeHost = pairing.host
                settings.bridgePort = pairing.port
                settings.bridgeToken = pairing.token
                // A bridge reached over a tunnel is https, and may sit
                // under a path. Both come out of the code.
                settings.bridgeScheme = pairing.scheme
                settings.bridgePath = pairing.path
                settings.bridgeMode = AppSettings.BRIDGE_REMOTE
                host.setText(pairing.host)
                port.setText(pairing.port.toString())
                token.setText(pairing.token)
                embeddedSwitch.isChecked = false
                applyMode()
                Toast.makeText(this,
                    getString(R.string.paired_with, pairing.host),
                    Toast.LENGTH_LONG).show()
            } catch (e: IllegalArgumentException) {
                Toast.makeText(this, e.message ?: getString(R.string.pairing_nothing),
                    Toast.LENGTH_LONG).show()
            }
        }

        folder.setText(settings.folderName)
        blocklist.setText(settings.artistBlocklist)
        packagesInput.setText(settings.watchedPackages)
        packagesInput.isEnabled = !settings.watchAllApps
        watchAllSwitch.isChecked = settings.watchAllApps
        watchAllSwitch.setOnCheckedChangeListener { _, _ ->
            packagesInput.isEnabled = !watchAllSwitch.isChecked
            buildPackagePicker(watchAllSwitch.isChecked)
        }
        minDuration.progress = settings.minDurationSec.coerceIn(0, 600)
        dedupe.progress = settings.dedupeHours.coerceIn(0, 168)
        minPlay.progress = (settings.minPlaybackMs / 1000L).toInt().coerceIn(0, 300)
        deleteAfter.isChecked = settings.deleteAfterTransfer

        fun syncLabels() {
            minDurationLabel.text = "Minimum track length: ${minDuration.progress}s"
            dedupeLabel.text = "Skip re-downloading within: ${dedupe.progress}h"
            minPlayLabel.text = "Start downloading after: ${minPlay.progress}s of playback"
        }
        syncLabels()

        minDuration.setOnSeekBarChangeListener(object : SimpleSeekListener() {
            override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                settings.minDurationSec = p
                syncLabels()
            }
        })
        dedupe.setOnSeekBarChangeListener(object : SimpleSeekListener() {
            override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                settings.dedupeHours = p
                syncLabels()
            }
        })
        minPlay.setOnSeekBarChangeListener(object : SimpleSeekListener() {
            override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                settings.minPlaybackMs = p * 1000L
                syncLabels()
            }
        })

        findViewById<Button>(R.id.detectAppsButton).setOnClickListener {
            buildPackagePicker(watchAllSwitch.isChecked)
        }

        findViewById<Button>(R.id.supportButton).setOnClickListener {
            openUrl(Support.DONATE_URL)
        }

        // The tools that used to be on the home screen. They are here now
        // because they are things a person goes looking for, not things
        // they do every day.
        val bridgeStatus = findViewById<TextView>(R.id.bridgeStatus)
        val testBridgeButton = findViewById<Button>(R.id.testBridgeButton)
        val updateBridgeButton = findViewById<Button>(R.id.updateBridgeButton)
        val termuxButton = findViewById<Button>(R.id.termuxButton)

        testBridgeButton.setOnClickListener {
            BridgeTools.test(this, settings, bridgeStatus)
        }
        updateBridgeButton.setOnClickListener {
            BridgeTools.update(this, settings, bridgeStatus)
        }
        // The bridge inside the app cannot be replaced - it is part of the
        // app. What can be updated is yt-dlp.
        updateBridgeButton.text = if (settings.isEmbedded) getString(R.string.update_yt_dlp)
            else getString(R.string.update_bridge)
        termuxButton.setOnClickListener {
            BridgeTools.openTermuxSettings(this)
        }
        BridgeTools.updateTermuxButton(this, settings, termuxButton)
        BridgeTools.check(this, settings, bridgeStatus)

        // The same pairing the home screen offers, for the person who has
        // already gone past the home screen to look for it.
        findViewById<Button>(R.id.pairRemoteSettingsButton)?.setOnClickListener {
            PairBridgeDialog.show(this)
        }

        cookiesStatus = findViewById<TextView>(R.id.cookiesStatus)
        findViewById<Button>(R.id.chooseCookiesButton).setOnClickListener {
            chooseCookies.launch(arrayOf(
                "text/plain", "application/octet-stream", "text/*", "*/*"
            ))
        }
        findViewById<Button>(R.id.removeCookiesButton).setOnClickListener {
            lifecycleScope.launch {
                CookieStore.forget(this@SettingsActivity)
                // The bridge may keep a copy of the jar, so it is told to
                // let go of it too.
                runCatching { bridgeClient(settings).clearCookies() }
                Toast.makeText(this@SettingsActivity, R.string.cookies_removed,
                    Toast.LENGTH_SHORT).show()
                showCookieState()
            }
        }
        showCookieState()

        findViewById<Button>(R.id.testEncoderButton).setOnClickListener {
            // A phone that cannot make mp3s should say so before a track
            // is saved as something else.
            val result = com.autosongs.ytdl.audio.Mp3Converter.testEncoder()
            androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle(R.string.test_encoder_button)
                .setMessage(result)
                .setPositiveButton("Close", null)
                .show()
        }

        findViewById<Button>(R.id.licensesButton).setOnClickListener {
            androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle(R.string.licenses_title)
                .setMessage(R.string.licenses_body)
                .setPositiveButton("Close", null)
                .show()
        }

        findViewById<Button>(R.id.checkUpdateButton).setOnClickListener {
            updateLabel.text = "Looking for a newer build…"
            lifecycleScope.launch {
                val current = UpdatePrompt.currentVersionCode(this@SettingsActivity)
                val newest = UpdatePrompt.newest(this@SettingsActivity, settings.customFeedUrl)
                updateLabel.text = when {
                    newest == null ->
                        "Could not reach the release feed. Is this phone online?"
                    AppUpdate.isNewer(newest, current) ->
                        "AutoSongs ${newest.versionName} is available. " +
                            "Open the app's home screen to download it."
                    else -> "You are on the newest build " +
                        "(${UpdatePrompt.currentVersionName(this@SettingsActivity)})."
                }
            }
        }

        findViewById<Button>(R.id.saveButton).setOnClickListener {
            settings.bridgeMode = if (embeddedSwitch.isChecked) {
                AppSettings.BRIDGE_EMBEDDED
            } else {
                AppSettings.BRIDGE_REMOTE
            }
            if (!embeddedSwitch.isChecked) {
                settings.bridgeHost = host.text.toString()
                settings.bridgePort = port.text.toString().trim().toIntOrNull() ?: 8765
                settings.bridgeToken = token.text.toString()
            }
            settings.folderName = folder.text.toString()
            settings.artistBlocklist = blocklist.text.toString()
            settings.watchedPackages = packagesInput.text.toString()
            settings.watchAllApps = watchAllSwitch.isChecked
            settings.deleteAfterTransfer = deleteAfter.isChecked
            settings.customFeedUrl = feedUrl.text.toString()
            settings.saveLocation = if (
                findViewById<RadioButton>(R.id.saveToBridgeRadio).isChecked
            ) {
                AppSettings.SAVE_BRIDGE
            } else {
                AppSettings.SAVE_LOCAL
            }
            Toast.makeText(this, "Settings saved", Toast.LENGTH_SHORT).show()
            finish()
        }

        // Where the songs are kept. The buttons show what is set now, and
        // take effect straight away - there is no reason to make the user
        // press Save for a thing with two answers.
        val saveToPhoneRadio = findViewById<RadioButton>(R.id.saveToPhoneRadio)
        val saveToBridgeRadio = findViewById<RadioButton>(R.id.saveToBridgeRadio)
        val saveLocationGroup = findViewById<RadioGroup>(R.id.saveLocationGroup)
        if (settings.saveLocation == AppSettings.SAVE_BRIDGE) {
            saveToBridgeRadio.isChecked = true
        } else {
            saveToPhoneRadio.isChecked = true
        }
        saveLocationGroup.setOnCheckedChangeListener { _, which ->
            settings.saveLocation = if (which == R.id.saveToBridgeRadio) {
                AppSettings.SAVE_BRIDGE
            } else {
                AppSettings.SAVE_LOCAL
            }
        }

        buildPackagePicker(watchAllSwitch.isChecked)
    }

    /**
     * Shows the music apps and browsers as checkboxes.
     *
     * The list is a convenience, not a whitelist: with "watch every app"
     * on, anything that plays music is picked up whether it is on this
     * list or not. The list is here so the screen shows something a
     * person can read - and so somebody who wants only one app can say so.
     */
    private fun buildPackagePicker(watchAll: Boolean) {
        packagesBox.removeAllViews()
        val detected = MusicApps.detect(this)

        if (detected.isEmpty()) {
            packagesHint.text =
                "No music apps found. Any app that plays music still works - " +
                "this list is only there to show what is on the phone."
            return
        }

        packagesHint.text = if (watchAll) {
            "Everything that plays music is picked up already. These are on " +
            "this phone - tick them only if you want to watch just these."
        } else {
            "Tap the apps you want watched:"
        }
        val current = settings.watchedPackages.split(",").map { it.trim() }.toSet()

        for (app in detected) {
            val box = CheckBox(this)
            box.text = "${app.label}\n${app.packageName}"
            box.textSize = 12f
            box.isChecked = current.contains(app.packageName)
            box.tag = app.packageName
            box.setOnCheckedChangeListener { _, _ ->
                val selected = packagesBox.children()
                    .filterIsInstance<CheckBox>()
                    .filter { it.isChecked }
                    .mapNotNull { it.tag as? String }
                packagesInput.setText(selected.joinToString(", "))
            }
            packagesBox.addView(box)
        }
    }

    private fun LinearLayout.children(): List<View> =
        (0 until childCount).map { getChildAt(it) }

    /**
     * Shows what the bridge says about cookies.
     *
     * The bridge looks for a jar on its own, so the answer comes from the
     * bridge rather than from what the app happens to know.
     */
    private fun showCookieState() {
        val name = settings.cookiesFileName
        cookiesStatus.text = if (name.isEmpty()) {
            getString(R.string.cookies_none)
        } else {
            getString(R.string.cookies_set, name)
        }
    }

    /**
     * Hands the chosen jar to the bridge.
     *
     * Failing here is not fatal: the jar is kept, and the next download
     * sends it again. The user is told, because a bridge on another
     * machine that is too old to take a jar would never get past the
     * sign-in demand.
     */
    private fun pushJarToBridge() {
        if (!CookieStore.hasJar(this)) return
        lifecycleScope.launch {
            val sent = CookieStore.sendToBridge(this@SettingsActivity,
                bridgeClient(settings))
            val failure = sent.exceptionOrNull()
            if (failure != null) {
                Toast.makeText(this@SettingsActivity,
                    getString(R.string.cookies_send_failed,
                        failure.message ?: "unknown"),
                    Toast.LENGTH_LONG).show()
            }
        }
    }

    /**
     * A client for the bridge the app is set up to use.
     *
     * The address and the token come from the settings, so the bridge
     * inside the app and a bridge on another machine are reached the same
     * way - there is no second way of addressing the bridge.
     */
    private fun bridgeClient(settings: AppSettings) = BridgeClient(
        settings.bridgeAddress.first,
        settings.bridgeAddress.second,
        settings.bridgeAuthToken,
        settings.bridgeScheme,
        settings.bridgePath
    )

    /** Opens a web address in the browser. */
    private fun openUrl(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (_: Exception) {
            Toast.makeText(this, "Could not open the link", Toast.LENGTH_SHORT).show()
        }
    }

    abstract class SimpleSeekListener : SeekBar.OnSeekBarChangeListener {
        override fun onStartTrackingTouch(sb: SeekBar?) {}
        override fun onStopTrackingTouch(sb: SeekBar?) {}
    }
}
