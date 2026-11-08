package com.autosongs.bridge

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.autosongs.bridge.databinding.ActivityMainBinding
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The bridge, and the code to pair with it.
 *
 * The whole screen is one thing: here is the bridge, here is the code,
 * type the code on the other phone. Everything else is a footnote.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.startButton.setOnClickListener {
            requestNotificationsThenStart()
        }
        binding.stopButton.setOnClickListener {
            BridgeService.stop(this)
            showState()
        }
        binding.copyCodeButton.setOnClickListener {
            copy(BridgeRunner.code)
        }
        binding.newCodeButton.setOnClickListener {
            // A new code, so an old one that was read over someone's
            // shoulder stops working. The key stays the same, so a phone
            // that is already paired stays paired.
            BridgeService.stop(this)
            BridgeService.start(this)
            toast(getString(R.string.new_code_made))
        }
        binding.batteryButton.setOnClickListener {
            askForBatteryExemption()
        }
        binding.libraryButton.setOnClickListener {
            copy(getString(R.string.library_where, libraryPath()))
        }

        askForNotifications()
        showState()
    }

    override fun onResume() {
        super.onResume()
        showState()
    }

    /** Shows what the bridge is doing. */
    private fun showState() {
        val running = BridgeRunner.isRunning()
        val code = BridgeRunner.code
        binding.codeText.text = if (code.isBlank()) "--------" else code
        binding.addressText.text = if (running) {
            BridgeRunner.address
        } else {
            getString(R.string.not_running)
        }
        binding.stateText.text = when {
            running -> getString(R.string.bridge_running)
            BridgeRunner.lastError.isNotBlank() ->
                getString(R.string.bridge_failed, BridgeRunner.lastError)
            else -> getString(R.string.bridge_stopped)
        }
        binding.startButton.isEnabled = !running
        binding.stopButton.isEnabled = running
        binding.copyCodeButton.isEnabled = running
        binding.newCodeButton.isEnabled = running
        binding.versionText.text = getString(
            R.string.bridge_version,
            BridgeRunner.version().ifBlank { "-" },
            BridgeRunner.ytDlpVersion().ifBlank { "-" }
        )
        binding.batteryButton.isEnabled = !hasBatteryExemption()
    }

    /** Where the finished songs end up. */
    private fun libraryPath(): String =
        "${getExternalFilesDir(null)?.absolutePath ?: filesDir.absolutePath}/library"

    private fun hasBatteryExemption(): Boolean = try {
        val pm = getSystemService(PowerManager::class.java)
        pm?.isIgnoringBatteryOptimizations(packageName) == true
    } catch (_: Throwable) {
        false
    }

    /**
     * Asks Android to leave this app alone.
     *
     * Without it, Android closes the bridge in the evening and the phone
     * that was going to save songs quietly stops.
     */
    private fun askForBatteryExemption() {
        if (hasBatteryExemption()) {
            toast(getString(R.string.battery_already_ok))
            return
        }
        try {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                    .setData(Uri.parse("package:$packageName"))
            )
        } catch (_: Throwable) {
            try {
                startActivity(
                    Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                )
            } catch (_: Throwable) {
                toast(getString(R.string.battery_could_not_open))
            }
        }
    }

    private fun requestNotificationsThenStart() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 7)
            return
        }
        BridgeService.start(this)
        showState()
        // The bridge takes a moment: Python has to load first.
        lifecycleScope.launch {
            repeat(20) {
                delay(500)
                showState()
                if (BridgeRunner.isRunning() && BridgeRunner.code.isNotBlank()) return@launch
            }
        }
    }

    private fun askForNotifications() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            == PackageManager.PERMISSION_GRANTED
        ) return
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 7)
    }

    private fun copy(text: String) {
        if (text.isBlank()) return
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
        clipboard?.setPrimaryClip(ClipData.newPlainText("AutoSongs", text))
        toast(getString(R.string.copied))
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }
}
