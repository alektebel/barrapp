package com.barrapp.data

import okhttp3.Dns
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.dnsoverhttps.DnsOverHttps
import java.net.InetAddress
import java.net.UnknownHostException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/**
 * Resolve a host through the system first, then each fallback in order, then
 * the last address that worked for it.
 *
 * Exists because a tester's phone could not resolve the API host while the API
 * was up (2026-10-11): the resolver is the one link the app does not control -
 * a carrier's, a "private DNS" filter, a captive network. Every failure is kept,
 * so when nothing works the error names each resolver and why.
 */
class FallbackDns(
    private val system: Dns,
    private val fallbacks: List<Dns>,
) : Dns {
    private val lastGood = ConcurrentHashMap<String, List<InetAddress>>()

    override fun lookup(hostname: String): List<InetAddress> {
        val failures = mutableListOf<String>()
        for ((i, dns) in (listOf(system) + fallbacks).withIndex()) {
            try {
                val found = dns.lookup(hostname)
                if (found.isNotEmpty()) {
                    lastGood[hostname] = found
                    return found
                }
                failures += "#$i: empty answer"
            } catch (e: Exception) {
                failures += "#$i: ${e.message ?: e.javaClass.simpleName}"
            }
        }
        lastGood[hostname]?.let { return it }
        throw UnknownHostException("$hostname: ${failures.joinToString("; ")}")
    }

    companion object {
        /**
         * System, then Cloudflare and Google over HTTPS. Each DoH endpoint is
         * reached by its fixed IPs, so the fallback does not itself need the
         * resolver that just failed.
         */
        fun standard(): FallbackDns {
            val bootstrap = OkHttpClient.Builder()
                .connectTimeout(5, TimeUnit.SECONDS)
                .readTimeout(5, TimeUnit.SECONDS)
                .build()
            fun doh(url: String, vararg ips: String) = DnsOverHttps.Builder()
                .client(bootstrap)
                .url(url.toHttpUrl())
                .bootstrapDnsHosts(ips.map { InetAddress.getByName(it) })
                .includeIPv6(false)
                .build()
            return FallbackDns(
                Dns.SYSTEM,
                listOf(
                    doh("https://cloudflare-dns.com/dns-query", "1.1.1.1", "1.0.0.1"),
                    doh("https://dns.google/dns-query", "8.8.8.8", "8.8.4.4"),
                ),
            )
        }
    }
}
