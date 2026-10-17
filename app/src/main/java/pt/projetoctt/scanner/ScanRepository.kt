package pt.projetoctt.scanner

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

data class ScanResult(
    val chatId: Long,
    val chatTitle: String,
    val messageId: Long,
    val sender: String,
    val date: Long,
    val format: String,
    val value: String,
) {
    val key get() = "${chatId}_${messageId}_$value"
}

/** Guarda as definições e os códigos lidos no armazenamento interno da app. */
class ScanRepository(context: Context) {

    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private val file = File(context.filesDir, "scans.json")

    var botToken: String
        get() = prefs.getString(KEY_TOKEN, "").orEmpty()
        set(value) = prefs.edit().putString(KEY_TOKEN, value).apply()

    /** Se definido, só aceita imagens deste grupo. */
    var chatFilter: Long?
        get() = if (prefs.contains(KEY_CHAT)) prefs.getLong(KEY_CHAT, 0) else null
        set(value) = prefs.edit().apply {
            if (value == null) remove(KEY_CHAT) else putLong(KEY_CHAT, value)
        }.apply()

    /** Próximo update_id a pedir ao Telegram (evita reprocessar mensagens). */
    var updateOffset: Long
        get() = prefs.getLong(KEY_OFFSET, 0)
        set(value) = prefs.edit().putLong(KEY_OFFSET, value).apply()

    @Synchronized
    fun load(): List<ScanResult> {
        if (!file.exists()) return emptyList()
        return try {
            val arr = JSONArray(file.readText())
            List(arr.length()) { i ->
                val o = arr.getJSONObject(i)
                ScanResult(
                    chatId = o.getLong("chatId"),
                    chatTitle = o.getString("chatTitle"),
                    messageId = o.getLong("messageId"),
                    sender = o.getString("sender"),
                    date = o.getLong("date"),
                    format = o.getString("format"),
                    value = o.getString("value"),
                )
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    @Synchronized
    fun save(results: List<ScanResult>) {
        val arr = JSONArray()
        results.forEach { r ->
            arr.put(
                JSONObject()
                    .put("chatId", r.chatId)
                    .put("chatTitle", r.chatTitle)
                    .put("messageId", r.messageId)
                    .put("sender", r.sender)
                    .put("date", r.date)
                    .put("format", r.format)
                    .put("value", r.value)
            )
        }
        val tmp = File(file.parentFile, "${file.name}.tmp")
        tmp.writeText(arr.toString())
        tmp.renameTo(file)
    }

    private companion object {
        const val KEY_TOKEN = "bot_token"
        const val KEY_CHAT = "chat_filter"
        const val KEY_OFFSET = "update_offset"
    }
}
