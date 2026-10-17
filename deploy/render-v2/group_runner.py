from threading import Thread, Lock
from collections import Counter
from datetime import datetime, timezone
from fast_collector import scan_group
import os
import psycopg

lock = Lock()
jobs = {}
active_job_id = None


def persist_completed_job(job_id):
    """Store a complete roster snapshot in the existing private attendance_v2 tables."""
    job = jobs[job_id]
    if job["department"] != "ALL" or job["done"] != job["total"]:
        return False
    scheduled = job.get("trigger_type") == "scheduled"
    key = "V2:ALL:%s:%s" % (job["shift"], job["work_date"]) if scheduled else None
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=8, options="-c statement_timeout=30000") as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO attendance_v2.departments(code,name) VALUES('ALL','All departments') ON CONFLICT(code) DO NOTHING")
            cur.execute("""INSERT INTO attendance_v2.attendance_runs
                (department_id,shift,work_date,trigger_type,status,started_at,finished_at,
                 total_employees,missing_count,error_count,scheduled_key)
                VALUES ((SELECT id FROM attendance_v2.departments WHERE code='ALL'),
                    %s,%s,%s,'completed',now(),now(),%s,%s,%s,%s)
                ON CONFLICT(scheduled_key) DO UPDATE SET status='completed',finished_at=now(),
                    total_employees=EXCLUDED.total_employees,missing_count=EXCLUDED.missing_count,
                    error_count=EXCLUDED.error_count
                RETURNING id""",
                (job["shift"],job["work_date"],job.get("trigger_type","manual"),
                 job["total"],job["counts"].get("NO_SCAN_IN_WINDOW",0),
                 job["counts"].get("INCOMPLETE",0)+job["counts"].get("QUERY_ERROR",0),key))
            run_id=cur.fetchone()[0]
            cur.execute("DELETE FROM attendance_v2.attendance_results WHERE run_id=%s",(run_id,))
            cur.executemany("""INSERT INTO attendance_v2.attendance_results
                (run_id,employee_no,status) VALUES(%s,%s,%s)""",
                [(run_id,r["employee_no"],r["status"]) for r in job["results"]])
    return True


def launch(job_id, employees, shift, work_date, department, employee_names,
           employee_departments=None, trigger_type="manual"):
    global active_job_id
    if not lock.acquire(blocking=False):
        return False
    active_job_id=job_id
    jobs[job_id]={"status":"running","total":len(employees),"done":0,"counts":{},
                  "shift":shift,"department":department,"work_date":work_date,
                  "trigger_type":trigger_type,"results":[],
                  "started_at":datetime.now(timezone.utc).isoformat()}
    def worker():
        counts=Counter()
        try:
            for employee_no,status in zip(employees,scan_group(employees,shift,work_date)):
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
            else:
                jobs[job_id]["status"]="completed"
                try:
                    jobs[job_id]["persisted"]=persist_completed_job(job_id)
                except Exception:
                    jobs[job_id]["persisted"]=False
                    jobs[job_id]["storage_error"]=True
        except Exception:
            jobs[job_id]["status"]="failed"
            jobs[job_id]["error"]="collector_failed"
        finally:
            jobs[job_id]["finished_at"]=datetime.now(timezone.utc).isoformat()
            global active_job_id
            active_job_id=None
            lock.release()
    Thread(target=worker,daemon=True).start()
    return True


def active_job():
    return {"job_id":active_job_id,**jobs[active_job_id]} if active_job_id in jobs else None
