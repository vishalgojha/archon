package ai.archon.mobile

import android.content.Context
import android.content.Intent
import androidx.work.Worker
import androidx.work.WorkerParameters

class HeartbeatWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {
    override fun doWork(): Result {
        val intent = Intent(applicationContext, ArchonForegroundService::class.java)
        intent.action = ArchonForegroundService.ACTION_HEARTBEAT
        applicationContext.startForegroundService(intent)
        return Result.success()
    }
}
