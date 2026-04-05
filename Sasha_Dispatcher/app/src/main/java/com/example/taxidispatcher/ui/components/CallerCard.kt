package com.example.taxidispatcher.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Close
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.example.taxidispatcher.data.local.CallerTicketEntity
import com.example.taxidispatcher.domain.queue.QuickAction
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun CallerCard(
    ticket: CallerTicketEntity,
    onCallTap: (String) -> Unit,
    onCloseTap: () -> Unit,
    onNoteChange: (String) -> Unit,
    onQuickAction: (QuickAction) -> Unit
) {
    var noteText by remember(ticket.id, ticket.note) { mutableStateOf(ticket.note) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = ticket.contactName ?: ticket.phoneNumber,
                        style = MaterialTheme.typography.titleLarge
                    )
                    if (!ticket.contactName.isNullOrBlank()) {
                        Text(text = ticket.phoneNumber, style = MaterialTheme.typography.bodyLarge)
                    }
                    Text(
                        text = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date(ticket.createdAt)),
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                Row {
                    IconButton(onClick = { onCallTap(ticket.phoneNumber) }) {
                        Icon(
                            imageVector = Icons.Default.Call,
                            contentDescription = "Call",
                            tint = Color(0xFF2E7D32),
                            modifier = Modifier.size(30.dp)
                        )
                    }
                    IconButton(onClick = onCloseTap) {
                        Icon(
                            imageVector = Icons.Default.Close,
                            contentDescription = "Close",
                            tint = Color(0xFFC62828),
                            modifier = Modifier.size(30.dp)
                        )
                    }
                }
            }

            OutlinedTextField(
                value = noteText,
                onValueChange = {
                    noteText = it
                    onNoteChange(it)
                },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
                label = { Text("Pickup notes") }
            )

            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                QuickActionButton("On my way") { onQuickAction(QuickAction.ON_MY_WAY) }
                QuickActionButton("8 min") { onQuickAction(QuickAction.ETA_8) }
                QuickActionButton("5 min") { onQuickAction(QuickAction.ETA_5) }
            }

            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                QuickActionButton("1 min") { onQuickAction(QuickAction.ETA_1) }
                Button(onClick = { onQuickAction(QuickAction.ARRIVED) }) {
                    Text("Arrived")
                }
            }
        }
    }
}

@Composable
private fun QuickActionButton(label: String, onClick: () -> Unit) {
    TextButton(onClick = onClick) {
        Text(label)
    }
}
