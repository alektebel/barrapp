package com.barrapp.data

/**
 * Where a clip is, as a stable code and a Spanish phrase.
 *
 * The progress bar keys on the code. The server sends `stageCode` and
 * `stageText` beside its English `stage`; an older server sends only the
 * English phrase, which [legacyCode] still understands. The phrases the phone
 * sets itself (sending, queued...) live here too, so every line the athlete
 * reads about a clip's progress is Spanish.
 */
object Stage {
    data class Client(val code: String, val text: String)

    val WAITING = Client("client.waiting", "Esperando para enviarse")
    val RESUMING = Client("client.resuming", "Reanudando la subida")
    val SENDING = Client("client.sending", "Enviando el vídeo")
    val CONNECTING = Client("client.connecting", "Sin conexión: la subida se reanudará sola")
    val QUEUED = Client("client.queued", "En cola en el servidor")
    val MEASURING = Client("client.measuring", "Midiendo")

    fun sending(sent: Int, total: Int) = "${SENDING.text} ($sent/$total partes)"
    fun connecting(safe: Int, total: Int) = "Sin conexión: $safe/$total partes ya están a salvo"

    /** Spanish for a server stage, for servers that predate `stageText`. */
    private val SERVER = mapOf(
        "stage.receiving" to "Recibiendo el vídeo",
        "stage.locating" to "Buscando el ejercicio en el vídeo",
        "stage.opening" to "Abriendo el vídeo",
        "stage.pose" to "Estimando la postura",
        "stage.recognising" to "Reconociendo el movimiento",
        "stage.finding" to "Buscando las repeticiones",
        "stage.relaxed" to "Repasando con criterio más flexible",
        "stage.visual_count" to "Contando a partir de fotogramas",
        "stage.scoring" to "Puntuando las repeticiones",
        "stage.hold" to "Midiendo el mantenimiento",
    )

    /** The code for an English stage phrase from an older server. */
    fun legacyCode(stage: String): String {
        val s = stage.lowercase()
        return when {
            "receiving" in s -> "stage.receiving"
            "locating" in s -> "stage.locating"
            "opening" in s -> "stage.opening"
            "pose" in s -> "stage.pose"
            "recognising" in s -> "stage.recognising"
            "relaxed" in s -> "stage.relaxed"
            "counting from" in s -> "stage.visual_count"
            "finding" in s -> "stage.finding"
            "scoring" in s -> "stage.scoring"
            "hold" in s -> "stage.hold"
            else -> ""
        }
    }

    /** Which of the four steps the record screen shows is active. */
    fun progressIndex(code: String, legacyStage: String): Int {
        val c = code.ifBlank { legacyCode(legacyStage) }
        return when (c) {
            "stage.locating", "stage.pose", "stage.recognising" -> 1
            "stage.finding", "stage.scoring", "stage.relaxed", "stage.visual_count" -> 3
            else -> 2
        }
    }

    fun code(job: Job): String = job.stageCode.ifBlank { legacyCode(job.stage) }

    /** What the list shows for a job on the server. */
    fun display(job: Job): String = job.stageText.ifBlank {
        SERVER[legacyCode(job.stage)] ?: when {
            job.stage.isNotBlank() -> job.stage
            job.status == "queued" -> QUEUED.text
            else -> MEASURING.text
        }
    }
}
