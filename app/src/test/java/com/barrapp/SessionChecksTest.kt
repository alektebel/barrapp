package com.barrapp

import com.barrapp.ui.CheckLine
import com.barrapp.ui.noChecksPossible
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class SessionChecksTest {
    @Test fun noCheckMadeIsNotAnAllClear() {
        assertNotNull(noChecksPossible(listOf(CheckLine("a", 0, 0, 3), CheckLine("b", 0, 0, 3))))
    }

    @Test fun someCheckMadeKeepsTheCues() {
        assertNull(noChecksPossible(listOf(CheckLine("a", 0, 2, 1), CheckLine("b", 0, 0, 3))))
        assertNull(noChecksPossible(emptyList()))
    }
}
