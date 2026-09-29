"""Department-owned Thai schedules, atomic claims and pinned shift dates.
The GitHub scheduler remains the caller; UTC scheduling never leaks into form times.
"""
from __future__ import annotations
import hashlib,json,re
from datetime import datetime,timedelta,date,time
from shift_history import BKK,bkk_now,resolve_view,normalize_mode,encode

DEFAULT_RULES=(('day1','DAY','08:15',True),('day2','DAY','18:00',True),
               ('night1','TONIGHT','20:15',True),('night_final','LAST_NIGHT','06:00',True),
               ('last_day','LAST_DAY','07:00',False))

def hhmm(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):
        raise ValueError('Use Thai time in 24-hour HH:MM format, e.g. 16:40.')
    return value

def boolval(v):
    if type(v) is bool:return v
    if v in (0,1):return bool(v)
    raise ValueError('enabled must be true or false.')

class ThaiSchedules:
    def __init__(self,store,clock=bkk_now,grace=180):self.store,self.clock,self.grace=store,clock,grace
    def init(self):
        with self.store.tx(serial=True) as c:
            c.execute('CREATE TABLE IF NOT EXISTS schedule_profiles ('
                      'department TEXT PRIMARY KEY,enabled INTEGER NOT NULL,weekdays TEXT NOT NULL,updated_at TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS schedule_rules ('
                      'department TEXT NOT NULL,rule_id TEXT NOT NULL,mode TEXT NOT NULL,at_time TEXT NOT NULL,'
                      'enabled INTEGER NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(department,rule_id))')
            c.execute('CREATE TABLE IF NOT EXISTS timed_runs ('
                      'department TEXT NOT NULL,slot_key TEXT NOT NULL,slot_date TEXT NOT NULL,mode TEXT NOT NULL,'
                      'work_date TEXT NOT NULL,scheduled_at TEXT NOT NULL,status TEXT NOT NULL,claimed_at TEXT NOT NULL,'
                      "started_at TEXT NOT NULL DEFAULT '',finished_at TEXT NOT NULL DEFAULT '',job_id TEXT NOT NULL DEFAULT '',"
                      "message TEXT NOT NULL DEFAULT '',late_minutes INTEGER NOT NULL DEFAULT 0,"
                      'PRIMARY KEY(department,slot_key,slot_date))')
            c.execute('CREATE TABLE IF NOT EXISTS scheduler_contact (id TEXT PRIMARY KEY,at_time TEXT NOT NULL,source TEXT NOT NULL)')
            for row in list(c.execute('SELECT * FROM auto_schedules')):self._ensure(c,row['department'])
    def _ensure(self,c,dep):
        if c.execute('SELECT department FROM schedule_profiles WHERE department=?',(dep,)).fetchone():return
        legacy=c.execute('SELECT * FROM auto_schedules WHERE department=?',(dep,)).fetchone()
        if legacy is None:raise ValueError('Select an existing department first.')
        c.execute('INSERT INTO schedule_profiles VALUES(?,?,?,?) ON CONFLICT(department) DO NOTHING',
                  (dep,int(bool(legacy['enabled'])),str(legacy['weekdays']),self.clock().isoformat()))
        keys=('day1_time','day2_time','night1_time','night_final_time')
        for n,(id_,mode,at,en) in enumerate(DEFAULT_RULES):
            at=hhmm(str(legacy[keys[n]])) if n<4 else at
            c.execute('INSERT INTO schedule_rules VALUES(?,?,?,?,?,?) ON CONFLICT(department,rule_id) DO NOTHING',
                      (dep,id_,mode,at,int(en),1))
            # An already-completed V12.1 slot must not rerun just because code was upgraded.
            if n<4:
                for old in list(c.execute("SELECT * FROM auto_query_runs WHERE department=? AND slot_key=? AND status='done'",(dep,id_))):
                    day=date.fromisoformat(str(old['slot_date'])[:10]); stamp=datetime.combine(day,time.fromisoformat(at),BKK)
                    view=resolve_view(mode,stamp)
                    c.execute('INSERT INTO timed_runs(department,slot_key,slot_date,mode,work_date,scheduled_at,status,claimed_at,finished_at,job_id,message) '
                              'VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(department,slot_key,slot_date) DO NOTHING',
                              (dep,id_+'.v1',day.isoformat(),mode,view['work_date'],stamp.isoformat(),'done',
                               str(old['started_at'] or stamp.isoformat()),str(old['finished_at'] or ''),str(old['job_id'] or ''),'Migrated completed V12.1 slot'))
    def _get(self,c,dep):
        self._ensure(c,dep)
        p=dict(c.execute('SELECT * FROM schedule_profiles WHERE department=?',(dep,)).fetchone())
        rules=[dict(r) for r in c.execute('SELECT * FROM schedule_rules WHERE department=? ORDER BY rule_id',(dep,))]
        p['enabled']=bool(p['enabled']);p['weekdays']=[int(v) for v in p['weekdays'].split(',') if v!='']
        p['slots']=[dict(id=r['rule_id'],mode=r['mode'],time=r['at_time'],enabled=bool(r['enabled']),revision=r['revision']) for r in rules]
        p['timezone']='Asia/Bangkok';p['weekday_basis']='execution_date'
        p['etag']=hashlib.sha256(encode(p).encode()).hexdigest()
        return p
    def get(self,dep):
        with self.store.tx(serial=True) as c:return self._get(c,dep)
    def save(self,dep,payload):
        enabled=boolval(payload.get('enabled',False)); days=payload.get('weekdays',[])
        if not isinstance(days,list) or not days or any(type(d) is not int or not 0<=d<=6 for d in days):
            raise ValueError('Select execution weekdays Mon–Sun (0–6).')
        raw=payload.get('slots')
        if not isinstance(raw,list) or not 1<=len(raw)<=12:raise ValueError('Use 1–12 query slots.')
        slots=[];ids=set();semantics=set()
        for r in raw:
            if not isinstance(r,dict):raise ValueError('Invalid slot.')
            id_=str(r.get('id',''))
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',id_) or id_ in ids:raise ValueError('Invalid or duplicate slot ID.')
            ids.add(id_);mode=normalize_mode(r.get('mode'));at=hhmm(r.get('time'));on=boolval(r.get('enabled',True))
            if on and (mode,at) in semantics:raise ValueError('Two enabled slots have the same mode and time.')
            if on:semantics.add((mode,at))
            slots.append(dict(id=id_,mode=mode,time=at,enabled=on))
        with self.store.tx(serial=True) as c:
            before=self._get(c,dep)
            if payload.get('etag')!=before['etag']:raise ValueError('Schedule changed. Reopen Settings before saving (no changes applied).')
            olds={r['id']:r for r in before['slots']}
            for r in slots:
                old=olds.get(r['id']); rev=old['revision'] if old else 1
                # New time/mode = a new occurrence, even when the earlier time ran today.
                if old and (r['time'],r['mode'])!=(old['time'],old['mode']):rev+=1
                c.execute('INSERT INTO schedule_rules VALUES(?,?,?,?,?,?) ON CONFLICT(department,rule_id) DO UPDATE SET '
                          'mode=excluded.mode,at_time=excluded.at_time,enabled=excluded.enabled,revision=excluded.revision',
                          (dep,r['id'],r['mode'],r['time'],int(r['enabled']),rev))
            for id_ in olds.keys()-ids:
                c.execute('UPDATE schedule_rules SET enabled=0 WHERE department=? AND rule_id=?',(dep,id_))
            c.execute('UPDATE schedule_profiles SET enabled=?,weekdays=?,updated_at=? WHERE department=?',
                      (int(enabled),','.join(map(str,sorted(set(days)))),self.clock().isoformat(timespec='seconds'),dep))
            return self._get(c,dep)
    def _occurrence(self,dep,slot,day):
        stamp=datetime.combine(day,time.fromisoformat(slot['time']),BKK);v=resolve_view(slot['mode'],stamp)
        return dict(department=dep,slot_key=slot['id']+'.v'+str(slot['revision']),slot_date=day.isoformat(),
                    mode=v['mode'],label=v['label'],work_date=v['work_date'],scheduled_at=stamp.isoformat(timespec='seconds'))
    def _state(self,c,o):
        return c.execute('SELECT * FROM timed_runs WHERE department=? AND slot_key=? AND slot_date=?',
                         (o['department'],o['slot_key'],o['slot_date'])).fetchone()
    def due(self,source='GITHUB'):
        now=self.clock();tasks=[]
        with self.store.tx(serial=True) as c:
            c.execute('INSERT INTO scheduler_contact VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET at_time=excluded.at_time,source=excluded.source',
                      ('last',now.isoformat(timespec='seconds'),str(source)[:60]))
            deps=[r[0] for r in c.execute('SELECT code FROM departments WHERE active=1')]
            for dep in deps:
                p=self._get(c,dep)
                if not p['enabled']:continue
                for day in (now.date()-timedelta(days=1),now.date()):
                    if day.weekday() not in p['weekdays']:continue
                    for slot in p['slots']:
                        if not slot['enabled']:continue
                        o=self._occurrence(dep,slot,day);stamp=datetime.fromisoformat(o['scheduled_at']);age=(now-stamp).total_seconds()/60
                        if not 0<=age<=self.grace:continue
                        if getattr(self,'roster',None):
                            members=self.roster(dep,o['work_date'],resolve_view(slot['mode'],stamp)['shift'],c)
                            if not members:continue  # Unknown or empty shift does not consume its occurrence.
                        old=self._state(c,o)
                        if old:
                            if old['status']=='done':continue
                            if old['status'] in ('claimed','running') and (now-datetime.fromisoformat(old['claimed_at'])).total_seconds()<3600:continue
                        c.execute('INSERT INTO timed_runs(department,slot_key,slot_date,mode,work_date,scheduled_at,status,claimed_at,late_minutes) '
                                  "VALUES(?,?,?,?,?,?,'claimed',?,?) ON CONFLICT(department,slot_key,slot_date) DO UPDATE SET "
                                  "status='claimed',claimed_at=excluded.claimed_at,started_at='',finished_at='',job_id='',message='',late_minutes=excluded.late_minutes",
                                  (dep,o['slot_key'],o['slot_date'],o['mode'],o['work_date'],o['scheduled_at'],now.isoformat(),int(age)))
                        o['late_minutes']=int(age);tasks.append(o)
        return sorted(tasks,key=lambda t:(t['scheduled_at'],t['department'],t['slot_key']))
    def claimed(self,dep,key,day):
        with self.store.tx() as c:
            row=c.execute('SELECT * FROM timed_runs WHERE department=? AND slot_key=? AND slot_date=?',(dep,key,day)).fetchone()
            if not row or row['status'] not in ('claimed','running'):raise ValueError('Auto slot not claimed or already completed.')
            return dict(row)
    def attach(self,dep,key,day,jid):
        with self.store.tx(serial=True) as c:
            c.execute('UPDATE timed_runs SET job_id=? WHERE department=? AND slot_key=? AND slot_date=?',(jid,dep,key,day))
    def job_state(self,jid,payload):
        status=payload['status'];stamp=self.clock().isoformat(timespec='seconds')
        with self.store.tx() as c:
            if status=='running':
                c.execute("UPDATE timed_runs SET status='running',started_at=? WHERE job_id=? AND started_at=''",(payload.get('started_at',stamp),jid))
            elif status in ('done','error'):
                c.execute('UPDATE timed_runs SET status=?,finished_at=?,message=? WHERE job_id=?',
                          (status,payload.get('finished_at',stamp),str(payload.get('message',''))[:500],jid))
    def complete(self,dep,key,day,status,jid='',message=''):
        # Do not allow a late failure report to demote an already-done occurrence.
        with self.store.tx(serial=True) as c:
            row=c.execute('SELECT * FROM timed_runs WHERE department=? AND slot_key=? AND slot_date=?',(dep,key,day)).fetchone()
            if not row or row['status']=='done':return
            if row['job_id'] and row['job_id']!=jid:raise ValueError('Job ID does not match the scheduled run.')
            c.execute('UPDATE timed_runs SET status=?,job_id=?,finished_at=?,message=? WHERE department=? AND slot_key=? AND slot_date=?',
                      ('done' if status=='done' else 'error',jid,self.clock().isoformat(timespec='seconds'),str(message)[:500],dep,key,day))
    def diagnostics(self,dep):
        now=self.clock();nexts=[];due=[];skipped=[]
        with self.store.tx(serial=True) as c:
            p=self._get(c,dep)
            if p['enabled']:
                for off in range(-1,8):
                    day=now.date()+timedelta(days=off)
                    if day.weekday() not in p['weekdays']:continue
                    for slot in p['slots']:
                        if not slot['enabled']:continue
                        o=self._occurrence(dep,slot,day);state=self._state(c,o)
                        if state and state['status']=='done':continue
                        at=datetime.fromisoformat(o['scheduled_at']);age=(now-at).total_seconds()/60
                        o['status']=state['status'] if state else 'waiting';o['late_minutes']=max(0,int(age))
                        if at>now:nexts.append(o)
                        elif age<=self.grace:
                            roster=self.roster(dep,o['work_date'],resolve_view(slot['mode'],at)['shift'],c) if getattr(self,'roster',None) else [1]
                            if roster:due.append(o)
                            else:
                                o['reason']='ไม่มีรายชื่อกะที่บันทึกไว้' if roster is None else 'กะนี้ไม่มีพนักงาน'
                                skipped.append(o)
            runs=[dict(r) for r in c.execute('SELECT * FROM timed_runs WHERE department=? ORDER BY claimed_at DESC LIMIT 10',(dep,))]
            contact=c.execute("SELECT * FROM scheduler_contact WHERE id='last'").fetchone()
        pending=sorted(due,key=lambda r:r['scheduled_at'])
        nxt=min(nexts,key=lambda r:r['scheduled_at']) if nexts else None
        if nxt:nxt['at']=nxt['scheduled_at']
        return dict(schedule=p,server_time=now.isoformat(timespec='seconds'),timezone='Asia/Bangkok',
                    next_run=nxt,pending=pending,skipped=skipped,last_run=runs[0] if runs else None,recent_runs=runs,
                    scheduler_contact=dict(contact) if contact else None)
