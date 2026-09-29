"""Add-only archive recovery for new dated rosters/results and schedule rules.
Runtime jobs are exported for audit, but not restarted by importing a backup.
"""
from __future__ import annotations
import json,re
from datetime import date
from shift_history import encode,FIELDS,fingerprint

TABLES={
 'shift_rosters':('department','work_date','shift','captured_at','payload_json'),
 'shift_results':('department','work_date','shift','employee_code','assignment_hash','queried_at','payload_json'),
 'schedule_profiles':('department','enabled','weekdays','updated_at'),
 'schedule_rules':('department','rule_id','mode','at_time','enabled','revision'),
}

def exists(c,table):return bool(list(c.execute('PRAGMA table_info('+table+')')))
def export_archive(c):
    return {table:[dict(r) for r in c.execute('SELECT * FROM '+table)] for table in (*TABLES,'timed_runs','query_journal') if exists(c,table)}

def validate_archive(pack):
    out={}
    for table,cols in TABLES.items():
        rows=pack.get(table,[])
        if not isinstance(rows,list) or len(rows)>250000:raise ValueError('Invalid archive table '+table)
        out[table]=[]
        for row in rows:
            if not isinstance(row,dict) or any(k not in row for k in cols):raise ValueError('Incomplete archive row '+table)
            d=str(row['department'])
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,23}',d) or d=='ALL':raise ValueError('Invalid archive department')
            r={k:row[k] for k in cols}
            if 'work_date' in r:
                date.fromisoformat(str(r['work_date']))
                if r['shift'] not in ('D','N'):raise ValueError('Invalid archive shift')
            if table=='shift_rosters':
                members=json.loads(r['payload_json'])
                if not isinstance(members,list) or len(members)>10000:raise ValueError('Invalid roster archive')
                seen=set()
                for e in members:
                    if not isinstance(e,dict) or not isinstance(e.get('employee_code'),str) or not e['employee_code'] or e.get('department')!=d or e.get('shift')!=r['shift']:raise ValueError('Roster archive mismatch')
                    if e['employee_code'] in seen:raise ValueError('Duplicate roster member')
                    seen.add(e['employee_code'])
                    if any(k not in e for k in FIELDS):raise ValueError('Incomplete roster member')
                r['payload_json']=encode(members)
            if table=='shift_results':
                data=json.loads(r['payload_json'])
                if not isinstance(data,dict):raise ValueError('Invalid scan archive')
                if data.get('status') not in ('PRESENT','NO SCAN TODAY','QUERY UNAVAILABLE','NO DATA FOR SHIFT','NOT STARTED','NOT CHECKED'):raise ValueError('Invalid scan archive status')
                data={k:v for k,v in data.items() if k in ('latest_datetime','status','name_from_web','scan_in','scan_out','raw_count','ot_minutes','work_date')}
                r['payload_json']=encode(data)
            if table=='schedule_profiles':
                if r['enabled'] not in (0,1):raise ValueError('Invalid schedule enabled')
                days=str(r['weekdays']).split(',')
                if not days or any(v not in list('0123456') for v in days):raise ValueError('Invalid weekdays')
            if table=='schedule_rules':
                from thai_schedule import hhmm
                from shift_history import normalize_mode
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',str(r['rule_id'])):raise ValueError('Invalid rule ID')
                hhmm(r['at_time']);normalize_mode(r['mode'])
                if r['enabled'] not in (0,1) or type(r['revision']) is not int or r['revision']<1:raise ValueError('Invalid rule revision')
            out[table].append(r)
    return out

def import_archive(c,pack):
    data=validate_archive(pack);added=0
    for table,cols in TABLES.items():
        if not exists(c,table):continue
        for row in data[table]:
            if not c.execute('SELECT code FROM departments WHERE code=?',(row['department'],)).fetchone():continue
            if table=='shift_results':
                rr=c.execute('SELECT payload_json FROM shift_rosters WHERE department=? AND work_date=? AND shift=?',
                             (row['department'],row['work_date'],row['shift'])).fetchone()
                e=next((e for e in json.loads(rr[0]) if e['employee_code']==row['employee_code']),None) if rr else None
                if not e or fingerprint(e)!=row['assignment_hash']:continue
            cur=c.execute('INSERT INTO '+table+'('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+') ON CONFLICT DO NOTHING',tuple(row[k] for k in cols))
            added+=max(0,cur.rowcount)
    return added
