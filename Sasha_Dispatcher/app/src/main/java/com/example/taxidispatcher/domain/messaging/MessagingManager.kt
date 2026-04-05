package com.example.taxidispatcher.domain.messaging

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.telephony.SmsManager
import androidx.core.content.ContextCompat

interface MessagingManager {
    fun sendSms(phoneNumber: String, message: String): Result<Unit>
}

class AndroidMessagingManager(
    private val context: Context
) : MessagingManager {
    override fun sendSms(phoneNumber: String, message: String): Result<Unit> {
        if (phoneNumber.isBlank()) {
            return Result.failure(IllegalArgumentException("Invalid phone number"))
        }

        val hasPermission = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.SEND_SMS
        ) == PackageManager.PERMISSION_GRANTED

        if (!hasPermission) {
            return Result.failure(IllegalStateException("SMS permission is not granted"))
        }

        return runCatching {
            SmsManager.getDefault().sendTextMessage(phoneNumber, null, message, null, null)
        }
    }
}
