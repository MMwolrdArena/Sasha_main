package com.example.taxidispatcher.data.repository

import com.example.taxidispatcher.data.local.CallerTicketDao
import com.example.taxidispatcher.data.local.CallerTicketEntity
import kotlinx.coroutines.flow.Flow
import java.util.UUID

class TicketRepository(
    private val dao: CallerTicketDao
) {
    fun observeActiveTickets(): Flow<List<CallerTicketEntity>> = dao.observeActiveTickets()

    fun observeArchivedTickets(): Flow<List<CallerTicketEntity>> = dao.observeArchivedTickets()

    suspend fun addTicket(phoneNumber: String, contactName: String?, note: String) {
        val activeTickets = dao.getActiveTickets()
        val now = System.currentTimeMillis()
        dao.insert(
            CallerTicketEntity(
                id = UUID.randomUUID().toString(),
                phoneNumber = phoneNumber,
                contactName = contactName,
                createdAt = now,
                updatedAt = now,
                note = note,
                status = com.example.taxidispatcher.data.model.TicketStatus.WAITING,
                queuePosition = activeTickets.size,
                lastSentMessage = null,
                isArchived = false
            )
        )
    }

    suspend fun updateTicket(ticket: CallerTicketEntity) {
        dao.update(ticket.copy(updatedAt = System.currentTimeMillis()))
    }

    suspend fun archiveTicket(ticket: CallerTicketEntity) {
        dao.update(
            ticket.copy(
                isArchived = true,
                status = com.example.taxidispatcher.data.model.TicketStatus.CLOSED,
                updatedAt = System.currentTimeMillis()
            )
        )
        rebalanceQueuePositions()
    }

    suspend fun rebalanceQueuePositions() {
        val activeTickets = dao.getActiveTickets().sortedBy { it.queuePosition }
        dao.insertAll(
            activeTickets.mapIndexed { index, ticket ->
                ticket.copy(queuePosition = index, updatedAt = System.currentTimeMillis())
            }
        )
    }

    suspend fun currentActiveQueue(): List<CallerTicketEntity> = dao.getActiveTickets().sortedBy { it.queuePosition }
}
