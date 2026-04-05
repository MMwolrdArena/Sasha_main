package com.example.taxidispatcher.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.example.taxidispatcher.contacts.ContactLookup
import com.example.taxidispatcher.data.repository.TicketRepository
import com.example.taxidispatcher.domain.messaging.MessagingManager

class QueueViewModelFactory(
    private val repository: TicketRepository,
    private val messagingManager: MessagingManager,
    private val contactLookup: ContactLookup
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(QueueViewModel::class.java)) {
            @Suppress("UNCHECKED_CAST")
            return QueueViewModel(repository, messagingManager, contactLookup) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class")
    }
}
