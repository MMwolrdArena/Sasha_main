package com.example.taxidispatcher.ui.main

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.taxidispatcher.ui.components.CallerCard
import com.example.taxidispatcher.ui.history.HistoryScreen

private enum class TabItem(val title: String) {
    Queue("Queue"),
    History("History")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    viewModel: QueueViewModel,
    onCallTap: (String) -> Unit
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var showAddDialog by remember { mutableStateOf(false) }
    var selectedTab by remember { mutableStateOf(TabItem.Queue) }
    val context = LocalContext.current

    uiState.toastMessage?.let { toastText ->
        LaunchedEffect(toastText) {
            Toast.makeText(context, toastText, Toast.LENGTH_SHORT).show()
            viewModel.clearToast()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(title = {
                Column {
                    Text("Taxi Dispatcher", style = MaterialTheme.typography.titleLarge)
                    Text(
                        "Active callers: ${uiState.activeTickets.size}",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            })
        },
        floatingActionButton = {
            if (selectedTab == TabItem.Queue) {
                FloatingActionButton(onClick = { showAddDialog = true }) {
                    Icon(Icons.Default.Add, contentDescription = "Add Test Caller")
                }
            }
        },
        bottomBar = {
            NavigationBar {
                TabItem.entries.forEach { item ->
                    NavigationBarItem(
                        selected = selectedTab == item,
                        onClick = { selectedTab = item },
                        icon = {},
                        label = { Text(item.title) }
                    )
                }
            }
        }
    ) { paddingValues ->
        when (selectedTab) {
            TabItem.Queue -> {
                LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(paddingValues).padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    items(uiState.activeTickets, key = { it.id }) { ticket ->
                        CallerCard(
                            ticket = ticket,
                            onCallTap = onCallTap,
                            onCloseTap = { viewModel.closeTicket(ticket) },
                            onNoteChange = { viewModel.updateNote(ticket, it) },
                            onQuickAction = { action -> viewModel.handleQuickAction(ticket.id, action) }
                        )
                    }
                }
            }

            TabItem.History -> {
                Column(
                    modifier = Modifier.fillMaxWidth().fillMaxSize().padding(paddingValues)
                ) {
                    HistoryScreen(uiState.archivedTickets)
                }
            }
        }
    }

    if (showAddDialog) {
        AddCallerDialog(
            onDismiss = { showAddDialog = false },
            onConfirm = { phone, name, note ->
                viewModel.addTestCaller(phone, name, note)
                showAddDialog = false
            }
        )
    }
}
