# Sasha Dispatcher (Android MVP)

Local-first taxi call + SMS dispatcher app built with Kotlin, Jetpack Compose, Room, and MVVM.

## MVP features
- Active caller queue as large cards.
- Manual "Add Test Caller" flow.
- Per-caller editable notes with automatic persistence.
- Quick actions (On my way, 8 min, 5 min, 1 min, Arrived).
- Queue position auto-messages for callers below selected card.
- Green call action (opens dialer).
- Red close/archive action.
- Basic history tab.
- Telephony integration hook interface for future incoming-call support.

## Open in Android Studio
1. Open the `Sasha_Dispatcher` folder.
2. Let Android Studio sync and generate wrapper files if prompted.
3. Run on a real device and grant permissions when requested.

## Notes
- Runtime permission request UI is intentionally minimal in this MVP.
- Messaging and contact lookup are abstracted to be swappable later.
