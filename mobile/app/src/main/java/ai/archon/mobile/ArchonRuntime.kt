package ai.archon.mobile

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.util.Log
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit
import kotlin.math.min

class ArchonRuntime(private val context: Context) : GatewaySession.Listener {
    private val config = MobileConfig(context)
    private val auditLogStore = AuditLogStore(context)
    private val contextCollector = ContextCollector(context, auditLogStore)
    private val dispatcher = InvokeDispatcher(context, auditLogStore, contextCollector)
    private val session = GatewaySession(config, dispatcher, this)

    @Volatile
    private var reconnectAttempt = 0

    fun start() {
        ArchonRuntimeRegistry.setSession(session)
        session.connect()
        scheduleHeartbeat()
    }

    fun stop() {
        session.disconnect()
        ArchonRuntimeRegistry.clearSession()
    }

    override fun onConnected() {
        reconnectAttempt = 0
        Log.i(TAG, "gateway connected")
    }

    override fun onDisconnected(reason: String) {
        Log.w(TAG, "gateway disconnected: $reason")
        scheduleReconnect()
    }

    private fun scheduleReconnect() {
        reconnectAttempt += 1
        val exponent = (reconnectAttempt - 1).coerceAtMost(10)
        val delayMs = min(INITIAL_RECONNECT_MS * (1L shl exponent), MAX_RECONNECT_MS)
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val intent = Intent(context, ArchonForegroundService::class.java).apply {
            action = ArchonForegroundService.ACTION_RECONNECT
        }
        val pendingIntent = PendingIntent.getService(
            context,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        alarmManager.setExactAndAllowWhileIdle(
            AlarmManager.ELAPSED_REALTIME_WAKEUP,
            SystemClock.elapsedRealtime() + delayMs,
            pendingIntent,
        )
    }

    private fun scheduleHeartbeat() {
        val request = PeriodicWorkRequestBuilder<HeartbeatWorker>(15, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            "archon_heartbeat",
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    companion object {
        private const val TAG = "ArchonRuntime"
        private const val INITIAL_RECONNECT_MS = 2_000L
        private const val MAX_RECONNECT_MS = 60_000L
    }
}

object ArchonRuntimeRegistry {
    @Volatile
    private var session: GatewaySession? = null

    fun setSession(value: GatewaySession) {
        session = value
    }

    fun clearSession() {
        session = null
    }

    fun sendWhatsAppEvent(event: WhatsAppEvent) {
        val payload = kotlinx.serialization.json.buildJsonObject {
            put("ts", kotlinx.serialization.json.JsonPrimitive(event.ts))
            put("sender", kotlinx.serialization.json.JsonPrimitive(event.sender ?: ""))
            put("message", kotlinx.serialization.json.JsonPrimitive(event.message ?: ""))
            put("group", kotlinx.serialization.json.JsonPrimitive(event.groupName ?: ""))
        }
        session?.sendContextEvent("context.whatsapp", payload)
    }
}
