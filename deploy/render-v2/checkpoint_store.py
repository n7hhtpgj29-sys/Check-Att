"""Persistent scan checkpoints and restart recovery for staging attendance jobs.

All rows are stored under attendance_v2. Only one V2 web worker should run.
A recovered run keeps the original scheduled_key (LINE idempotency key).
"""
import json
import logging
import os
from datetime import datetime,timezone,timedelta
import psycopg

log=logging.getLogger(__name__)
VALID={"SCAN_FOUND","NO_SCAN_IN_WINDOW","INCOMPLETE","QUERY_ERROR"}


def database():
    return psycopg.connect(os.environ["DATABASE_URL"],connect_timeout=8,
                           options="-c statement_timeout=30000")


def ensure(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_v2.scan_checkpoints(
            job_id text PRIMARY KEY,
            scheduled_key text UNIQUE,
            trigger_type text NOT NULL,
            department text NOT NULL,
            shift text NOT NULL,
            work_date date NOT NULL,
            roster_json jsonb NOT NULL,
            total integer NOT NULL,
            state text NOT NULL DEFAULT 'running',
            started_at timestamptz NOT NULL DEFAULT now(),
            heartbeat_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            failure_reason text,
            restored integer NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_v2.scan_checkpoint_results(
            job_id text NOT NULL REFERENCES attendance_v2.scan_checkpoints(job_id),
            employee_no text NOT NULL,
            status text NOT NULL,
            phase text NOT NULL,
            checked_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(job_id,employee_no)
        )
    """)


def create(job_id,roster,shift,work_date,department,trigger_type,scheduled_key):
    with database() as db:
        with db.cursor() as cur:
            ensure(cur)
            cur.execute("""
                INSERT INTO attendance_v2.scan_checkpoints
                    (job_id,scheduled_key,trigger_type,department,shift,work_date,
                     roster_json,total)
                VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            """,(job_id,scheduled_key,trigger_type,department,shift,work_date,
                 json.dumps(roster,ensure_ascii=False),len(roster)))


def heartbeat(job_id):
    with database() as db:
        with db.cursor() as cur:
            cur.execute("""
                UPDATE attendance_v2.scan_checkpoints
                SET heartbeat_at=now() WHERE job_id=%s AND state='running'
            """,(job_id,))


def save_result(job_id,employee_no,status,phase):
    if status not in VALID:
        status="QUERY_ERROR"
    with database() as db:
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO attendance_v2.scan_checkpoint_results
                    (job_id,employee_no,status,phase)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT(job_id,employee_no)
                DO UPDATE SET status=EXCLUDED.status, phase=EXCLUDED.phase,
                              checked_at=now()
            """,(job_id,employee_no,status,phase))
            cur.execute("""
                UPDATE attendance_v2.scan_checkpoints
                SET heartbeat_at=now() WHERE job_id=%s
            """,(job_id,))


def load_results(job_id):
    with database() as db:
        with db.cursor() as cur:
            ensure(cur)
            cur.execute("""
                SELECT employee_no,status FROM attendance_v2.scan_checkpoint_results
                WHERE job_id=%s
            """,(job_id,))
            return dict(cur.fetchall())


def mark(job_id,state,reason=None):
    with database() as db:
        with db.cursor() as cur:
            cur.execute("""
                UPDATE attendance_v2.scan_checkpoints
                SET state=%s,failure_reason=%s,heartbeat_at=now(),
                    finished_at=CASE WHEN %s='running' THEN NULL ELSE now() END
                WHERE job_id=%s
            """,(state,reason,state,job_id))


def recoverable(max_age_hours=5):
    """Recover only recently interrupted scheduled scans; do not replay stale shifts."""
    cutoff=datetime.now(timezone.utc)-timedelta(hours=max_age_hours)
    with database() as db:
        with db.cursor() as cur:
            ensure(cur)
            cur.execute("""
                SELECT job_id,scheduled_key,trigger_type,department,shift,work_date,
                       roster_json,started_at
                FROM attendance_v2.scan_checkpoints
                WHERE state='running'
                ORDER BY started_at DESC
            """)
            rows=cur.fetchall()
            pending=[]
            for job_id,key,trigger_type,dept,shift,day,roster,started in rows:
                if started < cutoff:
                    cur.execute("""
                        UPDATE attendance_v2.scan_checkpoints
                        SET state='needs_attention',
                            failure_reason='restart_recovery_window_expired',
                            finished_at=now()
                        WHERE job_id=%s AND state='running'
                    """,(job_id,))
                    log.warning("V2 stale interrupted job needs attention: %s",job_id)
                elif trigger_type=="scheduled":
                    pending.append(dict(job_id=job_id,scheduled_key=key,
                                        department=dept,shift=shift,
                                        work_date=str(day),roster=roster))
            return pending


def increment_recovery(job_id):
    with database() as db:
        with db.cursor() as cur:
            cur.execute("""
                UPDATE attendance_v2.scan_checkpoints
                SET restored=restored+1,heartbeat_at=now() WHERE job_id=%s
            """,(job_id,))


def recent_health(limit=12):
    with database() as db:
        with db.cursor() as cur:
            ensure(cur)
            cur.execute("""
                SELECT c.job_id,c.scheduled_key,c.shift,c.work_date,c.state,
                       c.total,c.heartbeat_at,c.restored,c.failure_reason,
                       count(r.employee_no) AS checked,
                       count(r.employee_no) FILTER
                           (WHERE r.status IN ('SCAN_FOUND','NO_SCAN_IN_WINDOW')) AS verified
                FROM attendance_v2.scan_checkpoints c
                LEFT JOIN attendance_v2.scan_checkpoint_results r
                    ON r.job_id=c.job_id
                GROUP BY c.job_id
                ORDER BY c.started_at DESC LIMIT %s
            """,(limit,))
            return [dict(job_id=a,scheduled_key=b,shift=c,work_date=str(d),
                         state=e,total=f,heartbeat_at=g.isoformat(),
                         recovered_count=h,failure_reason=i,
                         checkpointed=j,verified=k)
                    for a,b,c,d,e,f,g,h,i,j,k in cur.fetchall()]
