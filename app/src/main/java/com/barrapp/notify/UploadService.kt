package com.barrapp.notify

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.barrapp.data.Work

/**
 * Keeps the app alive while a clip is on its way: sending, queued or being
 * measured.
 *
 * The upload and the polling run in the app's process (BarrappViewModel), and a
 * phone - a Xiaomi above all - kills a process soon after it leaves the screen.
 * A foreground service of type dataSync, carrying the progress notification,
 * is the platform's way of saying "this user-started transfer is still going".
 * It does no work itself; it starts when the first clip becomes active and
 * stops when none is.
 */
class UploadService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = ProcessingNotifier.ongoing(this, intent?.getStringExtra(EXTRA_TEXT)
            ?: ProcessingNotifier.STAGES.first(), intent?.getIntExtra(EXTRA_INDEX, 0) ?: 0)
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0
        ServiceCompat.startForeground(this, ProcessingNotifier.ONGOING_ID, notification, type)
        return START_NOT_STICKY
    }

    companion object {
        private const val EXTRA_TEXT = "text"
        private const val EXTRA_INDEX = "index"
        @Volatile private var running = false

        fun shouldRun(works: List<Work>): Boolean = works.any { it.active }

        /** Start or stop to match the queue. Called on every queue change. */
        fun sync(context: Context, works: List<Work>, text: String? = null, index: Int = 0) {
            val app = context.applicationContext
            if (shouldRun(works)) {
                if (running && text == null) return
                val intent = Intent(app, UploadService::class.java)
                    .putExtra(EXTRA_TEXT, text ?: works.first { it.active }.line)
                    .putExtra(EXTRA_INDEX, index)
                // Android 12+ refuses to START a foreground service from the
                // background; the first start happens when the athlete picks a
                // clip (foreground), and a refusal later only loses the keep-alive,
                // never the upload.
                running = runCatching { ContextCompat.startForegroundService(app, intent) }.isSuccess
            } else if (running) {
                app.stopService(Intent(app, UploadService::class.java))
                running = false
            }
        }
    }
}
