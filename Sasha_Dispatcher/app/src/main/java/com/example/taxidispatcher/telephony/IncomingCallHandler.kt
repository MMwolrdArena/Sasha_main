package com.example.taxidispatcher.telephony

/**
 * Hook point for future real incoming-call integration.
 */
interface IncomingCallHandler {
    fun startListening()
    fun stopListening()
}

class StubIncomingCallHandler : IncomingCallHandler {
    override fun startListening() = Unit
    override fun stopListening() = Unit
}
