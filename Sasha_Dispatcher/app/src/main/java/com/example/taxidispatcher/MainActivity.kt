package com.example.taxidispatcher

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.ViewModelProvider
import androidx.room.Room
import com.example.taxidispatcher.contacts.AndroidContactLookup
import com.example.taxidispatcher.data.local.AppDatabase
import com.example.taxidispatcher.data.repository.TicketRepository
import com.example.taxidispatcher.domain.messaging.AndroidMessagingManager
import com.example.taxidispatcher.ui.main.MainScreen
import com.example.taxidispatcher.ui.main.QueueViewModel
import com.example.taxidispatcher.ui.main.QueueViewModelFactory
import com.example.taxidispatcher.ui.theme.TaxiDispatcherTheme

class MainActivity : ComponentActivity() {

    private lateinit var viewModel: QueueViewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val database = Room.databaseBuilder(
            applicationContext,
            AppDatabase::class.java,
            "taxi_dispatcher.db"
        ).build()

        val repository = TicketRepository(database.callerTicketDao())
        val viewModelFactory = QueueViewModelFactory(
            repository = repository,
            messagingManager = AndroidMessagingManager(this),
            contactLookup = AndroidContactLookup(this)
        )
        viewModel = ViewModelProvider(this, viewModelFactory)[QueueViewModel::class.java]

        setContent {
            TaxiDispatcherTheme {
                MainScreen(
                    viewModel = viewModel,
                    onCallTap = { phone -> launchCall(phone) }
                )
            }
        }
    }

    private fun launchCall(phoneNumber: String) {
        val intent = Intent(Intent.ACTION_DIAL).apply {
            data = Uri.parse("tel:$phoneNumber")
        }
        startActivity(intent)
    }
}
