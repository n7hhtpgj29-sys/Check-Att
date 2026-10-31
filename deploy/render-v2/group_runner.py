from threading import Thread, Lock
from collections import Counter
from datetime import datetime, timezone
from fast_collector import scan_group
import os
import json
import psycopg
import logging
import checkpoint_store as checkpoints

log=logging.getLogger(__name__)

lock = Lock()
jobs = {}
active_job_id = None


def persist_completed_job(job_id):
    """Store a complete roster snapshot in the existing private attendance_v2 tables."""
    job = jobs[job_id]
    if job["department"] != "ALL" or job["done"] != job["total"]:
        return False
    scheduled = job.get("trigger_type") == "scheduled"
    key = job.get("scheduled_key") if scheduled else None
    if scheduled and not key:
        raise ValueError("scheduled_key_required")
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=8, options="-c statement_timeout=30000") as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO attendance_v2.departments(code,name) VALUES('ALL','All departments') ON CONFLICT(code) DO NOTHING")
            cur.execute("""INSERT INTO attendance_v2.attendance_runs
                (department_id,shift,work_date,trigger_type,status,started_at,finished_at,
                 total_employees,missing_count,error_count,scheduled_key)
                VALUES ((SELECT id FROM attendance_v2.departments WHERE code='ALL'),
                    %s,%s,%s,'completed',now(),%s::timestamptz,%s,%s,%s,%s)
                ON CONFLICT(scheduled_key) DO UPDATE SET status='completed',finished_at=EXCLUDED.finished_at,
                    total_employees=EXCLUDED.total_employees,missing_count=EXCLUDED.missing_count,
                    error_count=EXCLUDED.error_count
                RETURNING id""",
                (job["shift"],job["work_date"],job.get("trigger_type","manual"),
                 job["query_completed_at"],job["total"],job["counts"].get("NO_SCAN_IN_WINDOW",0),
                 job["counts"].get("INCOMPLETE",0)+job["counts"].get("QUERY_ERROR",0),key))
            run_id=cur.fetchone()[0]
            cur.execute("DELETE FROM attendance_v2.attendance_results WHERE run_id=%s",(run_id,))
            cur.executemany("""INSERT INTO attendance_v2.attendance_results
                (run_id,employee_no,status,detail) VALUES(%s,%s,%s,%s)""",
                [(run_id,r["employee_no"],r["status"],json.dumps({"name":r["name"],"department":r["department"]},ensure_ascii=False)) for r in job["results"]])
    return True


def launch(job_id, employees, shift, work_date, department, employee_names,
           employee_departments=None, trigger_type="manual", scheduled_key=None,
           resume=False):
    global active_job_id
    if not lock.acquire(blocking=False):
        return False
    active_job_id=job_id
    roster=[{"employee_no":emp,"name":employee_names.get(emp,""),
             "department":(employee_departments or {}).get(emp,department)} for emp in employees]
    try:
        if resume:
            checkpoints.increment_recovery(job_id)
        else:
            checkpoints.create(job_id,roster,shift,work_date,department,trigger_type,scheduled_key)
    except Exception:
        log.exception("V2 failed to create/load durable job checkpoint")
        active_job_id=None
        lock.release()
        return False
    jobs[job_id]={"status":"running","total":len(employees),"done":0,"counts":{},
                  "shift":shift,"department":department,"work_date":work_date,
                  "trigger_type":trigger_type,"scheduled_key":scheduled_key,"results":[],
                  "scan_progress":{"stage":"starting","checked":0,"total":len(employees),"retry_pending":0},
                  "started_at":datetime.now(timezone.utc).isoformat()}
    def worker():
        counts=Counter()
        try:
            recovered=checkpoints.load_results(job_id) if resume else {}
            def progress_callback(**progress):
                jobs[job_id]["scan_progress"] = progress
                # Heartbeat is already saved with every per-employee checkpoint.
            def result_callback(employee_no,status,phase):
                checkpoints.save_result(job_id,employee_no,status,phase)
            for employee_no,status in zip(employees,scan_group(
                    employees,shift,work_date,progress_callback=progress_callback,
                    result_callback=result_callback,resumed=recovered)):
                if status not in ("SCAN_FOUND","NO_SCAN_IN_WINDOW","INCOMPLETE","QUERY_ERROR"):
                    status="QUERY_ERROR"
                counts[status]+=1
                jobs[job_id]["results"].append({
                    "employee_no":employee_no,"name":employee_names.get(employee_no,""),
                    "department":(employee_departments or {}).get(employee_no,department),
                    "status":status})
                jobs[job_id].update(done=sum(counts.values()),counts=dict(counts))
            if jobs[job_id]["done"]!=jobs[job_id]["total"]:
                jobs[job_id]["status"]="failed"
                jobs[job_id]["error"]="collector_ended_before_roster_completed"
                checkpoints.mark(job_id,"needs_attention","collector_ended_before_roster_completed")
            else:
                # Capture when the last employee was queried, prior to DB persistence
                # or any later Make.com / LINE transmission delay.
                jobs[job_id]["query_completed_at"]=datetime.now(timezone.utc).isoformat()
                try:
                    jobs[job_id]["persisted"]=persist_completed_job(job_id)
                    if not jobs[job_id]["persisted"]:
                        raise RuntimeError("persistence_incomplete")
                    checkpoints.mark(job_id,"completed")
                    jobs[job_id]["status"]="completed"
                    if jobs[job_id]["persisted"] and trigger_type == "scheduled":
                        # Do not block new attendance runs while the webhook is sent.
                        from webhook_bridge import deliver_after_completion
                        Thread(target=deliver_after_completion,
                               args=(dict(jobs[job_id]),),daemon=True).start()
                except Exception:
                    log.exception("V2 completed scan persistence failed")
                    jobs[job_id]["persisted"]=False
                    jobs[job_id]["storage_error"]=True
                    jobs[job_id]["status"]="failed"
                    try:
                        checkpoints.mark(job_id,"needs_attention","result_persistence_failed")
                    except Exception:
                        log.exception("V2 failure state could not be persisted")
        except Exception:
            log.exception("V2 collector failed; saved checkpoints remain available")
            jobs[job_id]["status"]="failed"
            jobs[job_id]["error"]="collector_failed"
            try:
                checkpoints.mark(job_id,"needs_attention","collector_failed")
            except Exception:
                log.exception("V2 failure state could not be persisted")
        finally:
            jobs[job_id]["finished_at"]=datetime.now(timezone.utc).isoformat()
            global active_job_id
            active_job_id=None
            lock.release()
    Thread(target=worker,daemon=True).start()
    return True


def active_job():
    return {"job_id":active_job_id,**jobs[active_job_id]} if active_job_id in jobs else None


def recover_interrupted_jobs():
    """Restart at most one recently interrupted job after Gunicorn worker boot."""
    from time import sleep
    sleep(5)
    try:
        pending=checkpoints.recoverable()
        if not pending:
            return
        # Newest run first; avoid automatically restarting several historical jobs.
        job=pending[0]
        roster=job["roster"]
        ids=[r["employee_no"] for r in roster]
        names={r["employee_no"]:r["name"] for r in roster}
        departments={r["employee_no"]:r["department"] for r in roster}
        if active_job():
            log.warning("V2 interrupted job recovery postponed; another scan active")
            return
        accepted=launch(job["job_id"],ids,job["shift"],job["work_date"],
                        job["department"],names,departments,
                        trigger_type="scheduled",scheduled_key=job["scheduled_key"],
                        resume=True)
        log.warning("V2 interrupted scan recovery job=%s accepted=%s",job["job_id"],accepted)
    except Exception:
        log.exception("V2 recovery could not initialize")
