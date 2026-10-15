package com.barrapp

import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import androidx.test.core.app.ApplicationProvider
import com.barrapp.data.Work
import com.barrapp.data.WorkStore
import com.barrapp.notify.ProcessingNotifier
import com.barrapp.notify.UploadService
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Uploading while the athlete uses other apps.
 *
 * The upload and the polling run in the app's process; on a Xiaomi in
 * particular that process is killed soon after it leaves the screen. A
 * foreground service (type dataSync) runs while any clip is active - sending,
 * queued or being measured - and carries the progress notification, so the
 * process stays alive and the athlete can see where the clip is.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class BackgroundUploadTest {
    private fun work(status: String) = Work(id = status, createdAt = 0, status = status)

    @Test
    fun `the service runs exactly while a clip is active`() {
        assertTrue(UploadService.shouldRun(listOf(work(WorkStore.STATUS_SENDING))))
        assertTrue(UploadService.shouldRun(listOf(work(WorkStore.STATUS_MEASURING))))
        assertTrue(UploadService.shouldRun(listOf(work(WorkStore.STATUS_CONNECTING))))
        assertFalse(UploadService.shouldRun(listOf(work(WorkStore.STATUS_DONE), work(WorkStore.STATUS_FAILED))))
        assertFalse(UploadService.shouldRun(emptyList()))
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
    fun `the service is declared as a data-sync foreground service`() {
        val ctx = ApplicationProvider.getApplicationContext<android.content.Context>()
        val info = ctx.packageManager.getServiceInfo(
            android.content.ComponentName(ctx, UploadService::class.java), PackageManager.GET_META_DATA)
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
