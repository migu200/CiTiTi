package pt.projetoctt.scanner

import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Imagem recebida numa conversa onde o bot está presente. */
data class IncomingImage(
    val chatId: Long,
    val chatTitle: String,
    val messageId: Long,
    val sender: String,
    val date: Long,
    val fileId: String,
)

data class UpdateBatch(val images: List<IncomingImage>, val nextOffset: Long)

/** Cliente mínimo da Telegram Bot API (getMe, getUpdates, getFile). */
class TelegramClient(token: String) {

    private val apiBase = "https://api.telegram.org/bot$token"
    private val fileBase = "https://api.telegram.org/file/bot$token"

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(LONG_POLL_SECONDS + 15L, TimeUnit.SECONDS)
        .build()

    /** Devolve o username do bot (serve também para validar o token). */
    suspend fun getMe(): String =
        call("getMe").getJSONObject("result").optString("username", "bot")

    /** Long polling: espera até [LONG_POLL_SECONDS] por novas mensagens. */
    suspend fun getUpdates(offset: Long): UpdateBatch {
        val result = call(
            "getUpdates",
            "offset" to offset.toString(),
            "timeout" to LONG_POLL_SECONDS.toString(),
            "allowed_updates" to JSONArray(listOf("message", "channel_post")).toString(),
        ).getJSONArray("result")

        var nextOffset = offset
        val images = mutableListOf<IncomingImage>()
        for (i in 0 until result.length()) {
            val update = result.getJSONObject(i)
            nextOffset = maxOf(nextOffset, update.getLong("update_id") + 1)
            val message = update.optJSONObject("message")
                ?: update.optJSONObject("channel_post")
                ?: continue
            parseImage(message)?.let(images::add)
        }
        return UpdateBatch(images, nextOffset)
    }

    suspend fun downloadFile(fileId: String): ByteArray {
        val path = call("getFile", "file_id" to fileId)
            .getJSONObject("result").getString("file_path")
        val response = http.newCall(Request.Builder().url("$fileBase/$path").build()).await()
        response.use {
            if (!it.isSuccessful) throw IOException("Falha ao descarregar imagem (HTTP ${it.code})")
            return it.body?.bytes() ?: throw IOException("Imagem vazia")
        }
    }

    private fun parseImage(message: JSONObject): IncomingImage? {
        // Foto comprimida: o Telegram envia vários tamanhos, o último é o maior.
        val photos = message.optJSONArray("photo")
        val fileId = if (photos != null && photos.length() > 0) {
            photos.getJSONObject(photos.length() - 1).getString("file_id")
        } else {
            // Imagem enviada como ficheiro (sem compressão) — melhor qualidade para códigos.
            val doc = message.optJSONObject("document") ?: return null
            if (!doc.optString("mime_type").startsWith("image/")) return null
            doc.getString("file_id")
        }

        val chat = message.getJSONObject("chat")
        val chatTitle = chat.optString("title").ifEmpty {
            listOf(chat.optString("first_name"), chat.optString("last_name"))
                .filter { it.isNotEmpty() }.joinToString(" ").ifEmpty { "Conversa privada" }
        }

        val from = message.optJSONObject("from")
        val sender = when {
            from != null -> listOf(from.optString("first_name"), from.optString("last_name"))
                .filter { it.isNotEmpty() }.joinToString(" ")
                .ifEmpty { from.optString("username") }
            else -> message.optJSONObject("sender_chat")?.optString("title") ?: chatTitle
        }

        return IncomingImage(
            chatId = chat.getLong("id"),
            chatTitle = chatTitle,
            messageId = message.getLong("message_id"),
            sender = sender,
            date = message.getLong("date"),
            fileId = fileId,
        )
    }

    private suspend fun call(method: String, vararg params: Pair<String, String>): JSONObject {
        val url = "$apiBase/$method".toHttpUrl().newBuilder().apply {
            params.forEach { (k, v) -> addQueryParameter(k, v) }
        }.build()
        val body = http.newCall(Request.Builder().url(url).build()).await().use { it.body?.string() }
            ?: throw IOException("Resposta vazia do Telegram")
        val json = JSONObject(body)
        if (!json.optBoolean("ok")) {
            val description = json.optString("description", "erro desconhecido")
            throw IOException(
                when (json.optInt("error_code")) {
                    401, 404 -> "Token do bot inválido"
                    409 -> "Conflito: $description (há outro programa ou webhook a usar este bot)"
                    else -> description
                }
            )
        }
        return json
    }

    companion object {
        const val LONG_POLL_SECONDS = 25
    }
}

/** Torna um pedido OkHttp cancelável a partir de uma coroutine. */
private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    cont.invokeOnCancellation { cancel() }
    enqueue(object : Callback {
        override fun onResponse(call: Call, response: Response) {
            cont.resume(response) { _ -> response.close() }
        }

        override fun onFailure(call: Call, e: IOException) {
            if (!cont.isCancelled) cont.resumeWithException(e)
        }
    })
}
