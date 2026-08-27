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
import com.barrapp.data.DayEntry
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

        data class Review(val title: String, val body: String)

        /**
         * The week's arithmetic, or null when there is nothing worth a
         * notification.
         *
         * Public so the in-app card shows exactly the text the notification
         * would - two summaries that disagree would be worse than one.
         */
        fun buildReview(context: Context): Review? {
            val profile = ProfileStore.load(context)
            val all = SessionStore.days(context)
            val since = weekAgo()
            val week = all.filter { it.date >= since }
            if (week.isEmpty()) return null

            val reps = week.sumOf { it.reps }
            val comparable = week.count { it.reps >= 3 }
            val measured = week.filter { it.measured }
            val name = profile.firstName

            val title = "$name — ${week.size} session${if (week.size == 1) "" else "s"} this week"
            val body = buildString {
                append("$reps rep${if (reps == 1) "" else "s"} measured across ")
                append("${week.size} day${if (week.size == 1) "" else "s"}. ")
                when {
                    comparable == 0 -> append(
                        "None reached 3 measured reps, so none can be compared with another " +
                            "session yet. Aim for ${profile.repTarget} in one set."
                    )
                    comparable == 1 -> append(
                        "One session reached the 3-rep floor. One more and there is something " +
                            "to compare it against."
                    )
                    else -> {
                        append("$comparable sessions cleared the 3-rep floor. ")
                        val trend = trendSentence(measured)
                        if (trend != null) append(trend)
                        else append("Scores held level within their own spread.")
                    }
                }
            }
            return Review(title, body)
        }

        private fun trendSentence(measured: List<DayEntry>): String? {
            if (measured.size < 2) return null
            val ordered = measured.sortedBy { it.date }
            val delta = (ordered.last().score ?: 0) - (ordered.first().score ?: 0)
            // Below this the difference is inside the noise of a proxy built
            // from three bounded components; calling it a trend would be an
            // invention.
            if (kotlin.math.abs(delta) < 8) return null
            return if (delta > 0)
                "The baseline proxy is up $delta points across the week, which is worth a look " +
                    "but has not been tested against your own rep-to-rep variation."
            else
                "The baseline proxy is down ${-delta} points across the week."
        }

        private fun weekAgo(): String {
            val c = Calendar.getInstance()
            c.add(Calendar.DAY_OF_YEAR, -7)
            return "%04d-%02d-%02d".format(
                c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH)
            )
        }
    }
}
