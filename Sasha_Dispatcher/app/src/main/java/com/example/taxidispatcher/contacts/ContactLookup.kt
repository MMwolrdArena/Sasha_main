package com.example.taxidispatcher.contacts

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.provider.ContactsContract
import androidx.core.content.ContextCompat

interface ContactLookup {
    fun findNameForNumber(number: String): String?
}

class AndroidContactLookup(
    private val context: Context
) : ContactLookup {
    override fun findNameForNumber(number: String): String? {
        val hasPermission = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.READ_CONTACTS
        ) == PackageManager.PERMISSION_GRANTED

        if (!hasPermission || number.isBlank()) return null

        val uri = android.net.Uri.withAppendedPath(
            ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
            android.net.Uri.encode(number)
        )

        context.contentResolver.query(
            uri,
            arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME),
            null,
            null,
            null
        )?.use { cursor ->
            return if (cursor.moveToFirst()) cursor.getString(0) else null
        }

        return null
    }
}
