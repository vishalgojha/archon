package ai.archon.mobile

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.provider.CalendarContract
import android.provider.ContactsContract
import androidx.core.content.ContextCompat
import kotlinx.serialization.Serializable
import java.util.Calendar

class ContextCollector(
    private val context: Context,
    private val auditLogStore: AuditLogStore,
) {
    fun getRecentWhatsApp(limit: Int): List<WhatsAppEvent> {
        return auditLogStore.getRecentWhatsApp(limit)
    }

    fun getTodayCalendarEvents(): List<CalendarEvent> {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED) {
            return emptyList()
        }

        val now = Calendar.getInstance()
        val start = now.clone() as Calendar
        start.set(Calendar.HOUR_OF_DAY, 0)
        start.set(Calendar.MINUTE, 0)
        start.set(Calendar.SECOND, 0)
        start.set(Calendar.MILLISECOND, 0)

        val end = now.clone() as Calendar
        end.set(Calendar.HOUR_OF_DAY, 23)
        end.set(Calendar.MINUTE, 59)
        end.set(Calendar.SECOND, 59)
        end.set(Calendar.MILLISECOND, 999)

        val projection = arrayOf(
            CalendarContract.Events.TITLE,
            CalendarContract.Events.DTSTART,
            CalendarContract.Events.DTEND,
            CalendarContract.Events.EVENT_LOCATION,
        )
        val selection = "${CalendarContract.Events.DTSTART} >= ? AND ${CalendarContract.Events.DTSTART} <= ?"
        val selectionArgs = arrayOf(start.timeInMillis.toString(), end.timeInMillis.toString())

        val results = mutableListOf<CalendarEvent>()
        val cursor = context.contentResolver.query(
            CalendarContract.Events.CONTENT_URI,
            projection,
            selection,
            selectionArgs,
            "${CalendarContract.Events.DTSTART} ASC",
        )
        cursor?.use {
            while (it.moveToNext()) {
                results.add(
                    CalendarEvent(
                        title = it.getString(0) ?: "",
                        startTs = it.getLong(1),
                        endTs = it.getLong(2),
                        location = it.getString(3),
                    ),
                )
            }
        }
        return results
    }

    fun getLastKnownLocation(): Location? {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            return null
        }
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val providers = manager.getProviders(true)
        var best: Location? = null
        for (provider in providers) {
            val location = manager.getLastKnownLocation(provider) ?: continue
            if (best == null || location.accuracy < best.accuracy) {
                best = location
            }
        }
        return best
    }

    fun searchContacts(query: String): List<ContactMatch> {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            return emptyList()
        }

        if (query.isBlank()) return emptyList()

        val projection = arrayOf(
            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
            ContactsContract.CommonDataKinds.Phone.NUMBER,
        )
        val selection = "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?"
        val selectionArgs = arrayOf("%$query%")

        val results = mutableListOf<ContactMatch>()
        val cursor = context.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            projection,
            selection,
            selectionArgs,
            "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} ASC",
        )
        cursor?.use {
            while (it.moveToNext()) {
                results.add(
                    ContactMatch(
                        name = it.getString(0) ?: "",
                        phone = it.getString(1) ?: "",
                    ),
                )
            }
        }
        return results
    }
}

@Serializable
data class CalendarEvent(
    val title: String,
    val startTs: Long,
    val endTs: Long,
    val location: String?,
)

@Serializable
data class ContactMatch(
    val name: String,
    val phone: String,
)
