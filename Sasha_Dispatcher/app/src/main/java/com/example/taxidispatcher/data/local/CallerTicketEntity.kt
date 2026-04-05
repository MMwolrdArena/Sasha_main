package com.example.taxidispatcher.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey
import com.example.taxidispatcher.data.model.TicketStatus

@Entity(tableName = "caller_tickets")
data class CallerTicketEntity(
    @PrimaryKey val id: String,
    val phoneNumber: String,
    val contactName: String?,
    val createdAt: Long,
    val updatedAt: Long,
    val note: String,
    val status: TicketStatus,
    val queuePosition: Int,
    val lastSentMessage: String?,
    val isArchived: Boolean
)
