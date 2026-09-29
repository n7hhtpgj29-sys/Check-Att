"""Four Bangkok-relative views. Additive, dated rosters/results; no guessed history."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

BKK = ZoneInfo('Asia/Bangkok')
MODES = {'LAST_DAY': ('D', -1, 'Last Day'), 'DAY': ('D', 0, 'Today'),
         'LAST_NIGHT': ('N', -1, 'Last Night'), 'TONIGHT': ('N', 0, 'Tonight')}
FIELDS = ('employee_code','full_name','department','position','active','updated_at',
          'location_support','team_support','group_code','shift')

def bkk_now(): return datetime.now(BKK)
def encode(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), default=str)
def normalize_mode(value):
    mode = str(value or 'DAY').strip().upper().replace(' ','_')
    mode = {'TODAY':'DAY','TODAY_DAY':'DAY','TO_NIGHT':'TONIGHT'}.get(mode,mode)
    if mode not in MODES: raise ValueError('Select Last Day, Today, Last Night or Tonight.')
    return mode

def resolve_view(mode, when=None):
    mode=normalize_mode(mode); when=when or bkk_now()
    if when.tzinfo is None: raise ValueError('A timezone-aware reference time is required.')
    when=when.astimezone(BKK); sh,offset,label=MODES[mode]; wd=when.date()+timedelta(days=offset)
    end=wd+timedelta(days=1 if sh=='N' else 0)
    return dict(mode=mode,label=label,shift=sh,work_date=wd.isoformat(),end_date=end.isoformat(),
                date_label=wd.strftime('%d/%m/%Y')+((' → '+end.strftime('%d/%m/%Y')) if sh=='N' else ''),
                timezone='Asia/Bangkok',utc_offset='+07:00')

def fingerprint(employee):
    # Every committed master revision invalidates that current assignment, including D→N→D.
    raw=[str(employee.get(k,'')) for k in ('employee_code','department','shift','group_code','active','updated_at')]
    return hashlib.sha256(encode(raw).encode()).hexdigest()

class ShiftHistory:
    def __init__(self,store,clock=bkk_now): self.store,self.clock=store,clock
    def init(self):
        with self.store.tx(serial=True) as c:
            c.execute('CREATE TABLE IF NOT EXISTS shift_rosters ('
                      'department TEXT NOT NULL,work_date TEXT NOT NULL,shift TEXT NOT NULL,'
                      'captured_at TEXT NOT NULL,payload_json TEXT NOT NULL,'
                      'PRIMARY KEY(department,work_date,shift))')
            c.execute('CREATE TABLE IF NOT EXISTS shift_results ('
                      'department TEXT NOT NULL,work_date TEXT NOT NULL,shift TEXT NOT NULL,'
                      'employee_code TEXT NOT NULL,assignment_hash TEXT NOT NULL,'
                      'queried_at TEXT NOT NULL,payload_json TEXT NOT NULL,'
                      'PRIMARY KEY(department,work_date,shift,employee_code))')
            c.execute('CREATE TABLE IF NOT EXISTS query_journal ('
                      'job_id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,payload_json TEXT NOT NULL)')
            c.execute('CREATE INDEX IF NOT EXISTS shift_result_date_idx ON shift_results(work_date)')
            self.capture(c)
            self._migrate_today_cache(c)
        # Capture before & after every employee mutation IN its own transaction.
        self.store.roster_hook=self.capture
    def _migrate_today_cache(self,c):
        # A previous single-row cache has no verified historical roster.
        # Only current-day, not-modified-since-query records are safe to retain.
        now=self.clock();wd=now.date().isoformat();day_label=now.strftime('%d/%m/%Y')
        cache={r['employee_code']:dict(r) for r in c.execute('SELECT * FROM attendance WHERE work_date=?',(day_label,))}
        for r in c.execute('SELECT * FROM employees WHERE active=1'):
            e=dict(r);old=cache.get(e['employee_code'])
            if not old:continue
            try:
                queried=datetime.strptime(old['query_at'],'%d/%m/%Y %H:%M:%S').replace(tzinfo=BKK)
                updated=datetime.fromisoformat(e['updated_at'])
                if updated.tzinfo is None:updated=updated.replace(tzinfo=BKK)
                if queried<updated or queried.date()!=now.date():continue
                data={k:old.get(k,'') for k in ('status','name_from_web','latest_datetime','scan_in','scan_out','raw_count','ot_minutes','work_date')}
                if data['status'] not in ('PRESENT','NO SCAN TODAY','QUERY UNAVAILABLE'):continue
                c.execute('INSERT INTO shift_results(department,work_date,shift,employee_code,assignment_hash,queried_at,payload_json) '
                          'VALUES(?,?,?,?,?,?,?) ON CONFLICT(department,work_date,shift,employee_code) DO NOTHING',
                          (e['department'],wd,e['shift'],e['employee_code'],fingerprint(e),queried.isoformat(timespec='seconds'),encode(data)))
            except (ValueError,TypeError,KeyError):continue

    def capture(self,c):
        now=self.clock(); wd=now.astimezone(BKK).date().isoformat(); stamp=now.isoformat()
        deps=[r['code'] for r in c.execute('SELECT code FROM departments')]
        employees=[dict(r) for r in c.execute('SELECT '+','.join(FIELDS)+' FROM employees WHERE active=1 ORDER BY employee_code')]
        existing={(r['department'],r['shift']):r['payload_json'] for r in c.execute(
            'SELECT department,shift,payload_json FROM shift_rosters WHERE work_date=?',(wd,))}
        for dep in deps:
            for sh in ('D','N'):
                payload=encode([r for r in employees if r['department']==dep and r['shift']==sh])
                if existing.get((dep,sh))==payload:continue
                c.execute('INSERT INTO shift_rosters(department,work_date,shift,captured_at,payload_json) VALUES(?,?,?,?,?) '
                          'ON CONFLICT(department,work_date,shift) DO UPDATE SET '
                          'captured_at=excluded.captured_at,payload_json=excluded.payload_json',
                          (dep,wd,sh,stamp,payload))
    def capture_today(self):
        with self.store.tx(serial=True) as c:self.capture(c)
    def roster(self,department,wd,shift,c=None):
        if c is None:
            with self.store.tx() as conn:return self.roster(department,wd,shift,conn)
        r=c.execute('SELECT payload_json FROM shift_rosters WHERE department=? AND work_date=? AND shift=?',
                    (department,wd,shift)).fetchone()
        # None means unknown, [] means a known empty shift. Never confuse them.
        return json.loads(r[0]) if r else None
    def records(self,department,wd,shift,c=None):
        if c is None:
            with self.store.tx() as conn:return self.records(department,wd,shift,conn)
        rows=self.roster(department,wd,shift,c)
        if rows is None:return None
        scans={r['employee_code']:dict(r) for r in c.execute(
            'SELECT * FROM shift_results WHERE department=? AND work_date=? AND shift=?',(department,wd,shift))}
        out=[]
        for employee in rows:
            row={**employee,'work_date':date.fromisoformat(wd).strftime('%d/%m/%Y'),
                 'status':'NOT CHECKED','scan_in':'','scan_out':'','query_at':'','ot_minutes':0}
            saved=scans.get(employee['employee_code'])
            if saved and saved['assignment_hash']==fingerprint(employee):
                row.update(json.loads(saved['payload_json'])); row['query_at']=saved['queried_at']
                row['work_date']=date.fromisoformat(wd).strftime('%d/%m/%Y')
            out.append(row)
        return out
    def save_result(self,c,employee,wd,shift,result):
        c.execute('INSERT INTO shift_results(department,work_date,shift,employee_code,assignment_hash,queried_at,payload_json) '
                  'VALUES(?,?,?,?,?,?,?) ON CONFLICT(department,work_date,shift,employee_code) DO UPDATE SET '
                  'assignment_hash=excluded.assignment_hash,queried_at=excluded.queried_at,payload_json=excluded.payload_json',
                  (employee['department'],wd,shift,employee['employee_code'],fingerprint(employee),
                   self.clock().isoformat(timespec='seconds'),encode(result)))
    def save_job(self,jid,payload):
        with self.store.tx() as c:
            c.execute('INSERT INTO query_journal(job_id,updated_at,payload_json) VALUES(?,?,?) '
                      'ON CONFLICT(job_id) DO UPDATE SET updated_at=excluded.updated_at,payload_json=excluded.payload_json',
                      (jid,self.clock().isoformat(),encode(payload)))
            # Bounded UI journal; no removal of dated attendance or roster data.
            old=[r[0] for r in c.execute('SELECT job_id FROM query_journal ORDER BY updated_at DESC LIMIT 100000 OFFSET 200')]
            for key in old:c.execute('DELETE FROM query_journal WHERE job_id=?',(key,))
    def previous_jobs(self):
        with self.store.tx() as c:
            return {r['job_id']:json.loads(r['payload_json']) for r in c.execute('SELECT * FROM query_journal')}
