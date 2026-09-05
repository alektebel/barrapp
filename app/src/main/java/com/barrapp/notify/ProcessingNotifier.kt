package com.barrapp.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.barrapp.MainActivity
import com.barrapp.R

/**
 * The "your clip is being measured" notification.
 *
 * The measurement runs on the server and can take longer than the time someone
 * wants to sit on the processing screen. So the app says what it is doing in a
 * progress notification, keeps updating it as the job moves through its stages,
 * and posts a result notification when the job is done or has failed - so the
 * user can put the phone down and do something else, and still be told when
 * the analysis is finished.
 */
object ProcessingNotifier {

    const val CHANNEL = "processing"
    private const val ONGOING_ID = 4202
    private const val RESULT_ID = 4203

    // Mirrors BarrappViewModel.STAGE_* in order, so the notification's progress
    // bar can show where in the pipeline the job is.
    private val STAGES = com.barrapp.Voice.STAGES.map { it.name }

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) != null) return
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL,
                "Clip analysis",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Progress and results while a clip is being measured."
                setShowBadge(false)
            }
        )
    }

    /** Post (or refresh) the ongoing notification for a job that is running. */
    fun stage(context: Context, stage: String) {
        if (!canPost(context)) return
        val index = STAGES.indexOfFirst { it.equals(stage, ignoreCase = true) }
            .let { if (it < 0) 0 else it }
        val notification = builder(context, "Measuring your clip")
            .setContentText(stage)
            .setOngoing(true)
            .setProgress(STAGES.size, index, false)
            .setContentIntent(openApp(context))
            .build()
        runCatching { NotificationManagerCompat.from(context).notify(ONGOING_ID, notification) }
    }

    /** Replace the ongoing notification with a "finished" one that opens the result. */
    fun done(context: Context, title: String, body: String) {
        cancel(context)
        if (!canPost(context)) return
        val notification = builder(context, title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(openApp(context))
            .build()
        runCatching { NotificationManagerCompat.from(context).notify(RESULT_ID, notification) }
    }

    /** Replace the ongoing notification with a "failed" one. */
    fun fail(context: Context, message: String) {
        cancel(context)
        if (!canPost(context)) return
        val notification = builder(context, "That clip could not be measured")
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(message))
            .setAutoCancel(true)
            .setContentIntent(openApp(context))
            .build()
        runCatching { NotificationManagerCompat.from(context).notify(RESULT_ID, notification) }
    }

    /** Remove the ongoing notification (upload cancelled, or already replaced). */
    fun cancel(context: Context) {
        runCatching { NotificationManagerCompat.from(context).cancel(ONGOING_ID) }
    }

    private fun builder(context: Context, title: String): NotificationCompat.Builder {
        ensureChannel(context)
        return NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setPriority(NotificationCompat.PRIORITY_LOW)
    }

    private fun openApp(context: Context): PendingIntent =
        PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

    private fun canPost(context: Context): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
        else
            true
}
