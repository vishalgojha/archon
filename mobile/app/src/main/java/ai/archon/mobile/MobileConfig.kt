package ai.archon.mobile

import android.content.Context

class MobileConfig(private val context: Context) {
    private val prefs = SecurePrefs.get(context)

    val backendUrl: String
        get() = prefs.getString(KEY_BACKEND_URL, BuildConfig.DEFAULT_BACKEND_URL) ?: BuildConfig.DEFAULT_BACKEND_URL

    val apiKey: String
        get() = prefs.getString(KEY_API_KEY, BuildConfig.ARCHON_API_KEY) ?: BuildConfig.ARCHON_API_KEY

    fun gatewayUrl(): String {
        val base = backendUrl.trimEnd('/')
        val wsScheme = if (base.startsWith("https")) "wss" else "ws"
        val host = base.removePrefix("http://").removePrefix("https://")
        return "$wsScheme://$host/v1/mobile/gateway"
    }

    fun setBackendUrl(value: String) {
        prefs.edit().putString(KEY_BACKEND_URL, value).apply()
    }

    fun setApiKey(value: String) {
        prefs.edit().putString(KEY_API_KEY, value).apply()
    }

    companion object {
        private const val KEY_BACKEND_URL = "backend_url"
        private const val KEY_API_KEY = "api_key"
    }
}
