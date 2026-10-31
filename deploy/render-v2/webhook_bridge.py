"""Durable outbound Make webhook notification for finished V2 attendance runs.

No employee roster or LINE credential is sent in the callback. Make must call the
authenticated /api/v2/line-delivery-claim endpoint before sending LINE.
"""
import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
import psycopg

log = logging.getLogger(__name__)


def configured_webhook():
    url = os.environ.get("V2_MAKE_WEBHOOK_URL", "").strip()
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or
            not (parsed.hostname == "make.com" or parsed.hostname.endswith(".make.com")) or
            parsed.username or parsed.password):
        raise ValueError("Invalid HTTPS Make.com webhook URL")
    return url


def database():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=8,
                           options="-c statement_timeout=30000")


def ensure_outbox(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_v2.webhook_outbox (
            job_key text PRIMARY KEY,
            invocation_id text NOT NULL,
            shift text NOT NULL,
            work_date date NOT NULL,
            state text NOT NULL DEFAULT 'pending'
                CHECK(state IN ('pending','accepted')),
            attempts integer NOT NULL DEFAULT 0,
            last_error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            delivered_at timestamptz
        )
    """)


def enqueue(job):
    if job.get("trigger_type") != "scheduled" or not job.get("scheduled_key"):
        return False
    job_key = job["scheduled_key"]
    invocation_id = job_key.rsplit(":", 1)[-1]
    with database() as db:
        with db.cursor() as cur:
            ensure_outbox(cur)
            cur.execute("""
                INSERT INTO attendance_v2.webhook_outbox
                    (job_key,invocation_id,shift,work_date)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT(job_key) DO NOTHING
            """,(job_key,invocation_id,job["shift"],job["work_date"]))
    return True


def dispatch(job_key):
    """Attempt one delivery; idempotent claim in Make prevents repeat LINE pushes."""
    url = configured_webhook()
    if not url:
        return {"sent":False,"reason":"webhook_not_configured"}
    with database() as db:
        with db.cursor() as cur:
            ensure_outbox(cur)
            cur.execute("""
                SELECT job_key,invocation_id,shift,work_date,state
                FROM attendance_v2.webhook_outbox WHERE job_key=%s
            """,(job_key,))
            row=cur.fetchone()
    if not row:
        return {"sent":False,"reason":"outbox_job_not_found"}
    key,invocation_id,shift,work_date,state=row
    if state == "accepted":
        return {"sent":False,"reason":"already_accepted"}
    payload=json.dumps({
        "event":"attendance_v2.completed",
        "job_id":key,
        "invocation_id":invocation_id,
        "shift":shift,
        "work_date":str(work_date)
    }).encode("utf-8")
    req=urllib.request.Request(url,data=payload,method="POST",headers={
        "Content-Type":"application/json","User-Agent":"Attendance-V2-Webhook/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=20,context=ssl.create_default_context()) as response:
            code=response.status
        if not (200<=code<300):
            raise RuntimeError("Make webhook rejected request")
        error=None
    except Exception as exc:
        error=type(exc).__name__
        log.warning("V2 Make webhook delivery failed: %s",error)
    with database() as db:
        with db.cursor() as cur:
            cur.execute("""
                UPDATE attendance_v2.webhook_outbox
                SET attempts=attempts+1,
                    state=CASE WHEN %s::boolean THEN 'accepted' ELSE state END,
                    delivered_at=CASE WHEN %s::boolean THEN now() ELSE delivered_at END,
                    last_error=%s
                WHERE job_key=%s
            """,(error is None,error is None,error,key))
    return {"sent":error is None,"reason":"accepted_by_make" if error is None else error}


def deliver_after_completion(job):
    """Called only after completed attendance results are persisted in Supabase."""
    if not enqueue(job):
        return
    try:
        dispatch(job["scheduled_key"])
    except Exception:
        log.exception("V2 webhook dispatch could not complete")


def reconcile_completed(max_jobs=8):
    """Recover pending completion notifications after a Render worker restart.

    This checks ONLY already completed scheduled reports with no prior
    webhook acknowledgement. The Make-side claim still prevents duplicate LINE.
    """
    if not configured_webhook():
        return {"scanned":0,"reason":"webhook_not_configured"}
    with database() as db:
        with db.cursor() as cur:
            ensure_outbox(cur)
            cur.execute("""
                SELECT r.scheduled_key,r.shift,r.work_date
                FROM attendance_v2.attendance_runs r
                JOIN attendance_v2.departments d ON d.id=r.department_id
                JOIN attendance_v2.scan_checkpoints c
                     ON c.scheduled_key=r.scheduled_key AND c.state='completed'
                LEFT JOIN attendance_v2.webhook_outbox o
                     ON o.job_key=r.scheduled_key
                WHERE r.trigger_type='scheduled'
                  AND r.status='completed'
                  AND d.code='ALL'
                  AND r.scheduled_key IS NOT NULL
                  AND r.finished_at > now()-interval '6 hours'
                  AND (o.job_key IS NULL OR o.state='pending')
                ORDER BY r.finished_at DESC LIMIT %s
            """,(max_jobs,))
            rows=cur.fetchall()
    delivered=0
    for key,shift,day in rows:
        try:
            enqueue({"trigger_type":"scheduled","scheduled_key":key,
                     "shift":shift,"work_date":str(day)})
            status=dispatch(key)
            delivered+=int(status.get("sent",False))
        except Exception:
            log.exception("V2 completed webhook reconciliation failed")
    return {"scanned":len(rows),"accepted":delivered}
