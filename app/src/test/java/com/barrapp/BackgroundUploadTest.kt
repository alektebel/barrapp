package com.barrapp

import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import androidx.test.core.app.ApplicationProvider
import com.barrapp.data.Work
import com.barrapp.data.WorkStore
import com.barrapp.notify.ProcessingNotifier
import com.barrapp.upload.UploadWorker
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Uploading with the app closed.
 *
 * The queue runs in a WorkManager worker (upload/UploadWorker), which the
 * system starts again after the process dies and only with a network. While
 * it runs it is a foreground service of type dataSync carrying the progress
 * notification; a Xiaomi above all kills background apps early otherwise.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class BackgroundUploadTest {
    private fun work(status: String) = Work(id = status, createdAt = 0, status = status)

    @Test
    fun `the queue runs only with a network and survives a closed app`() {
        val request = UploadWorker.request()
        assertEquals(androidx.work.NetworkType.CONNECTED,
            request.workSpec.constraints.requiredNetworkType)
        assertTrue(request.workSpec.expedited)
        val info = UploadWorker.foregroundInfo(ApplicationProvider.getApplicationContext())
        assertEquals(ProcessingNotifier.ONGOING_ID, info.notificationId)
        assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC, info.foregroundServiceType)
    }

    @Test
    fun `restart resumes single PUT and multipart transfers including connecting state`() {
        assertTrue(WorkStore.resumesUploadAfterRestart(work(WorkStore.STATUS_SENDING)
            .copy(jobId = "j1", uploadMode = "single")))
        assertTrue(WorkStore.resumesUploadAfterRestart(work(WorkStore.STATUS_CONNECTING)
            .copy(jobId = "j2", uploadMode = "single", uploadComplete = true)))
        assertTrue(WorkStore.resumesUploadAfterRestart(work(WorkStore.STATUS_CONNECTING)
            .copy(jobId = "j3", uploadId = "multipart-1")))
        assertFalse(WorkStore.resumesUploadAfterRestart(work(WorkStore.STATUS_SENDING)))
        assertFalse(WorkStore.resumesUploadAfterRestart(work(WorkStore.STATUS_FAILED)
            .copy(uploadMode = "single")))
    }

    @Test
    fun `restart waits on a clip the server already holds instead of re-sending it`() {
        assertTrue(WorkStore.waitsOnServerAfterRestart(work(WorkStore.STATUS_QUEUED).copy(jobId = "j1")))
        assertTrue(WorkStore.waitsOnServerAfterRestart(work(WorkStore.STATUS_MEASURING).copy(jobId = "j2")))
        assertTrue(WorkStore.waitsOnServerAfterRestart(work(WorkStore.STATUS_SENDING)
            .copy(jobId = "j3", uploadMode = "single", uploadComplete = true)))
        // Mid-send or never sent: not the server's yet.
        assertFalse(WorkStore.waitsOnServerAfterRestart(work(WorkStore.STATUS_SENDING)
            .copy(jobId = "j4", uploadId = "multipart-1")))
        assertFalse(WorkStore.waitsOnServerAfterRestart(work(WorkStore.STATUS_WAITING)))
        // A job past submit is never submitted again: that would re-run the worker.
        for (status in listOf("queued", "processing", "done", "failed")) {
            assertTrue(status in WorkStore.SUBMITTED_ON_SERVER)
        }
        for (status in listOf("new", "created", "uploaded")) {
            assertFalse(status in WorkStore.SUBMITTED_ON_SERVER)
        }
    }

    @Test
    fun `the service is declared as a data-sync foreground service`() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        val info = ctx.packageManager.getServiceInfo(
            android.content.ComponentName(ctx, androidx.work.impl.foreground.SystemForegroundService::class.java), PackageManager.GET_META_DATA)
        assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            info.foregroundServiceType and ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        assertFalse(info.exported)
    }

    @Test
    fun `the permissions it needs are declared`() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        val perms = ctx.packageManager.getPackageInfo(ctx.packageName, PackageManager.GET_PERMISSIONS)
            .requestedPermissions.orEmpty().toSet()
        assertTrue(perms.contains("android.permission.FOREGROUND_SERVICE"))
        assertTrue(perms.contains("android.permission.FOREGROUND_SERVICE_DATA_SYNC"))
    }

    @Test
    fun `the notification speaks spanish`() {
        for (s in ProcessingNotifier.STAGES + ProcessingNotifier.TITLE + ProcessingNotifier.CHANNEL_NAME) {
            for (word in listOf("the ", "clip", "analyzing", "uploading", "your")) {
                assertFalse("$s contains $word", s.lowercase().contains(word))
            }
        }
    }
}
