package ai.archon.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LifecycleService

class ArchonForegroundService : LifecycleService() {
    private var runtime: ArchonRuntime? = null

    override fun onCreate() {
        super.onCreate()
        runtime = ArchonRuntime(this)
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_RECONNECT -> runtime?.start()
            ACTION_HEARTBEAT -> runtime?.start()
            else -> runtime?.start()
        }
        return Service.START_STICKY
    }

    override fun onDestroy() {
        runtime?.stop()
        runtime = null
        super.onDestroy()
    }

    private fun buildNotification(): Notification {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Archon Mobile",
                NotificationManager.IMPORTANCE_LOW,
            )
            manager.createNotificationChannel(channel)
        }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.presence_online)
            .setContentTitle("Archon is running")
            .setContentText("Silent background agent")
            .setOngoing(true)
            .build()
    }

    companion object {
        const val ACTION_RECONNECT = "ai.archon.mobile.action.RECONNECT"
        const val ACTION_HEARTBEAT = "ai.archon.mobile.action.HEARTBEAT"
        private const val CHANNEL_ID = "archon_foreground"
        private const val NOTIFICATION_ID = 1001
    }
}
