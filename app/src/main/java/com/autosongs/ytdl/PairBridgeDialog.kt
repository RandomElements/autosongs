package com.autosongs.ytdl

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.view.LayoutInflater
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.lifecycleScope
import com.autosongs.ytdl.bridge.BridgeDiscovery
import com.autosongs.ytdl.bridge.BridgeVersion
import com.autosongs.ytdl.bridge.PairCode
import com.autosongs.ytdl.data.AppSettings
import kotlinx.coroutines.launch

/**
 * Pairs the app with a bridge on another machine.
 *
 * The bridge shows eight characters on its screen. The user types them
 * here, and the phone works the rest out by itself: where the bridge is,
 * and the key the two share.
 */
object PairBridgeDialog {

    fun show(activity: Activity) {
        val settings = AppSettings.get(activity)
        val view = LayoutInflater.from(activity).inflate(R.layout.dialog_pair_bridge, null)
        val codeInput = view.findViewById<EditText>(R.id.pairCodeInput)
        val link = view.findViewById<TextView>(R.id.pairDownloadLink)
        val status = view.findViewById<TextView>(R.id.pairStatus)

        // Where the bridge for the computer can be fetched.
        val page = BridgeVersion.HOSTS.firstOrNull()
            ?: "https://autosongs.example"
        link.text = page
        link.setOnClickListener {
            try {
                activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(page)))
            } catch (_: Throwable) {
                Toast.makeText(activity, page, Toast.LENGTH_LONG).show()
            }
        }

        val dialog = AlertDialog.Builder(activity)
            .setTitle(R.string.pair_remote_bridge)
            .setView(view)
            .setPositiveButton(R.string.find_and_pair, null)
            .setNegativeButton(android.R.string.cancel, null)
            .create()

        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val typed = codeInput.text.toString().trim()
                if (typed.isEmpty()) {
                    status.text = activity.getString(R.string.pairing_nothing)
                    return@setOnClickListener
                }
                val code = try {
                    PairCode.normalize(typed)
                } catch (e: IllegalArgumentException) {
                    status.text = e.message ?: ""
                    return@setOnClickListener
                }
                val owner = activity as? LifecycleOwner ?: return@setOnClickListener
                status.text = activity.getString(R.string.looking_for_the_bridge)
                owner.lifecycleScope.launch {
                    val found = BridgeDiscovery.find(code)
                    if (found == null) {
                        status.text = activity.getString(R.string.bridge_not_found)
                        return@launch
                    }
                    val token = BridgeDiscovery.claim(found.host, found.port, code)
                        .getOrElse {
                            status.text = activity.getString(R.string.pairing_failed)
                            return@launch
                        }
                    settings.bridgeHost = found.host
                    settings.bridgePort = found.port
                    settings.bridgeToken = token
                    settings.bridgeMode = AppSettings.BRIDGE_REMOTE
                    val said = activity.getString(R.string.paired_with, found.host)
                    status.text = said
                    Toast.makeText(activity, said, Toast.LENGTH_LONG).show()
                    dialog.dismiss()
                }
            }
        }
        dialog.show()
    }
}
