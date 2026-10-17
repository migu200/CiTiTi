package pt.projetoctt.scanner

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class UiState(
    val results: List<ScanResult> = emptyList(),
    val status: String = "",
    val listening: Boolean = false,
    val botToken: String = "",
    val chatFilter: String = "",
) {
    val hasToken get() = botToken.isNotBlank()
}

class MainViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = ScanRepository(app)
    private val resultsLock = Mutex()
    private var pollJob: Job? = null

    private val _state = MutableStateFlow(
        UiState(
            results = repo.load(),
            botToken = repo.botToken,
            chatFilter = repo.chatFilter?.toString().orEmpty(),
        )
    )
    val state: StateFlow<UiState> = _state.asStateFlow()

    /** Começa a receber imagens (chamado quando a app fica visível). */
    fun startListening() {
        if (pollJob?.isActive == true || repo.botToken.isBlank()) return
        val previous = pollJob
        val client = TelegramClient(repo.botToken)

        pollJob = viewModelScope.launch(Dispatchers.IO) {
            previous?.cancelAndJoin() // nunca dois getUpdates em simultâneo
            _state.update { it.copy(listening = true) }
            try {
                setStatus("A ligar ao Telegram…")
                val botName = client.getMe()
                setStatus("Ligado como @$botName. À espera de imagens…")

                while (isActive) {
                    try {
                        val batch = client.getUpdates(repo.updateOffset)
                        for (image in batch.images) processImage(client, image)
                        repo.updateOffset = batch.nextOffset
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        setStatus("Erro: ${e.message}. Nova tentativa em 5 s…")
                        delay(5_000)
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                setStatus("Erro: ${e.message}")
            } finally {
                _state.update { it.copy(listening = false) }
            }
        }
    }

    fun stopListening() {
        pollJob?.cancel()
    }

    fun saveSettings(token: String, chatFilter: String) {
        val tokenChanged = token != repo.botToken
        repo.botToken = token
        repo.chatFilter = chatFilter.toLongOrNull()
        if (tokenChanged) repo.updateOffset = 0
        _state.update {
            it.copy(botToken = token, chatFilter = repo.chatFilter?.toString().orEmpty())
        }
        stopListening()
        startListening()
    }

    fun delete(result: ScanResult) = editResults { list -> list.filterNot { it.key == result.key } }

    fun clearAll() = editResults { emptyList() }

    private suspend fun processImage(client: TelegramClient, image: IncomingImage) {
        val filter = repo.chatFilter
        if (filter != null && filter != image.chatId) return

        val origin = "${image.chatTitle} (ID ${image.chatId})"
        try {
            setStatus("A ler imagem de $origin…")
            val decoded = BarcodeDecoder.decode(client.downloadFile(image.fileId))
            val codes = decoded
                .map { it.copy(value = it.value.replace(Regex("\\s"), "").uppercase()) }
                .filter { TRACKING_CODE.matches(it.value) }
                .distinctBy { it.value }
            if (codes.isEmpty()) {
                setStatus(
                    if (decoded.isEmpty()) "Imagem de $origin sem códigos legíveis."
                    else "Imagem de $origin: ${decoded.size} código(s) ignorado(s) (formato diferente de AA123456789AA)."
                )
                return
            }
            val newResults = codes.map {
                ScanResult(
                    chatId = image.chatId,
                    chatTitle = image.chatTitle,
                    messageId = image.messageId,
                    sender = image.sender,
                    date = image.date,
                    format = it.format,
                    value = it.value,
                )
            }
            resultsLock.withLock {
                val current = _state.value.results
                val existing = current.mapTo(HashSet()) { it.key }
                val merged = newResults.filterNot { it.key in existing } + current
                repo.save(merged)
                _state.update { it.copy(results = merged) }
            }
            setStatus("${codes.size} código(s) lido(s) de $origin.")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            setStatus("Erro ao processar imagem de $origin: ${e.message}")
        }
    }

    private fun editResults(transform: (List<ScanResult>) -> List<ScanResult>) {
        viewModelScope.launch(Dispatchers.IO) {
            resultsLock.withLock {
                val updated = transform(_state.value.results)
                repo.save(updated)
                _state.update { it.copy(results = updated) }
            }
        }
    }

    private fun setStatus(text: String) = _state.update { it.copy(status = text) }

    private companion object {
        /** 2 letras + 9 números + 2 letras (ex.: RR123456789PT). */
        val TRACKING_CODE = Regex("^[A-Z]{2}[0-9]{9}[A-Z]{2}$")
    }
}
