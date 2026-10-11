package com.barrapp

import com.barrapp.data.FallbackDns
import okhttp3.Dns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.net.InetAddress
import java.net.UnknownHostException

/**
 * 2026-10-11: a tester's phone could not resolve the API host
 * (`*.execute-api.eu-west-1.amazonaws.com`) - "unable to resolve host" - while
 * the API itself was up and answering. A phone's resolver (the carrier's, a
 * "private DNS" filter, a captive network) is the one link in the chain the app
 * does not control, so the client tries the system first, then DNS-over-HTTPS,
 * then the last address that worked for that host.
 */
class FallbackDnsTest {
    private val ip = InetAddress.getByAddress("api.test", byteArrayOf(10, 0, 0, 1))
    private val ip2 = InetAddress.getByAddress("api.test", byteArrayOf(10, 0, 0, 2))

    private class Fake(val name: String, var answer: List<InetAddress>? = null) : Dns {
        var calls = 0
        override fun lookup(hostname: String): List<InetAddress> {
            calls++
            return answer ?: throw UnknownHostException("$name cannot resolve $hostname")
        }
    }

    @Test
    fun `the system resolver is used when it works`() {
        val system = Fake("system", listOf(ip))
        val doh = Fake("doh", listOf(ip2))
        assertEquals(listOf(ip), FallbackDns(system, listOf(doh)).lookup("api.test"))
        assertEquals(0, doh.calls)
    }

    @Test
    fun `a failed system lookup falls through to the next resolver`() {
        val dns = FallbackDns(Fake("system"), listOf(Fake("cloudflare"), Fake("google", listOf(ip2))))
        assertEquals(listOf(ip2), dns.lookup("api.test"))
    }

    @Test
    fun `an empty answer counts as a failure`() {
        val dns = FallbackDns(Fake("system", emptyList()), listOf(Fake("doh", listOf(ip2))))
        assertEquals(listOf(ip2), dns.lookup("api.test"))
    }

    @Test
    fun `the last good address is used when every resolver fails`() {
        val system = Fake("system", listOf(ip))
        val dns = FallbackDns(system, listOf(Fake("doh")))
        dns.lookup("api.test")
        system.answer = null
        assertEquals(listOf(ip), dns.lookup("api.test"))
    }

    @Test
    fun `with nothing to fall back on the error names every resolver`() {
        val dns = FallbackDns(Fake("system"), listOf(Fake("cloudflare"), Fake("google")))
        try {
            dns.lookup("api.test")
            fail("expected UnknownHostException")
        } catch (e: UnknownHostException) {
            val msg = e.message.orEmpty()
            assertTrue(msg, msg.contains("system") && msg.contains("cloudflare") && msg.contains("google"))
        }
    }

    @Test
    fun `a resolver that throws something else does not stop the chain`() {
        val broken = object : Dns {
            override fun lookup(hostname: String): List<InetAddress> = throw IllegalStateException("boom")
        }
        assertEquals(listOf(ip2), FallbackDns(broken, listOf(Fake("doh", listOf(ip2)))).lookup("api.test"))
    }
}
