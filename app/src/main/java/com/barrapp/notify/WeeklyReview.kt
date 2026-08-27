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
import androidx.work.Constraints
import androidx.work.ListenableWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.WorkManager
import com.barrapp.MainActivity
import com.barrapp.R
import com.barrapp.data.ProfileStore
import com.barrapp.data.SessionStore
import java.util.Calendar
import java.util.concurrent.TimeUnit

/**
 * The weekly review.
 *
 * Written on the phone from the sessions already measured, not fetched. That
 * keeps it honest by construction: it can only say things the data supports,
 * and it works with no network and no account. The server's prose model writes
 * the per-clip read-out; this is the arithmetic over a week, which does not
 * need a model and should not pretend to.
 *
 * It only fires when there is something to say. A notification that arrives
 * every Monday whether or not you trained is one people turn off in a fortnight.
 */
class WeeklyReviewWorker(
    context: Context,
    params: WorkerParameters,
) : Worker(context, params) {

    // Spelled out: an unqualified `Result` in a Worker collides with
    // kotlin.Result, which is a default import.
    override fun doWork(): ListenableWorker.Result {
        val context = applicationContext
        val review = buildReview(context) ?: return ListenableWorker.Result.success()
        notify(context, review.title, review.body)
        SessionStore.markReviewed(context)
        return ListenableWorker.Result.success()
    }

    private fun notify(context: Context, title: String, body: String) {
        ensureChannel(context)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val open = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        runCatching { NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification) }
    }

    companion object {
        const val CHANNEL = "weekly_review"
        private const val NOTIFICATION_ID = 4201
        private const val WORK_NAME = "barrapp_weekly_review"

        fun ensureChannel(context: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            if (manager.getNotificationChannel(CHANNEL) != null) return
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL,
                    "Weekly review",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "One summary a week, only when there is something to report."
                }
            )
        }

        /** Schedule for roughly Monday morning, repeating weekly. */
        fun schedule(context: Context) {
            ensureChannel(context)
            val request = PeriodicWorkRequestBuilder<WeeklyReviewWorker>(7, TimeUnit.DAYS)
                .setInitialDelay(millisUntilNextMonday(), TimeUnit.MILLISECONDS)
                .setConstraints(Constraints.Builder().build())
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
        }

        private fun millisUntilNextMonday(): Long {
            val now = Calendar.getInstance()
            val target = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, 9)
                set(Calendar.MINUTE, 0)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
                while (get(Calendar.DAY_OF_WEEK) != Calendar.MONDAY || timeInMillis <= now.timeInMillis) {
                    add(Calendar.DAY_OF_YEAR, 1)
                }
            }
            return (target.timeInMillis - now.timeInMillis).coerceAtLeast(60_000L)
        }

        fun buildReview(context: Context): ReviewText.Review? =
            ReviewText.compose(ProfileStore.load(context), SessionStore.days(context))
    }
}
