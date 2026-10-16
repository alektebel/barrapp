package com.barrapp.upload

import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.BackoffPolicy
import com.barrapp.notify.ProcessingNotifier
import java.util.concurrent.TimeUnit

/**
 * Runs the upload queue whether or not the app is open.
 *
 * WorkManager keeps the request across a closed app, a killed process and a
 * reboot, and only starts it with a network. While it runs it is a
 * foreground service of type dataSync carrying the progress notification, so
 * a phone that kills background apps early (a Xiaomi above all) leaves it
 * alone. A clip paused for the network makes it ask to run again later.
 */
class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun getForegroundInfo(): ForegroundInfo = foregroundInfo(applicationContext)

    override suspend fun doWork(): Result {
        // Android 12+ may refuse a foreground service started from the
        // background; the queue still runs, just without the keep-alive.
        runCatching { setForeground(getForegroundInfo()) }
        val waitsForNetwork = UploadQueue.get(applicationContext).drain()
        return if (waitsForNetwork) Result.retry() else Result.success()
    }

    companion object {
        const val NAME = "barrapp-upload-queue"

        fun foregroundInfo(context: Context): ForegroundInfo {
            val notification = ProcessingNotifier.ongoing(
                context, ProcessingNotifier.STAGES.first(), 0)
            return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ForegroundInfo(ProcessingNotifier.ONGOING_ID, notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            } else ForegroundInfo(ProcessingNotifier.ONGOING_ID, notification)
        }

        fun request() = OneTimeWorkRequestBuilder<UploadWorker>()
            .setConstraints(Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .setBackoffCriteria(BackoffPolicy.LINEAR, 30, TimeUnit.SECONDS)
            .build()

        /** One queue: a kick while it runs appends one more pass after it,
         *  which picks up whatever arrived meanwhile. */
        fun enqueue(context: Context) {
            runCatching {
                WorkManager.getInstance(context).enqueueUniqueWork(
                    NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, request())
            }
        }
    }
}
