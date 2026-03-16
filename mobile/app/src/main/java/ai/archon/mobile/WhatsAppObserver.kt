package ai.archon.mobile

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class WhatsAppObserver : NotificationListenerService() {
    private lateinit var auditLogStore: AuditLogStore

    override fun onCreate() {
        super.onCreate()
        auditLogStore = AuditLogStore(this)
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName != WHATSAPP_PACKAGE) return

        val extras = sbn.notification.extras
        val sender = extras.getString(Notification.EXTRA_TITLE)
        val message = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
        val group = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()

        if (!isApprovedSender(sender, group)) return

        auditLogStore.logWhatsApp(sender, message, group)
        ArchonRuntimeRegistry.sendWhatsAppEvent(
            WhatsAppEvent(
                ts = System.currentTimeMillis(),
                sender = sender,
                message = message,
                groupName = group,
            ),
        )
    }

    private fun isApprovedSender(sender: String?, group: String?): Boolean {
        val prefs = SecurePrefs.get(this)
        val approved = prefs.getStringSet(KEY_APPROVED_SENDERS, emptySet()) ?: emptySet()
        if (approved.isEmpty()) return false
        val normalizedSender = sender?.lowercase()?.trim() ?: ""
        val normalizedGroup = group?.lowercase()?.trim() ?: ""
        return approved.any {
            val entry = it.lowercase().trim()
            entry == normalizedSender || (entry.isNotBlank() && entry == normalizedGroup)
        }
    }

    companion object {
        private const val WHATSAPP_PACKAGE = "com.whatsapp"
        private const val KEY_APPROVED_SENDERS = "approved_senders"
    }
}
