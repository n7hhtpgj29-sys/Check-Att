from threading import Thread, Lock
from collections import Counter
from datetime import datetime
from collector_v2 import query_employee

lock=Lock()
jobs={}
active_job_id=None

def launch(job_id, employees, shift):
    global active_job_id
    if not lock.acquire(blocking=False):
        return False
    active_job_id=job_id
    jobs[job_id]={"status":"running","total":len(employees),"done":0,"counts":{},"shift":shift,"started_at":datetime.now().isoformat()}
    def worker():
        counts=Counter()
        try:
            for employee_no in employees:
                try:
                    result=query_employee(employee_no,shift)
                    status=result.get("status","QUERY_ERROR")
                    if status not in ("SCAN_FOUND","INCOMPLETE","QUERY_ERROR"):
                        status="QUERY_ERROR"
                except Exception:
                    status="QUERY_ERROR"
                counts[status]+=1
                jobs[job_id].update(done=sum(counts.values()),counts=dict(counts))
            jobs[job_id]["status"]="completed"
            jobs[job_id]["finished_at"]=datetime.now().isoformat()
        except Exception:
            jobs[job_id]["status"]="failed"
            jobs[job_id]["finished_at"]=datetime.now().isoformat()
        finally:
            global active_job_id
            active_job_id=None
            lock.release()
    Thread(target=worker,daemon=True).start()
    return True

def active_job():
    return {"job_id":active_job_id,**jobs[active_job_id]} if active_job_id in jobs else None
