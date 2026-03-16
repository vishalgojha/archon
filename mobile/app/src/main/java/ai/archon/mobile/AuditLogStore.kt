package ai.archon.mobile

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import kotlinx.serialization.Serializable

class AuditLogStore(context: Context) : SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE invoke_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                method TEXT NOT NULL,
                request_json TEXT,
                response_json TEXT,
                status TEXT NOT NULL
            )
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE TABLE whatsapp_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                sender TEXT,
                message TEXT,
                group_name TEXT
            )
            """.trimIndent(),
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS invoke_audit")
        db.execSQL("DROP TABLE IF EXISTS whatsapp_events")
        onCreate(db)
    }

    fun logInvoke(method: String, requestJson: String?, responseJson: String?, status: String) {
        val values = ContentValues().apply {
            put("ts", System.currentTimeMillis())
            put("method", method)
            put("request_json", requestJson)
            put("response_json", responseJson)
            put("status", status)
        }
        writableDatabase.insert("invoke_audit", null, values)
    }

    fun logWhatsApp(sender: String?, message: String?, groupName: String?) {
        val values = ContentValues().apply {
            put("ts", System.currentTimeMillis())
            put("sender", sender)
            put("message", message)
            put("group_name", groupName)
        }
        writableDatabase.insert("whatsapp_events", null, values)
    }

    fun getRecentWhatsApp(limit: Int): List<WhatsAppEvent> {
        val events = mutableListOf<WhatsAppEvent>()
        val cursor = readableDatabase.query(
            "whatsapp_events",
            arrayOf("ts", "sender", "message", "group_name"),
            null,
            null,
            null,
            null,
            "ts DESC",
            limit.toString(),
        )
        cursor.use {
            while (it.moveToNext()) {
                events.add(
                    WhatsAppEvent(
                        ts = it.getLong(0),
                        sender = it.getString(1),
                        message = it.getString(2),
                        groupName = it.getString(3),
                    ),
                )
            }
        }
        return events
    }

    companion object {
        private const val DB_NAME = "archon_mobile.db"
        private const val DB_VERSION = 1
    }
}

@Serializable
data class WhatsAppEvent(
    val ts: Long,
    val sender: String?,
    val message: String?,
    val groupName: String?,
)
