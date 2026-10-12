package com.barrapp.ui.tracker

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.RangeSlider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.barrapp.data.Work
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.mono

/**
 * La ventana de recorte, ANTES de subir.
 *
 * El teléfono propone dónde está la serie (los tiradores ya vienen colocados
 * sobre la ventana sugerida); el atleta los ajusta — grueso vale, pasos de
 * 0,1 s — y confirma. Lo que sale por el cable es exactamente lo que aquí se
 * ve: el servidor mide el fichero que recibe, así que ningún número medido
 * cambia por recortar. Cancelar sube el clip entero, como siempre.
 */
@Composable
fun TrimScreen(
    work: Work,
    onWindow: (Double, Double) -> Unit,
    onConfirm: () -> Unit,
    onDiscard: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val duration = work.clipDurationS.coerceAtLeast(work.trimEndS).coerceAtLeast(0.1)
    // Estado local mientras se arrastra; cada paro escribe en el work.
    var start by remember(work.id) { mutableStateOf(work.trimStartS) }
    var end by remember(work.id) { mutableStateOf(work.trimEndS) }

    Column(
        modifier.fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(bottom = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(20.dp))
        Eyebrow("Antes de subir")
        Spacer(Modifier.height(6.dp))
        Text("Recorta la serie", style = T.pageTitle)
        Spacer(Modifier.height(8.dp))
        Text(
            "Barra encontró movimiento entre %.1f s y %.1f s. Ajusta los " +
                "tiros si empezaste antes o terminaste después; solo lo " +
                "recortado se sube."
                .format(work.trimStartS, work.trimEndS),
            style = T.bodyS,
            modifier = Modifier.padding(horizontal = 8.dp),
        )
        Spacer(Modifier.height(28.dp))

        TkCard {
            Eyebrow("La ventana")
            Spacer(Modifier.height(16.dp))
            RangeSlider(
                value = start.toFloat()..end.toFloat(),
                onValueChange = { r ->
                    // Pasos de 0,1 s: grueso vale, y el número que se lee es
                    // el número que viaja.
                    val s = (r.start * 10).toInt() / 10.0
                    val e = (r.endInclusive * 10).toInt() / 10.0
                    if (e - s >= 1.0) {   // una serie de menos de 1 s no es una serie
                        start = s; end = e
                        onWindow(s, e)
                    }
                },
                valueRange = 0f..duration.toFloat(),
                colors = SliderDefaults.colors(
                    thumbColor = Tk.primary,
                    activeTrackColor = Tk.primary,
                    inactiveTrackColor = Tk.border,
                ),
            )
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("%.1f s".format(start), style = mono(12))
                Text("%.1f s de %.0f".format(end - start, duration),
                    style = mono(12, color = Tk.primaryLight))
                Text("%.1f s".format(end), style = mono(12))
            }
            Spacer(Modifier.height(4.dp))
            Text(
                if (end - start < duration * 0.8)
                    "Se sube el %.0f%% del clip".format(
                        (end - start) / duration * 100)
                else
                    "La ventana cubre casi todo el clip; se sube casi entero",
                style = T.bodyS,
            )
        }

        Spacer(Modifier.height(20.dp))
        TkPrimaryButton("Recortar y subir", onConfirm)
        Spacer(Modifier.height(10.dp))
        TkSecondaryButton("Subir el clip entero", onDiscard)
    }
}
