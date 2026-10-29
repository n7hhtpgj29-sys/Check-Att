"""Opt-in Asia/Bangkok Attendance V2 scheduler (one Gunicorn worker).

Only activate after legacy Make schedule has been disabled and a Make webhook
receiver is configured. An active Free Render service may be suspended by the
platform; use a managed cron for strict 08:19/20:19 reliability.
"""
import logging
import os
import threading
import time
from datetime import datetime, time as daytime, timedelta
from zoneinfo import ZoneInfo
import psycopg

log=logging.getLogger(__name__)
BKK=ZoneInfo("Asia/Bangkok")
_started=False
_lock=threading.Lock()
SHIFT_TIMES={"D":daytime(8,19),"N":daytime(20,19)}


def _db():
    return psycopg.connect(os.environ["DATABASE_URL"],
                           connect_timeout=8, options="-c statement_timeout=12000")


def _ensure_slots(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_v2.scheduler_slots(
            work_date date NOT NULL,
            shift text NOT NULL CHECK(shift IN ('D','N')),
            state text NOT NULL DEFAULT 'started'
                CHECK(state IN ('started','completed')),
            job_key text,
            claimed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(work_date,shift)
        )
    """)


def tick(now=None):
    """One check. No duplicate scan when worker is restarted within the window."""
    from webhook_bridge import configured_webhook
    if not configured_webhook():
        return {"started":False,"reason":"webhook_not_configured"}
    from group_runner import launch, active_job
    now=(now or datetime.now(BKK)).astimezone(BKK)
    for shift,clock in SHIFT_TIMES.items():
        due=datetime.combine(now.date(),clock,BKK)
        late=(now-due).total_seconds()
        if late < 0 or late > 20*60:
            continue
        if active_job():
            return {"started":False,"reason":"another_run_active"}
        with _db() as db:
            with db.cursor() as cur:
                _ensure_slots(cur)
                cur.execute("""
                    INSERT INTO attendance_v2.scheduler_slots(work_date,shift)
                    VALUES (%s,%s)
                    ON CONFLICT DO NOTHING
                    RETURNING work_date
                """,(now.date(),shift))
                claimed=cur.fetchone() is not None
        if not claimed:
            return {"started":False,"reason":"slot_already_claimed"}
        # A committed slot is intentionally not retried after a crash; an
        # interrupted run must be reviewed, not silently duplicate a LINE push.
        import uuid
        job_id=str(uuid.uuid4())
        invocation_id=str(uuid.uuid4())
        job_key="V2:ALL:"+shift+":"+now.date().isoformat()+":"+invocation_id
        with _db() as db:
            with db.cursor() as cur:
                cur.execute("""
                    SELECT e.employee_no,e.full_name,d.name
                    FROM attendance_v2.employees e
                    JOIN attendance_v2.departments d ON d.id=e.department_id
                    WHERE e.active AND e.shift=%s ORDER BY e.employee_no
                """,(shift,))
                roster=cur.fetchall()
                cur.execute("""
                    UPDATE attendance_v2.scheduler_slots SET job_key=%s
                    WHERE work_date=%s AND shift=%s
                """,(job_key,now.date(),shift))
        if not roster:
            log.error("V2 scheduler: empty roster for shift %s",shift)
            return {"started":False,"reason":"empty_roster"}
        ids=[r[0] for r in roster]
        names={r[0]:r[1] for r in roster}
        depts={r[0]:r[2] for r in roster}
        if not launch(job_id,ids,shift,now.date().isoformat(),
                      "ALL",names,depts,trigger_type="scheduled",
                      scheduled_key=job_key):
            log.warning("V2 scheduler did not start claimed slot")
            return {"started":False,"reason":"launch_rejected"}
        log.info("V2 scheduler started shift=%s roster_count=%d",shift,len(ids))
        return {"started":True,"shift":shift,"total":len(ids)}
    return {"started":False,"reason":"outside_schedule_window"}


def _loop():
    # Delay a little after the worker starts so database migrations/deploy
    # health checks are not competing with scheduler initialization.
    time.sleep(8)
    while True:
        try:
            tick()
        except Exception:
            log.exception("V2 internal scheduler tick failed")
        time.sleep(25)


def start():
    global _started
    if os.getenv("V2_INTERNAL_SCHEDULER_ENABLED")!="1":
        log.info("V2 internal scheduler disabled; no scheduled scans started")
        return
    with _lock:
        if _started:
            return
        _started=True
    thread=threading.Thread(target=_loop,name="v2-internal-scheduler",daemon=True)
    thread.start()
