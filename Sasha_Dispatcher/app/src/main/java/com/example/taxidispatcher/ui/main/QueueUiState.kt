package com.example.taxidispatcher.ui.main

import com.example.taxidispatcher.data.local.CallerTicketEntity

data class QueueUiState(
    val activeTickets: List<CallerTicketEntity> = emptyList(),
    val archivedTickets: List<CallerTicketEntity> = emptyList(),
    val toastMessage: String? = null
)
