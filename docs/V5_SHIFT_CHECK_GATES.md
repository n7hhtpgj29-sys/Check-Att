# Attendance v5 shift check gates

Confirmed by operator on 2026-10-16:
- Day shift scheduled check: 08:15 Asia/Bangkok, on shift work date.
- Night shift scheduled check: 20:15 Asia/Bangkok, on shift work date.
- Prior to the relevant check time, state is PENDING and missing list is empty. Do not label anyone absent.
- At or after gate, run collection for the relevant work date and shift. Query failure, partial pagination, and missing roster are not MISSING.
- For night shift, use start date as work date; support timestamps through the following morning. Never use prior night's scans for current night.
- A missing scan is not equivalent to an approved absence determination; reconcile leave/holiday/roster changes.
- Reruns should be idempotent by department + shift + work_date + check phase; track source freshness.
- Testing must cover 20:14 -> PENDING, 20:15 -> eligible, next-day 00:30 -> same night work date, and 08:14 -> PENDING, 08:15 -> eligible.
- Existing v4 Windows test may produce false NO_SCAN_IN_WINDOW if run early. Do not treat early-run results as absences.
