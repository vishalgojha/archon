package ai.archon.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import kotlinx.serialization.encodeToJsonElement
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive

class InvokeDispatcher(
    private val context: Context,
    private val auditLogStore: AuditLogStore,
    private val contextCollector: ContextCollector,
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun handleInvoke(method: String, params: JsonObject?): JsonElement {
        val requestJson = params?.toString()
        val wakeLock = acquireWakeLock()
        return try {
            val result = when (method) {
                "read_whatsapp" -> {
                    val limit = params?.get("limit")?.jsonPrimitive?.intOrNull ?: 20
                    val events = contextCollector.getRecentWhatsApp(limit)
                    buildJsonObject {
                        put("events", json.encodeToJsonElement(events))
                    }
                }
                "get_calendar" -> {
                    val events = contextCollector.getTodayCalendarEvents()
                    buildJsonObject {
                        put("events", json.encodeToJsonElement(events))
                    }
                }
                "get_location" -> {
                    val location = contextCollector.getLastKnownLocation()
                    if (location == null) JsonNull else {
                        buildJsonObject {
                            put("lat", JsonPrimitive(location.latitude))
                            put("lng", JsonPrimitive(location.longitude))
                            put("accuracy", JsonPrimitive(location.accuracy.toDouble()))
                            put("ts", JsonPrimitive(location.time))
                        }
                    }
                }
                "send_notification" -> {
                    val title = params?.get("title")?.jsonPrimitive?.contentOrNull ?: "Archon"
                    val body = params?.get("body")?.jsonPrimitive?.contentOrNull ?: ""
                    postLocalNotification(title, body)
                    buildJsonObject { put("status", JsonPrimitive("sent")) }
                }
                "get_contacts" -> {
                    val query = params?.get("query")?.jsonPrimitive?.contentOrNull ?: ""
                    val contacts = contextCollector.searchContacts(query)
                    buildJsonObject {
                        put("contacts", json.encodeToJsonElement(contacts))
                    }
                }
                else -> buildJsonObject {
                    put("error", JsonPrimitive("unknown_method"))
                }
            }
            auditLogStore.logInvoke(method, requestJson, result.toString(), "ok")
            result
        } catch (ex: Exception) {
            auditLogStore.logInvoke(method, requestJson, "{\"error\":\"${ex.message}\"}", "error")
            buildJsonObject {
                put("error", JsonPrimitive(ex.message ?: "invoke_failed"))
            }
        } finally {
            wakeLock?.let {
                if (it.isHeld) {
                    it.release()
                }
            }
        }
    }

    private fun postLocalNotification(title: String, body: String) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "archon_events"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(channelId, "Archon Events", NotificationManager.IMPORTANCE_DEFAULT)
            manager.createNotificationChannel(channel)
        }

        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .build()

        manager.notify((System.currentTimeMillis() % 10000).toInt(), notification)
    }

    private fun acquireWakeLock(): PowerManager.WakeLock? {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        val wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "archon:invoke")
        wakeLock.setReferenceCounted(false)
        wakeLock.acquire(20_000L)
        return wakeLock
    }
}
