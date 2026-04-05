package com.example.taxidispatcher.ui.history

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.taxidispatcher.data.local.CallerTicketEntity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun HistoryScreen(archivedTickets: List<CallerTicketEntity>) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        items(archivedTickets, key = { it.id }) { ticket ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(ticket.contactName ?: ticket.phoneNumber, style = MaterialTheme.typography.titleMedium)
                    if (!ticket.contactName.isNullOrBlank()) {
                        Text(ticket.phoneNumber)
                    }
                    Text("Status: ${ticket.status}")
                    Text("Note: ${ticket.note.ifBlank { "-" }}")
                    Text(
                        text = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date(ticket.updatedAt)),
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
    }
}
