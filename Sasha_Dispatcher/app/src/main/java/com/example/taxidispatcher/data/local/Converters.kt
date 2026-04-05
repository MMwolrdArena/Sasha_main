package com.example.taxidispatcher.data.local

import androidx.room.TypeConverter
import com.example.taxidispatcher.data.model.TicketStatus

class Converters {
    @TypeConverter
    fun fromStatus(status: TicketStatus): String = status.name

    @TypeConverter
    fun toStatus(value: String): TicketStatus = TicketStatus.valueOf(value)
}
