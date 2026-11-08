package com.autosongs.bridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Keeps the bridge running.
 *
 * Android closes apps that sit in the background, and this app's whole
 * job is to sit in the background. So it runs as a foreground service,
 * and its notification shows the code - so a phone can pair with it
 * without this app being open at all.
 */
class BridgeService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var poller: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopEverything()
            return START_NOT_STICKY
        }

        startInForeground()

        if (!BridgeRunner.isRunning()) {
            val started = BridgeRunner.start(this)
            if (!started) {
                Log.e(TAG, "the bridge did not start: ${BridgeRunner.lastError}")
            }
        }
        // Again, now that the code is known: the notification shows it.
        startInForeground()
        startPolling()
        return START_STICKY
    }

    override fun onDestroy() {
        stopEverything()
        super.onDestroy()
    }

    private fun stopEverything() {
        poller?.cancel()
        poller = null
        BridgeRunner.stop()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /**
     * Looks for finished songs and puts them in the library.
     *
     * The bridge writes them into this app's own folder, because an app
     * cannot write straight into a public folder on modern Android.
     */
    private fun startPolling() {
        if (poller?.isActive == true) return
        poller = scope.launch {
            while (isActive) {
                try {
                    val moved = LibraryImporter.sweep(this@BridgeService)
                    if (moved > 0) {
                        Log.i(TAG, "$moved song(s) moved into the library")
                        startInForeground()
                    }
                } catch (t: Throwable) {
                    Log.w(TAG, "the library could not be swept", t)
                }
                delay(4000)
            }
        }
    }

    private fun startInForeground() {
        makeChannel()
        val notification = buildNotification()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
                )
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        } catch (t: Throwable) {
            Log.e(TAG, "the notification could not be shown", t)
        }
    }

    private fun buildNotification(): Notification {
        val code = BridgeRunner.code
        val title = if (code.isBlank()) {
            getString(R.string.bridge_starting)
        } else {
            getString(R.string.bridge_running)
        }
        val text = if (code.isBlank()) {
            getString(R.string.bridge_starting_detail)
        } else {
            getString(R.string.bridge_code_in_notification, code)
        }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(
                PendingIntent.getActivity(
                    this, 0,
                    Intent(this, MainActivity::class.java),
                    PendingIntent.FLAG_IMMUTABLE
                )
            )
            .build()
    }

    private fun makeChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.bridge_channel),
            NotificationManager.IMPORTANCE_LOW
        )
        channel.setShowBadge(false)
        manager.createNotificationChannel(channel)
    }

    companion object {
        private const val TAG = "BridgeService"
        private const val CHANNEL_ID = "autosongs_bridge"
        private const val NOTIFICATION_ID = 41

        const val ACTION_STOP = "com.autosongs.bridge.STOP"

        fun start(context: Context) {
            val intent = Intent(context, BridgeService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            val intent = Intent(context, BridgeService::class.java).setAction(ACTION_STOP)
            context.startService(intent)
        }
    }
}
