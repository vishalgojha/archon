package ai.archon.mobile

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.ViewFlipper
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request

class OnboardingActivity : ComponentActivity() {
    private lateinit var flipper: ViewFlipper
    private lateinit var backendInput: EditText
    private lateinit var apiKeyInput: EditText
    private lateinit var statusText: TextView
    private val scope = CoroutineScope(Dispatchers.Main)

    private val requestNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
    private val requestContacts = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
    private val requestCalendar = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
    private val requestLocation = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_onboarding)

        flipper = findViewById(R.id.onboarding_flipper)
        backendInput = findViewById(R.id.input_backend_url)
        apiKeyInput = findViewById(R.id.input_api_key)
        statusText = findViewById(R.id.text_test_status)

        backendInput.setText(BuildConfig.DEFAULT_BACKEND_URL)

        findViewById<Button>(R.id.btn_connect_next).setOnClickListener {
            val config = MobileConfig(this)
            val backend = backendInput.text.toString().ifBlank { BuildConfig.DEFAULT_BACKEND_URL }
            config.setBackendUrl(backend)
            config.setApiKey(apiKeyInput.text.toString())
            flipper.showNext()
        }

        findViewById<Button>(R.id.btn_permissions_back).setOnClickListener { flipper.showPrevious() }
        findViewById<Button>(R.id.btn_permissions_next).setOnClickListener { flipper.showNext() }
        findViewById<Button>(R.id.btn_test_back).setOnClickListener { flipper.showPrevious() }
        findViewById<Button>(R.id.btn_test_next).setOnClickListener { flipper.showNext() }
        findViewById<Button>(R.id.btn_done_back).setOnClickListener { flipper.showPrevious() }

        findViewById<Button>(R.id.btn_enable_notification_listener).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }

        findViewById<Button>(R.id.btn_request_notifications).setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        findViewById<Button>(R.id.btn_request_contacts).setOnClickListener {
            requestContacts.launch(Manifest.permission.READ_CONTACTS)
        }

        findViewById<Button>(R.id.btn_request_calendar).setOnClickListener {
            requestCalendar.launch(Manifest.permission.READ_CALENDAR)
        }

        findViewById<Button>(R.id.btn_request_location).setOnClickListener {
            requestLocation.launch(Manifest.permission.ACCESS_COARSE_LOCATION)
        }

        findViewById<Button>(R.id.btn_request_battery).setOnClickListener {
            requestIgnoreBatteryOptimizations()
        }

        findViewById<Button>(R.id.btn_test_connection).setOnClickListener {
            testConnection()
        }

        findViewById<Button>(R.id.btn_done_start).setOnClickListener {
            val intent = Intent(this, ArchonForegroundService::class.java)
            ContextCompat.startForegroundService(this, intent)
            finish()
        }

        requestIgnoreBatteryOptimizations()
    }

    private fun requestIgnoreBatteryOptimizations() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        val packageName = packageName
        if (!pm.isIgnoringBatteryOptimizations(packageName)) {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.data = Uri.parse("package:$packageName")
            startActivity(intent)
        }
    }

    private fun testConnection() {
        val config = MobileConfig(this)
        val backendUrl = config.backendUrl.trimEnd('/')
        statusText.text = "Status: testing..."

        scope.launch(Dispatchers.IO) {
            val client = OkHttpClient()
            val request = Request.Builder()
                .url("$backendUrl/health")
                .addHeader("Authorization", "Bearer ${config.apiKey}")
                .build()
            val success = runCatching { client.newCall(request).execute().use { it.isSuccessful } }.getOrDefault(false)
            val text = if (success) "Status: connected" else "Status: failed"
            launch(Dispatchers.Main) {
                statusText.text = text
            }
        }
    }
}
