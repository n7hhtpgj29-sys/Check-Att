from threading import Thread, Lock
from collections import Counter
from datetime import datetime
from fast_collector import scan_group

lock=Lock()
jobs={}
active_job_id=None

def launch(job_id, employees, shift, work_date, department, employee_names, employee_departments=None):
    global active_job_id
    if not lock.acquire(blocking=False):
        return False
    active_job_id=job_id
    jobs[job_id]={"status":"running","total":len(employees),"done":0,"counts":{},"shift":shift,"department":department,"work_date":work_date,"results":[],"started_at":datetime.now().isoformat()}
    def worker():
        counts=Counter()
        try:
            for employee_no,status in zip(employees,scan_group(employees,shift,work_date)):
                if status not in ("SCAN_FOUND","NO_SCAN_IN_WINDOW","INCOMPLETE","QUERY_ERROR"):status="QUERY_ERROR"
                counts[status]+=1
                jobs[job_id]["results"].append({"employee_no":employee_no,"name":employee_names.get(employee_no,""),"department":(employee_departments or {}).get(employee_no,department),"status":status})
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
