package com.barrapp

import com.barrapp.data.MotionSample
import com.barrapp.data.TrimPlan
import com.barrapp.data.TrimSuggestion

/**
 * El núcleo puro de la sugerencia de recorte, probado con puntuaciones
 * sintéticas: caminata de entrada silenciosa, serie ruidosa, salida
 * silenciosa. Sin decodificar vídeo — la parte Android (el muestreo) se
 * prueba en el dispositivo, no aquí.
 */
object TrimPlanTest {

    private var failures = 0
    private var checks = 0

    private fun check(name: String, condition: Boolean, detail: String = "") {
        checks++
        if (!condition) {
            failures++
            println("  FAIL  $name${if (detail.isEmpty()) "" else "  ($detail)"}")
        }
    }

    /** Un clip de 35 s: 0–14 s quieto, 15–21 s la serie, 22–35 s quieto.
     *  Muestras cada 0,5 s, la primera en 0,5 s. */
    private val walkInSetWalkOut: List<MotionSample> = (1..69).map { i ->
        val t = i * 0.5
        MotionSample(t, if (t in 14.5..21.0) 40.0 else 1.0)
    }

    private fun suggest(
        samples: List<MotionSample> = walkInSetWalkOut,
        durationS: Double = 35.0,
    ) = TrimPlan.suggest(samples, durationS)

    private fun suggestionRules() {
        val s = suggest()
        check("a clip with a set suggests a window", s != null)
        if (s == null) return
        // Serie 15–21 s: la ventana con 1 s de aire a cada lado.
        check("window starts about a second before the set",
            Math.abs(s.startS - 14.0) < 0.6, "startS=${s.startS}")
        check("window ends about a second after the set",
            Math.abs(s.endS - 22.0) < 0.6, "endS=${s.endS}")
        check("window is clamped inside the clip",
            s.startS >= 0.0 && s.endS <= 35.0)
        check("duration recorded", Math.abs(s.durationS - 35.0) < 1e-9)
    }

    private fun quietEdgeRules() {
        // Una serie al principio del clip: el aire de entrada no puede
        // llevar la ventana a tiempos negativos.
        val early = (1..20).map { i ->
            val t = i * 0.5
            MotionSample(t, if (t <= 4.0) 40.0 else 1.0)
        }
        val s = suggest(early, 10.0)
        check("early set clamps to 0", s != null && s.startS == 0.0,
            "startS=${s?.startS}")
        // Y al final: endS se sujeta a la duración.
        val late = (1..20).map { i ->
            val t = i * 0.5
            MotionSample(t, if (t >= 9.0) 40.0 else 1.0)
        }
        val s2 = suggest(late, 10.0)
        check("late set clamps to duration", s2 != null && s2.endS == 10.0,
            "endS=${s2?.endS}")
    }

    private fun gapToleranceRules() {
        // La serie con una pausa de 1 s dentro (dos muestras por debajo del
        // umbral): sigue siendo UNA ventana, no dos.
        val withGap = (1..69).map { i ->
            val t = i * 0.5
            val inSet = t in 14.5..17.0 || t in 18.5..21.0
            MotionSample(t, if (inSet) 40.0 else 1.0)
        }
        val s = suggest(withGap)
        check("a pause inside the set does not split the window",
            s != null && Math.abs(s.endS - 22.0) < 0.6, "endS=${s?.endS}")
    }

    private fun noSignalRules() {
        check("an empty sample list suggests nothing",
            suggest(emptyList()) == null)
        val flat = (1..69).map { MotionSample(it * 0.5, 0.0) }
        check("a clip with no motion suggests nothing", suggest(flat) == null)
    }

    private fun loudestRunRules() {
        // Dos tramos por encima del umbral: gana el más largo, no el primero.
        val twoRuns = (1..69).map { i ->
            val t = i * 0.5
            MotionSample(t, when {
                t in 5.0..8.0 -> 40.0     // ruido corto al entrar
                t in 14.5..21.0 -> 40.0   // la serie
                else -> 1.0
            })
        }
        val s = suggest(twoRuns)
        check("the longest loud run wins",
            s != null && Math.abs(s.startS - 14.0) < 0.6, "startS=${s?.startS}")
    }

    private fun shouldTrimRules() {
        // La serie (14–22 s) contra 35 s: recorta.
        check("a 8 s window over a 35 s clip is worth trimming",
            TrimPlan.shouldTrim(suggest(), 35.0))
        // Un clip que ya es casi todo serie: no.
        val allSet = (1..69).map { MotionSample(it * 0.5, 40.0) }
        val s = suggest(allSet)
        check("a window covering most of the clip is not worth trimming",
            !TrimPlan.shouldTrim(s, 35.0))
        check("no suggestion means no trim",
            !TrimPlan.shouldTrim(null, 35.0))
        check("no duration means no trim",
            !TrimPlan.shouldTrim(suggest(), 0.0))
    }

    fun runAll(): Int {
        suggestionRules()
        quietEdgeRules()
        gapToleranceRules()
        noSignalRules()
        loudestRunRules()
        shouldTrimRules()
        println(if (failures == 0) "OK  $checks checks passed"
                else "FAILED  $failures of $checks checks")
        return failures
    }

    @JvmStatic
    fun main(args: Array<String>) {
        if (runAll() > 0) kotlin.system.exitProcess(1)
    }
}

/** The same checks under Gradle's `testDebugUnitTest`. */
class TrimPlanTestSuite {
    @org.junit.Test
    fun everyRuleHolds() {
        org.junit.Assert.assertEquals("trim plan checks failed (see stdout)",
            0, TrimPlanTest.runAll())
    }
}
