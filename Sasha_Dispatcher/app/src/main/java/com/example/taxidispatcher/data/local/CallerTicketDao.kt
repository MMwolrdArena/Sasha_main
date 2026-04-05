package com.example.taxidispatcher.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface CallerTicketDao {
    @Query("SELECT * FROM caller_tickets WHERE isArchived = 0 ORDER BY queuePosition ASC, createdAt ASC")
    fun observeActiveTickets(): Flow<List<CallerTicketEntity>>

    @Query("SELECT * FROM caller_tickets WHERE isArchived = 1 ORDER BY updatedAt DESC")
    fun observeArchivedTickets(): Flow<List<CallerTicketEntity>>

    @Query("SELECT * FROM caller_tickets WHERE isArchived = 0 ORDER BY queuePosition ASC, createdAt ASC")
    suspend fun getActiveTickets(): List<CallerTicketEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(ticket: CallerTicketEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(tickets: List<CallerTicketEntity>)

    @Update
    suspend fun update(ticket: CallerTicketEntity)
}
