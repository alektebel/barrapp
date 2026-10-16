package com.barrapp.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class CountDisplayTest {
    @Test fun `vision counts are described as estimates from frames`() {
        assertEquals("5 repeticiones estimadas a partir de fotogramas", countSummary("vision", 5, 0))
    }

    @Test fun `unmeasured is distinct from a measured zero`() {
        assertEquals("Recuento de repeticiones no disponible", countSummary("unmeasured", 0, 0))
    }

    @Test fun `geometric count retains its candidate context`() {
        assertEquals("0 repeticiones medidas de 2 encontradas", countSummary("geometry", 0, 2))
    }

    @Test fun `holds are not labeled as repetition counts`() {
        assertEquals("2 intentos de mantenimiento medidos", countSummary("hold", 2, 2))
    }
}
