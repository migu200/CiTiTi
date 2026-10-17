package pt.projetoctt.scanner

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {

    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme(
                colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()
            ) {
                ScannerScreen(viewModel)
            }
        }
    }

    // Recebe imagens apenas enquanto a app está visível.
    override fun onStart() {
        super.onStart()
        viewModel.startListening()
    }

    override fun onStop() {
        super.onStop()
        viewModel.stopListening()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ScannerScreen(viewModel: MainViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var showSettings by rememberSaveable { mutableStateOf(!state.hasToken) }
    var confirmClear by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Códigos do Telegram") },
                actions = {
                    IconButton(
                        onClick = { shareText(context, state.results.joinToString("\n") { it.value }) },
                        enabled = state.results.isNotEmpty(),
                    ) { Icon(Icons.Default.Share, contentDescription = "Partilhar todos") }
                    IconButton(
                        onClick = { confirmClear = true },
                        enabled = state.results.isNotEmpty(),
                    ) { Icon(Icons.Default.Delete, contentDescription = "Apagar todos") }
                    IconButton(onClick = { showSettings = true }) {
                        Icon(Icons.Default.Settings, contentDescription = "Definições")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            StatusBar(state)
            when {
                !state.hasToken -> EmptyMessage("Abre as definições (⚙) e indica o token do bot para começar.")
                state.results.isEmpty() -> EmptyMessage(
                    "Ainda não há códigos.\nEnvia para o grupo uma foto com um código no formato " +
                        "AA123456789AA (2 letras, 9 números, 2 letras)."
                )
                else -> LazyColumn(
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(state.results, key = { it.key }) { result ->
                        ResultCard(result, onDelete = { viewModel.delete(result) })
                    }
                }
            }
        }
    }

    if (showSettings) {
        SettingsDialog(
            initialToken = state.botToken,
            initialChat = state.chatFilter,
            onSave = { token, chat ->
                viewModel.saveSettings(token, chat)
                showSettings = false
            },
            onDismiss = { showSettings = false },
        )
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("Apagar todos os códigos?") },
            text = { Text("Esta ação não pode ser anulada.") },
            confirmButton = {
                TextButton(onClick = { viewModel.clearAll(); confirmClear = false }) { Text("Apagar") }
            },
            dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("Cancelar") } },
        )
    }
}

@Composable
private fun StatusBar(state: UiState) {
    if (state.status.isEmpty()) return
    Surface(color = MaterialTheme.colorScheme.secondaryContainer, modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            if (state.listening) {
                CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(8.dp))
            }
            Text(state.status, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun EmptyMessage(text: String) {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(text, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun ResultCard(result: ScanResult, onDelete: () -> Unit) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    val isLink = result.value.startsWith("http://") || result.value.startsWith("https://")

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(start = 16.dp, end = 8.dp, top = 12.dp)) {
            SelectionContainer {
                Text(result.value, style = MaterialTheme.typography.titleMedium, fontFamily = FontFamily.Monospace)
            }
            Text(
                "${result.format} · ${result.chatTitle} · ${result.sender} · ${formatDate(result.date)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
            Row {
                TextButton(onClick = {
                    clipboard.setText(AnnotatedString(result.value))
                    Toast.makeText(context, "Copiado", Toast.LENGTH_SHORT).show()
                }) { Text("Copiar") }
                TextButton(onClick = { shareText(context, result.value) }) { Text("Partilhar") }
                if (isLink) {
                    TextButton(onClick = { openLink(context, result.value) }) { Text("Abrir") }
                }
                Spacer(Modifier.weight(1f))
                TextButton(onClick = onDelete) { Text("Apagar") }
            }
        }
    }
}

@Composable
private fun SettingsDialog(
    initialToken: String,
    initialChat: String,
    onSave: (token: String, chat: String) -> Unit,
    onDismiss: () -> Unit,
) {
    var token by rememberSaveable { mutableStateOf(initialToken) }
    var chat by rememberSaveable { mutableStateOf(initialChat) }
    val chatValid = chat.isEmpty() || chat.toLongOrNull() != null

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Definições") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it.trim() },
                    label = { Text("Token do bot") },
                    placeholder = { Text("123456:ABC-DEF…") },
                    singleLine = true,
                )
                Text("Cria o bot e obtém o token com o @BotFather.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(
                    value = chat,
                    onValueChange = { chat = it.trim() },
                    label = { Text("ID do grupo (opcional)") },
                    placeholder = { Text("-100…") },
                    singleLine = true,
                    isError = !chatValid,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                )
                Text(
                    "Vazio = aceita imagens de todos os grupos onde o bot está. " +
                        "O ID aparece na barra de estado quando chega uma imagem.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        },
        confirmButton = {
            TextButton(enabled = token.isNotBlank() && chatValid, onClick = { onSave(token, chat) }) {
                Text("Guardar")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}

private fun formatDate(epochSeconds: Long): String =
    SimpleDateFormat("dd/MM/yyyy HH:mm", Locale("pt", "PT")).format(Date(epochSeconds * 1000))

private fun shareText(context: Context, text: String) {
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, text)
    }
    context.startActivity(Intent.createChooser(intent, "Partilhar"))
}

private fun openLink(context: Context, url: String) {
    try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    } catch (e: ActivityNotFoundException) {
        Toast.makeText(context, "Nenhuma app para abrir o link", Toast.LENGTH_SHORT).show()
    }
}
