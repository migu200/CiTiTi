package pt.projetoctt.scanner

import android.graphics.BitmapFactory
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import kotlinx.coroutines.tasks.await

data class DecodedCode(val format: String, val value: String)

/** Lê códigos de barras e QR codes de uma imagem, no próprio telemóvel (ML Kit). */
object BarcodeDecoder {

    private const val MAX_SIDE = 4096

    private val scanner by lazy {
        BarcodeScanning.getClient(
            BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_ALL_FORMATS)
                .build()
        )
    }

    suspend fun decode(bytes: ByteArray): List<DecodedCode> {
        // Reduz imagens enormes para não esgotar a memória.
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > MAX_SIDE) sample *= 2

        val bitmap = BitmapFactory.decodeByteArray(
            bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample }
        ) ?: return emptyList()

        try {
            return scanner.process(InputImage.fromBitmap(bitmap, 0)).await()
                .mapNotNull { code ->
                    val value = code.rawValue ?: code.displayValue ?: return@mapNotNull null
                    DecodedCode(formatName(code.format), value)
                }
                .distinctBy { it.value }
        } finally {
            bitmap.recycle()
        }
    }

    private fun formatName(format: Int) = when (format) {
        Barcode.FORMAT_QR_CODE -> "QR Code"
        Barcode.FORMAT_DATA_MATRIX -> "Data Matrix"
        Barcode.FORMAT_PDF417 -> "PDF417"
        Barcode.FORMAT_AZTEC -> "Aztec"
        Barcode.FORMAT_CODE_128 -> "Code 128"
        Barcode.FORMAT_CODE_39 -> "Code 39"
        Barcode.FORMAT_CODE_93 -> "Code 93"
        Barcode.FORMAT_CODABAR -> "Codabar"
        Barcode.FORMAT_EAN_13 -> "EAN-13"
        Barcode.FORMAT_EAN_8 -> "EAN-8"
        Barcode.FORMAT_ITF -> "ITF"
        Barcode.FORMAT_UPC_A -> "UPC-A"
        Barcode.FORMAT_UPC_E -> "UPC-E"
        else -> "Código"
    }
}
