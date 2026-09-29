"""Read-only preview and transactional, add-only recovery. Never deletes rows."""
from __future__ import annotations
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from shift_backup import export_archive,import_archive,validate_archive

BKK = ZoneInfo('Asia/Bangkok')
EMP_COLS = ('employee_code','full_name','department','position','active','updated_at',
            'location_support','team_support','group_code','shift')
ATT_COLS = ('employee_code','name_from_web','latest_datetime','status','query_at',
            'scan_in','scan_out','raw_count','ot_minutes','work_date')
SCHEDULE_COLS = ('department','enabled','weekdays','day1_time','day2_time',
                 'night1_time','night_final_time','updated_at')

def now(): return datetime.now(BKK).isoformat(timespec='seconds')
def text(v): return '' if v is None else str(v).strip()
def flag(v, default=1):
    if v is None: return default
    if isinstance(v, str): return int(v.lower() in ('1','true','yes','on'))
    return int(bool(v))
def department(v):
    s = text(v).upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,23}', s) or s == 'ALL':
        raise ValueError('Invalid department in backup: '+s[:30])
    return s

def normalize(pack):
    if not isinstance(pack, dict): raise ValueError('Backup must be a JSON object.')
    if pack.get('format') == 'cc-attendance-rescue':
        raise ValueError('Select one copy from the rescue file preview first.')
    raw = pack.get('employees', [])
    deps = pack.get('departments', [])
    if not isinstance(raw,list) or not isinstance(deps,list): raise ValueError('Invalid backup arrays.')
    if len(raw)>100000: raise ValueError('Too many employees in backup.')
    validate_archive(pack)
    default_dept = pack.get('department')
    dmap = {}
    for r in deps:
        if not isinstance(r,dict): raise ValueError('Invalid department row.')
        d = department(r.get('code') or r.get('department'))
        dmap[d] = dict(code=d,name=text(r.get('name')) or d,
                       active=flag(r.get('active')),updated_at=text(r.get('updated_at')) or now())
    if default_dept:
        d=department(default_dept)
        dmap.setdefault(d,dict(code=d,name=d,active=1,updated_at=now()))
    employees = {}
    for r in raw:
        if not isinstance(r,dict): raise ValueError('Invalid employee row.')
        emp = text(r.get('employee_code')).upper()
        if not emp or len(emp)>80 or any(c in emp for c in '<>\n\r'):
            raise ValueError('Invalid employee code in backup.')
        d = department(r.get('department') or default_dept)
        sh = text(r.get('shift')).upper()
        if sh not in ('D','N'): raise ValueError('Invalid shift for '+emp+': use D or N.')
        if emp in employees: raise ValueError('Duplicate employee code in backup: '+emp)
        row = {k:text(r.get(k)) for k in EMP_COLS}
        row.update(employee_code=emp,department=d,active=flag(r.get('active')),
                   full_name=text(r.get('full_name')) or emp,shift=sh,
                   updated_at=text(r.get('updated_at')) or now())
        employees[emp]=row
        dmap.setdefault(d,dict(code=d,name=d,active=1,updated_at=now()))
    if not dmap: raise ValueError('No departments or employees found in this backup.')
    atts=[]
    rawatts=pack.get('attendance',[]) or []
    if not isinstance(rawatts,list): raise ValueError('Invalid attendance array.')
    for r in rawatts:
        if not isinstance(r,dict): raise ValueError('Invalid attendance row.')
        emp=text(r.get('employee_code')).upper()
        if emp not in employees: continue
        if r.get('department') and department(r['department'])!=employees[emp]['department']:
            raise ValueError('Attendance department mismatch: '+emp)
        row={k:text(r.get(k)) for k in ATT_COLS}
        row.update(employee_code=emp,raw_count=int(r.get('raw_count') or 0),
                   ot_minutes=int(r.get('ot_minutes') or 0))
        atts.append(row)
    schedules=[]
    raws=pack.get('auto_schedules',pack.get('schedules',[])) or []
    if isinstance(pack.get('schedule'),dict): raws=[pack['schedule']]
    if not isinstance(raws,list): raise ValueError('Invalid schedule array.')
    for r in raws:
        d=department(r.get('department') or default_dept)
        if d not in dmap: continue
        row={k:text(r.get(k)) for k in SCHEDULE_COLS}
        wd=r.get('weekdays',list(range(7)))
        if isinstance(wd,str):wd=wd.split(',')
        wd=sorted({int(x) for x in wd})
        if not wd or any(x<0 or x>6 for x in wd):raise ValueError('Invalid schedule weekdays.')
        row.update(department=d,enabled=flag(r.get('enabled')),weekdays=','.join(map(str,wd)),updated_at=now())
        for k in SCHEDULE_COLS[3:7]:
            try: datetime.strptime(row[k],'%H:%M')
            except ValueError: raise ValueError('Invalid schedule time: '+k)
        schedules.append(row)
    return dict(departments=list(dmap.values()),employees=list(employees.values()),attendance=atts,schedules=schedules)

class Recovery:
    def __init__(self,store,ensure_schedule):
        self.store,self.ensure_schedule=store,ensure_schedule
    def export_all(self):
        # Read a coherent snapshot, including empty and inactive departments.
        with self.store.tx() as c:
            if self.store.postgres:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            tables={name:[dict(x) for x in c.execute('SELECT * FROM '+name)]
                    for name in ('departments','employees','attendance','auto_schedules')}
            tables.update(export_archive(c))
        # psycopg timestamps in schedules must be JSON portable.
        for rows in tables.values():
            for r in rows:
                for k,v in list(r.items()):
                    if hasattr(v,'isoformat'):r[k]=v.isoformat()
        return dict(ok=True,format='cc-attendance-all-v1211',version='12.1.3',exported_at=now(),**tables)
    def _summary(self,c,normalized):
        deps={r['code'] for r in c.execute('SELECT code FROM departments')}
        existing={r['employee_code']:r['department'] for r in c.execute('SELECT employee_code,department FROM employees')}
        conflict=[dict(employee_code=r['employee_code'],file_department=r['department'],
                       server_department=existing[r['employee_code']])
                  for r in normalized['employees'] if r['employee_code'] in existing
                  and existing[r['employee_code']]!=r['department']]
        return dict(departments_in_file=len(normalized['departments']),
                    departments_to_add=sum(r['code'] not in deps for r in normalized['departments']),
                    employees_in_file=len(normalized['employees']),
                    employees_to_add=sum(r['employee_code'] not in existing for r in normalized['employees']),
                    employees_kept=sum(r['employee_code'] in existing for r in normalized['employees']),
                    conflicts=conflict,mode='add-missing-only')
    def preview(self,pack):
        n=normalize(pack)
        with self.store.tx() as c:return self._summary(c,n)
    def import_pack(self,pack):
        n=normalize(pack)
        # All validation precedes all writes. One transaction for the entire import.
        with self.store.tx(serial=True) as c:
            result=self._summary(c,n)
            result.update(departments_added=0,employees_added=0,attendance_added=0,schedules_added=0)
            for r in n['departments']:
                cur=c.execute('INSERT INTO departments(code,name,active,updated_at) VALUES(?,?,?,?) '
                              'ON CONFLICT(code) DO NOTHING',tuple(r[k] for k in ('code','name','active','updated_at')))
                result['departments_added']+=max(0,cur.rowcount)
            for r in n['employees']:
                cur=c.execute('INSERT INTO employees('+','.join(EMP_COLS)+') VALUES('+','.join('?' for _ in EMP_COLS)+') '
                              'ON CONFLICT(employee_code) DO NOTHING',tuple(r[k] for k in EMP_COLS))
                result['employees_added']+=max(0,cur.rowcount)
            bycode={r['employee_code']:r['department'] for r in n['employees']}
            # Do not attach another department's scan records to an existing employee.
            actual={r['employee_code']:r['department'] for r in c.execute('SELECT employee_code,department FROM employees')}
            for r in n['attendance']:
                if actual.get(r['employee_code'])!=bycode[r['employee_code']]:continue
                cur=c.execute('INSERT INTO attendance('+','.join(ATT_COLS)+') VALUES('+','.join('?' for _ in ATT_COLS)+') '
                              'ON CONFLICT(employee_code) DO NOTHING',tuple(r[k] for k in ATT_COLS))
                result['attendance_added']+=max(0,cur.rowcount)
            for r in n['schedules']:
                r=dict(r)
                if self.store.postgres:r['enabled']=bool(r['enabled'])
                cur=c.execute('INSERT INTO auto_schedules('+','.join(SCHEDULE_COLS)+') VALUES('+','.join('?' for _ in SCHEDULE_COLS)+') '
                              'ON CONFLICT(department) DO NOTHING',tuple(r[k] for k in SCHEDULE_COLS))
                result['schedules_added']+=max(0,cur.rowcount)
            result['archive_rows_added']=import_archive(c,pack)
        for r in n['departments']:self.ensure_schedule(r['code'])
        return result
