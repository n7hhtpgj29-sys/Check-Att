# Attendance V2 → Make.com completion webhook

## What is already implemented
- A scheduled V2 job collects the ACTIVE employee roster and runs adaptive retries.
- After all results are persisted in Supabase, V2 queues one completion event for that invocation.
- V2 sends a JSON POST to the exact `V2_MAKE_WEBHOOK_URL` configured on the **staging Render service**. Payload contains only:
  `event, job_id, invocation_id, shift, work_date`. No employee names or admin token are sent.
- V2 keeps an outbox record and only marks **accepted_by_make** after a 2xx HTTP response.
- A distinct invocation is generated for each manual Make Run once. Do not deduplicate by day.
- LINE is not sent directly by the V2 webhook bridge. Make must call /line-delivery-claim, then LINE push, then /line-delivery-ack.
- If webhook delivery fails, use authenticated `POST /api/v2/webhook-retry` with `{"job_id":"..."}` for a pending job. Inspect `GET /api/v2/webhook-status`.
- Receipt by Make (2xx) is **not proof** that LINE was delivered.

## Make configuration required
Make.com does not combine a daily Schedule trigger and a Custom Webhook trigger inside a single linear scenario. Use two short scenarios, not a long HTTP wait:

**A: Existing schedule starter** (Daily 08:19, 20:19 Asia/Bangkok)
1. Set V2 Admin Token
2. POST `https://cc-attendance-v2-staging.onrender.com/api/v2/scheduled-run`, body `{}`, header `X-Admin-Token`.
3. Stop. Remove/disable the old long-wait + LINE modules. This scenario should finish within seconds.

**B: Completion receiver** (new Custom Webhook trigger)
1. Webhooks > Custom Webhook. Create a new hook and copy its full URL privately into Render > Environment > `V2_MAKE_WEBHOOK_URL`.
2. HTTP: POST `https://cc-attendance-v2-staging.onrender.com/api/v2/line-delivery-claim` with JSON body:
   `{"job_id":"{{1.job_id}}","invocation_id":"{{1.invocation_id}}","shift":"{{1.shift}}","work_date":"{{1.work_date}}"}`
   and header `X-Admin-Token` set privately in Make. Map the actual Make output tokens.
3. Filter: run LINE only if HTTP claim `ready=true` AND `claimed=true` AND `line_message` is present.
4. HTTP POST `https://api.line.me/v2/bot/message/push` with existing Bot chat LINE OA authorization, recipient and text `{{claim.line_message}}`.
5. After LINE API reports success, HTTP POST `https://cc-attendance-v2-staging.onrender.com/api/v2/line-delivery-ack`, JSON `{"invocation_id":"{{1.invocation_id}}"}` and X-Admin-Token.
6. Leave error handling visible; on LINE 429, do not acknowledge as sent. Do not blindly replay accepted webhook events. The claim persists intentionally to avoid duplicate LINE after an uncertain send result.

**Safety checklist**
- Disable the previous Make v6 260-second LINE delivery path before activating the receiver to avoid confusing parallel checks.
- Configure the webhook URL only in the Render Environment UI; never paste the full hook or admin/LINE tokens into a chat or repository.
- Test on staging using the current roster and observe webhook-status plus execution logs.
- If an attendance run is interrupted by Render restart, no completion callback is fired. Fix durable job resumption separately if needed.
- The webhook feature is **inactive** until `V2_MAKE_WEBHOOK_URL` is set and the Make receiver scenario is enabled.

## Status endpoints
- GET /api/v2/webhook-status (authenticated): configured, recent outbox rows, attempts and state.
- POST /api/v2/webhook-retry (authenticated): retry a known pending completed job only.

Production `cc-attendance-iphone-pwa.onrender.com` is not modified.
