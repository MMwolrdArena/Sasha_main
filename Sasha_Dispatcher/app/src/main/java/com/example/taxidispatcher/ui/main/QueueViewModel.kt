package com.example.taxidispatcher.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.taxidispatcher.contacts.ContactLookup
import com.example.taxidispatcher.data.local.CallerTicketEntity
import com.example.taxidispatcher.data.model.TicketStatus
import com.example.taxidispatcher.data.repository.TicketRepository
import com.example.taxidispatcher.domain.messaging.MessageTemplates
import com.example.taxidispatcher.domain.messaging.MessagingManager
import com.example.taxidispatcher.domain.queue.QuickAction
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class QueueViewModel(
    private val repository: TicketRepository,
    private val messagingManager: MessagingManager,
    private val contactLookup: ContactLookup
) : ViewModel() {

    private val _uiState = MutableStateFlow(QueueUiState())
    val uiState: StateFlow<QueueUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            combine(
                repository.observeActiveTickets(),
                repository.observeArchivedTickets()
            ) { active, archived ->
                QueueUiState(activeTickets = active, archivedTickets = archived)
            }.collect { state -> _uiState.value = state }
        }
    }

    fun addTestCaller(phoneNumber: String, name: String?, note: String?) {
        if (phoneNumber.isBlank()) {
            showToast("Phone number is required")
            return
        }
        viewModelScope.launch {
            val resolvedName = name?.takeIf { it.isNotBlank() } ?: contactLookup.findNameForNumber(phoneNumber)
            repository.addTicket(phoneNumber, resolvedName, note.orEmpty())
        }
    }

    fun updateNote(ticket: CallerTicketEntity, note: String) {
        viewModelScope.launch {
            repository.updateTicket(ticket.copy(note = note, updatedAt = System.currentTimeMillis()))
        }
    }

    fun closeTicket(ticket: CallerTicketEntity) {
        viewModelScope.launch {
            repository.archiveTicket(ticket)
            showToast("Caller archived")
        }
    }

    fun clearToast() {
        _uiState.update { it.copy(toastMessage = null) }
    }

    fun handleQuickAction(ticketId: String, action: QuickAction) {
        viewModelScope.launch {
            val queue = repository.currentActiveQueue()
            val targetIndex = queue.indexOfFirst { it.id == ticketId }
            if (targetIndex < 0) {
                showToast("Caller not found")
                return@launch
            }

            val target = queue[targetIndex]
            val directMessage = MessageTemplates.directMessage(action)
            val directStatus = action.toStatus()

            val directResult = messagingManager.sendSms(target.phoneNumber, directMessage)
            if (directResult.isFailure) {
                showToast(directResult.exceptionOrNull()?.message ?: "Unable to send SMS")
            }

            repository.updateTicket(
                target.copy(
                    status = directStatus,
                    lastSentMessage = directMessage,
                    updatedAt = System.currentTimeMillis()
                )
            )

            if (action.shouldTriggerQueueUpdate()) {
                queue.drop(targetIndex + 1).forEachIndexed { offset, ticket ->
                    val aheadCount = offset + 1
                    val queueMessage = MessageTemplates.queueMessage(aheadCount)
                    val result = messagingManager.sendSms(ticket.phoneNumber, queueMessage)
                    if (result.isFailure) {
                        showToast("Queue message failed for ${ticket.phoneNumber}")
                    }
                    repository.updateTicket(
                        ticket.copy(
                            status = TicketStatus.WAITING,
                            lastSentMessage = queueMessage,
                            updatedAt = System.currentTimeMillis()
                        )
                    )
                }
            }

            if (action == QuickAction.ARRIVED) {
                repository.archiveTicket(target)
            } else {
                repository.rebalanceQueuePositions()
            }
        }
    }

    private fun QuickAction.toStatus(): TicketStatus = when (this) {
        QuickAction.ON_MY_WAY -> TicketStatus.ON_MY_WAY
        QuickAction.ETA_8 -> TicketStatus.ETA_8
        QuickAction.ETA_5 -> TicketStatus.ETA_5
        QuickAction.ETA_1 -> TicketStatus.ETA_1
        QuickAction.ARRIVED -> TicketStatus.ARRIVED
    }

    private fun QuickAction.shouldTriggerQueueUpdate(): Boolean = when (this) {
        QuickAction.ON_MY_WAY,
        QuickAction.ETA_8,
        QuickAction.ETA_5,
        QuickAction.ETA_1,
        QuickAction.ARRIVED -> true
    }

    private fun showToast(message: String) {
        _uiState.update { it.copy(toastMessage = message) }
    }
}
