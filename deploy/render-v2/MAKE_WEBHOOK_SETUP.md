# Attendance V2 → One Make Scenario (completion webhook)

## Intended final process
Attendance V2 scheduler (08:19 D / 20:19 N, Asia/Bangkok)
→ V2 scans current active roster and retries only unverified employees
→ persist completed report in Supabase
→ V2 webhook notifies Make
→ **one Make scenario** receives event, calls V2 claim API, sends via existing LINE OA, acknowledges success.

There is no long-running Make HTTP wait and no Repeater.

## Prepared components
- `scheduler_v2.py`: opt-in scheduler with a unique database slot per date+shift. Only fires in a 20-minute window after scheduled time, never starts when another V2 scan is active.
- `gunicorn_config.py`: starts scheduler thread in the single Gunicorn worker **only if** `V2_INTERNAL_SCHEDULER_ENABLED=1`.
- `webhook_bridge.py`: completion event outbox with an HTTPS Make URL; only called after persisted complete run.
- `GET /api/v2/webhook-status`, `POST /api/v2/webhook-retry`: authenticated operational checks.
- Original PWA production and original Make v6 are not modified.

## Connect Make before enabling the new scheduler
1. Import `Attendance_V2_One_Scenario_Webhook_to_LINE.blueprint.json` into a **NEW** Make scenario (do not replace the working v6).
2. In module 01, create **Webhooks > Custom Webhook** and obtain its live URL.
3. In module 02 enter the V2 admin token privately and configure module 04 to use the existing LINE OA connection / target group. Verify modules 03 claim and 05 ack map `invocation_id`.
4. In Render Staging `cc-attendance-v2-staging` Environment set `V2_MAKE_WEBHOOK_URL` to the full HTTPS URL **privately**; do not paste secrets in messages or commit them.
5. Activate the new Webhook receiver. Check `GET /api/v2/webhook-status` to confirm configured. Perform one deliberate staging test and verify EXACTLY one LINE push and ACK.
6. **Only after successful test**, disable the legacy v6 schedule in Make. Then set Render Staging Environment `V2_INTERNAL_SCHEDULER_ENABLED=1`.
7. The old Make v6 remains available but should remain inactive to avoid two schedule sources issuing duplicate scans.

## Important operational constraint
**Render Free web services sleep after inactivity and may restart. In-process scheduler timing is NOT reliable on the Free plan.**
A dedicated Render Cron Job is better for guaranteed 08:19 and 20:19 starts, but Render documents a minimum $1/month charge per cron job; do not create one without billing approval.
For production-grade scheduling prefer a Render Cron job or an external reliable scheduler that calls the V2 start endpoint using a securely configured credential. The internal scheduler is only suitable when the web service stays awake and restarts are acceptable.

## Schedule
08:19 and 20:19 Asia/Bangkok. The opt-in internal scheduler checks every 25 seconds while the web worker is alive.
Slots are recorded in `attendance_v2.scheduler_slots`, uniquely by date and shift to reduce duplicates.
An interrupted run is not automatically replayed; it must be reviewed (avoids accidental duplicate notification).

## Completion payload (no personal roster data)
```json
{"event":"attendance_v2.completed","job_id":"V2:ALL:D:2026-10-29:<uuid>",
 "invocation_id":"<uuid>","shift":"D","work_date":"2026-10-29"}
```

## Caveats
- Webhook status `accepted` means Make acknowledged receipt, **not** that LINE was delivered.
- Final sending is gated on `ready=true` and `claimed=true`. ACK only after LINE success.
- No Scan is not a confirmed absence; Query Error and Incomplete never become No Scan.
- If the job is killed by Render restart before persistence, there is no completion webhook.
- Make v6 unchanged; do not enable its old schedule together with the new scheduler.
