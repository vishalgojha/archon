package ai.archon.mobile

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

class GatewaySession(
    private val config: MobileConfig,
    private val dispatcher: InvokeDispatcher,
    private val listener: Listener,
) {
    interface Listener {
        fun onConnected()
        fun onDisconnected(reason: String)
    }

    private val scope = CoroutineScope(Dispatchers.IO)
    private val json = Json { ignoreUnknownKeys = true }
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    @Volatile
    private var socket: WebSocket? = null


    fun connect() {
        if (socket != null) return
        val request = Request.Builder()
            .url(config.gatewayUrl())
            .addHeader("Authorization", "Bearer ${config.apiKey}")
            .build()

        socket = client.newWebSocket(request, SocketListener())
    }

    fun disconnect() {
        socket?.close(1000, "shutdown")
        socket = null
    }

    fun send(jsonPayload: JsonElement) {
        socket?.send(jsonPayload.toString())
    }

    fun sendContextEvent(eventType: String, payload: JsonObject) {
        val message = buildJsonObject {
            put("type", JsonPrimitive(eventType))
            put("payload", payload)
        }
        send(message)
    }

    private inner class SocketListener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            listener.onConnected()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val element = runCatching { json.parseToJsonElement(text) }.getOrNull() ?: return
            val obj = element as? JsonObject ?: return
            val type = obj["type"]?.jsonPrimitive?.contentOrNull ?: return
            if (type != "invoke") return
            val id = obj["id"]?.jsonPrimitive?.contentOrNull ?: return
            val method = obj["method"]?.jsonPrimitive?.contentOrNull ?: return
            val params = obj["params"] as? JsonObject

            scope.launch {
                val result = dispatcher.handleInvoke(method, params)
                val responsePayload = buildJsonObject {
                    put("type", JsonPrimitive("invoke_result"))
                    put("id", JsonPrimitive(id))
                    put("method", JsonPrimitive(method))
                    put("result", result)
                }
                send(responsePayload)
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            socket = null
            listener.onDisconnected("closed: $reason")
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            socket = null
            listener.onDisconnected("failure: ${t.message ?: "unknown"}")
        }
    }
}
