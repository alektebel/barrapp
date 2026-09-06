package com.barrapp.data

import android.content.Context
import androidx.core.content.edit

/**
 * The signed-in session, on the phone.
 *
 * Only tokens live here - never the password. The access token expires in an
 * hour; the refresh token is what makes the app open signed in tomorrow, so it
 * is the one thing here whose loss actually costs the user something.
 *
 * An empty store is not an error state. It means anonymous, which is a
 * perfectly good way to use barrapp: the device id still identifies the
 * training history, exactly as it did before accounts existed.
 */
object AuthStore {
    private const val PREFS = "barrapp_auth"
    private const val ACCESS = "access_token"
    private const val REFRESH = "refresh_token"
    private const val EXPIRES = "expires_at"
    private const val EMAIL = "email"
    /** Set once a device's anonymous history has been moved onto the account,
     *  so a later sign-in does not try to claim what it already claimed. */
    private const val CLAIMED = "claimed_device"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    data class Session(
        val accessToken: String,
        val refreshToken: String,
        val expiresAt: Long,
        val email: String,
    ) {
        /** A minute of slack: a token that expires while the request is in
         *  flight is the same problem as one that expired a minute ago. */
        val expired: Boolean
            get() = System.currentTimeMillis() > expiresAt - 60_000
    }

    fun session(context: Context): Session? {
        val p = prefs(context)
        val access = p.getString(ACCESS, "").orEmpty()
        val refresh = p.getString(REFRESH, "").orEmpty()
        if (access.isBlank() || refresh.isBlank()) return null
        return Session(access, refresh, p.getLong(EXPIRES, 0L), p.getString(EMAIL, "").orEmpty())
    }

    fun signedIn(context: Context): Boolean = session(context) != null

    fun email(context: Context): String = prefs(context).getString(EMAIL, "").orEmpty()

    fun save(
        context: Context,
        accessToken: String,
        refreshToken: String?,
        expiresIn: Long,
        email: String?,
    ) {
        prefs(context).edit {
            putString(ACCESS, accessToken)
            // A refresh does not reissue the refresh token; the one already
            // stored stays valid, so an absent value must not clear it.
            if (!refreshToken.isNullOrBlank()) putString(REFRESH, refreshToken)
            putLong(EXPIRES, System.currentTimeMillis() + expiresIn * 1000)
            if (!email.isNullOrBlank()) putString(EMAIL, email)
        }
    }

    fun markClaimed(context: Context, deviceId: String) {
        prefs(context).edit { putString(CLAIMED, deviceId) }
    }

    fun alreadyClaimed(context: Context, deviceId: String): Boolean =
        prefs(context).getString(CLAIMED, "") == deviceId

    /** Sign out. The device id is deliberately left alone: it is this phone's
     *  name, not the account's, and clearing it would orphan any anonymous
     *  history that was never claimed. */
    fun clear(context: Context) {
        prefs(context).edit { clear() }
    }
}
