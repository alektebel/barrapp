package com.barrapp

import android.content.Context

object DeviceId {
    fun get(context: Context): String {
        val prefs = context.getSharedPreferences("barrapp", Context.MODE_PRIVATE)
        val existing = prefs.getString("device_id", null)
        if (!existing.isNullOrBlank()) return existing
        val created = java.util.UUID.randomUUID().toString()
        prefs.edit().putString("device_id", created).apply()
        return created
    }

    fun privacyAccepted(context: Context): Boolean =
        context.getSharedPreferences("barrapp", Context.MODE_PRIVATE)
            .getBoolean("privacy_accepted", false)

    fun acceptPrivacy(context: Context) {
        context.getSharedPreferences("barrapp", Context.MODE_PRIVATE)
            .edit()
            .putBoolean("privacy_accepted", true)
            .apply()
    }
}
