package com.example.taxidispatcher.domain.messaging

import com.example.taxidispatcher.domain.queue.QuickAction

object MessageTemplates {
    private val directTemplates = mapOf(
        QuickAction.ON_MY_WAY to "Taxi is on the way.",
        QuickAction.ETA_8 to "Taxi can be there in about 8 minutes.",
        QuickAction.ETA_5 to "Taxi can be there in about 5 minutes.",
        QuickAction.ETA_1 to "Taxi can be there in about 1 minute.",
        QuickAction.ARRIVED to "Taxi has arrived."
    )

    fun directMessage(action: QuickAction): String = directTemplates.getValue(action)

    fun queueMessage(callsAhead: Int): String {
        val numberText = when (callsAhead) {
            1 -> "One"
            2 -> "Two"
            3 -> "Three"
            4 -> "Four"
            5 -> "Five"
            else -> callsAhead.toString()
        }
        return "Taxi can ride here. $numberText call${if (callsAhead == 1) "" else "s"} ahead of you."
    }
}
