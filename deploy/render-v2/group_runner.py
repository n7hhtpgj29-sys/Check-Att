from threading import Thread, Lock
from collections import Counter
from datetime import datetime
from collector_v2 import query_employee

lock=Lock()
jobs={}

def launch(job_id, employees, shift):
    if not lock.acquire(blocking=False):
        return False
    jobs[job_id]={"status":"running","total":len(employees),"done":0,"counts":{}}
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
        except Exception:
            jobs[job_id]["status"]="failed"
        finally:
            lock.release()
    Thread(target=worker,daemon=True).start()
    return True
