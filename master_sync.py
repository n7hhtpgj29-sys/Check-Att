"""V12.1.2: department-scoped latest-file master, preview then atomic apply.

No employee is physically deleted. Omissions become inactive. Cross-department
moves require explicit confirmation. PostgreSQL uses the existing Store/schema.
Do not log workbook contents, passwords, preview tokens or backup JSON.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import PurePath

FIELDS = ('employee_code','full_name','department','position','active','updated_at',
          'location_support','team_support','group_code','shift')
EDIT_FIELDS = ('full_name','location_support','team_support','group_code','shift')
MAX_ROWS = 10000
MAX_UPLOAD = 5 * 1024 * 1024
PREVIEW_MINUTES = 20

class MasterSyncError(ValueError):
    def __init__(self, message, code='INVALID_INPUT', status=400):
        super().__init__(message)
        self.code, self.status = code, status

def text(value):
    if value is None: return ''
    if isinstance(value, float) and value.is_integer(): return str(int(value))
    return str(value).strip()

def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), default=str)

def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()

def dep(value):
    d = text(value).upper()
    if d == 'ALL' or not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,23}', d):
        raise MasterSyncError('เลือกแผนกเดียวก่อนอัปโหลด / Select a specific department.')
    return d

def parse_workbook(blob: bytes, filename: str, department: str, sheet_name: str = ''):
    """Application Excel reader; formulas are rejected instead of using stale caches."""
    from openpyxl import load_workbook  # Existing deployed application's dependency.
    d = dep(department)
    filename = PurePath(filename.replace('\\','/')).name[:200]
    if not filename.lower().endswith('.xlsx'):
        raise MasterSyncError('ใช้ไฟล์ .xlsx เท่านั้น')
    if not blob or len(blob) > MAX_UPLOAD:
        raise MasterSyncError('ไฟล์ว่างหรือเกิน 5 MB')
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            members = z.infolist()
            if len(members) > 3000 or sum(m.file_size for m in members) > 50 * 1024 * 1024:
                raise MasterSyncError('Workbook ใหญ่เกินขอบเขตที่รองรับ')
            if any('vbaproject' in m.filename.lower() for m in members):
                raise MasterSyncError('ไม่รองรับไฟล์ที่มี macro')
        wb = load_workbook(io.BytesIO(blob), read_only=True, data_only=False, keep_links=False)
    except MasterSyncError: raise
    except Exception:
        raise MasterSyncError('อ่าน Excel ไม่ได้: ไฟล์ไม่ใช่ .xlsx ที่สมบูรณ์') from None
    try:
        sheets = wb.sheetnames
        chosen = sheet_name or sheets[0]
        if chosen not in sheets: raise MasterSyncError('ไม่พบชีตที่เลือก')
        ws = wb[chosen]
        if (ws.max_row or 0) > MAX_ROWS + 1 or (ws.max_column or 0) > 64:
            raise MasterSyncError('รองรับไม่เกิน 10,000 แถวและ 64 คอลัมน์ต่อชีต')
        def header(v): return re.sub(r'[^a-z0-9ก-๙]+','_',text(v).lower()).strip('_')
        hs = [header(c.value) for c in next(ws.iter_rows(min_row=1,max_row=1), [])]
        aliases = {
            'employee_code': ['employee_code','employee_no','emp_no','empno','รหัสพนักงาน'],
            'full_name': ['full_name','name','employee_name','ชื่อ','ชื่อพนักงาน'],
            'location_support': ['location_support','location','support_location'],
            'team_support': ['team_support','team','support_team'],
            'group_code': ['group','group_code','group_support'],
            'shift': ['shift','shift_code'],
            'department': ['department','dept','แผนก'],
            'active': ['active','is_active'],
        }
        idx = {}
        for key, names in aliases.items():
            matches = [i for i,h in enumerate(hs) if h in names]
            if len(matches)>1: raise MasterSyncError('หัวคอลัมน์ซ้ำ: '+key)
            if matches: idx[key] = matches[0]
        required = ('employee_code',)+EDIT_FIELDS
        missing = [k for k in required if k not in idx]
        if missing: raise MasterSyncError('ขาดหัวคอลัมน์: '+', '.join(missing))
        incoming = {}
        for line, cells in enumerate(ws.iter_rows(min_row=2), 2):
            values = {k:text(cells[i].value) if i<len(cells) else '' for k,i in idx.items()}
            if not any(values.get(k) for k in required): continue
            for key, i in idx.items():
                if i<len(cells) and cells[i].data_type=='f':
                    raise MasterSyncError(f'แถว {line}: {key} เป็นสูตร กรุณา Paste values ก่อน')
            code = values['employee_code'].upper()
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9_.-]{0,79}', code):
                raise MasterSyncError(f'แถว {line}: รหัสพนักงานว่างหรือไม่ถูกต้อง')
            if code in incoming: raise MasterSyncError(f'รหัสซ้ำในไฟล์: {code} (แถว {line})')
            if not values['full_name']: raise MasterSyncError(f'แถว {line}: ไม่มีชื่อของ {code}')
            sh = values['shift'].upper()
            if sh not in ('D','N'): raise MasterSyncError(f'แถว {line}: Shift ของ {code} ต้องเป็น D หรือ N')
            if any(len(values[k])>250 for k in EDIT_FIELDS):
                raise MasterSyncError(f'แถว {line}: ข้อความยาวเกิน 250 ตัวอักษร')
            if values.get('department') and values['department'].upper()!=d:
                raise MasterSyncError(f'แถว {line}: Department ในไฟล์ไม่ตรงกับ {d}')
            av = values.get('active','').lower()
            if av in ('','1','true','yes','y','active','on'): active=1
            elif av in ('0','false','no','n','inactive','off'): active=0
            else: raise MasterSyncError(f'แถว {line}: Active ใช้ YES/NO หรือ 1/0 หรือปล่อยว่าง')
            incoming[code] = dict(employee_code=code, full_name=values['full_name'],
                department=d, location_support=values['location_support'], team_support=values['team_support'],
                group_code=values['group_code'].upper(), shift=sh, active=active)
        if not incoming: raise MasterSyncError('ไฟล์ไม่มีรายชื่อ ไม่อนุญาตให้ล้างแผนกด้วยไฟล์ว่าง')
        m = re.match(r'^([A-Za-z][A-Za-z0-9-]{0,23})[ _-]+(?:STAFF|MASTER|EMPLOYEES?)\b',filename,re.I)
        hint = m.group(1).upper() if m else ''
        warnings = []
        if len(sheets)>1: warnings.append(f'อ่านเฉพาะชีต {chosen}; ไม่รวมชีตอื่น')
        if hint and hint!=d: warnings.append(f'ชื่อไฟล์ดูเป็นแผนก {hint} แต่เลือก {d}: ตรวจสอบก่อนยืนยัน')
        if not any(r['active'] for r in incoming.values()):
            warnings.append('ไฟล์นี้จะทำให้แผนกไม่มีพนักงาน Active')
        return dict(filename=filename, sheet=chosen, sheets=sheets, department=d,
                    filename_department=hint, filename_mismatch=bool(hint and hint!=d), warnings=warnings,
                    file_sha256=hashlib.sha256(blob).hexdigest(), rows=list(incoming.values()))
    finally: wb.close()

class MasterSync:
    def __init__(self, store): self.store=store
    def init(self):
        with self.store.tx(serial=True) as c:
            c.execute('CREATE TABLE IF NOT EXISTS master_sync_previews('
                'token_hash TEXT PRIMARY KEY,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,'
                'department TEXT NOT NULL,payload_json TEXT NOT NULL,snapshot_hash TEXT NOT NULL,'
                "status TEXT NOT NULL DEFAULT 'preview',audit_id TEXT DEFAULT '')")
            c.execute('CREATE TABLE IF NOT EXISTS master_sync_audits('
                'id TEXT PRIMARY KEY,created_at TEXT NOT NULL,department TEXT NOT NULL,'
                'filename TEXT NOT NULL,summary_json TEXT NOT NULL,backup_json TEXT NOT NULL)')

    def _master(self,c):
        employees = [dict(x) for x in c.execute('SELECT '+','.join(FIELDS)+' FROM employees ORDER BY employee_code')]
        departments = [dict(x) for x in c.execute('SELECT * FROM departments ORDER BY code')]
        return dict(employees=employees, departments=departments)

    def _plan(self, master, pack):
        d=pack['department']; existing={x['employee_code']:x for x in master['employees']}
        if not any(x['code']==d and x['active'] for x in master['departments']):
            raise MasterSyncError('ไม่พบแผนกที่เลือก กรุณาเพิ่ม Department ก่อน')
        changes=[]; counts=dict(add=0,update=0,reactivate=0,transfer=0,deactivate=0,unchanged=0,shift_change=0)
        def append(kind, old, new, reason, fields):
            r=new or old
            counts[kind]+=1
            changes.append(dict(action=kind, employee_code=r['employee_code'],full_name=r['full_name'],
                from_department=old['department'] if old else '', to_department=new['department'] if new else d,
                old_shift=old['shift'] if old else '',new_shift=new['shift'] if new else old['shift'],
                old_active=int(old['active']) if old else None,new_active=int(new['active']) if new else 0,
                fields=fields,reason=reason,field_changes=[dict(field=k,before=old.get(k,'') if old else '',after=new.get(k,'') if new else (0 if k=='active' else old.get(k,''))) for k in fields]))
        incoming={r['employee_code']:r for r in pack['rows']}
        for code,new in incoming.items():
            old=existing.get(code)
            fields=[k for k in EDIT_FIELDS+('active',) if old is not None and text(old.get(k))!=text(new.get(k))]
            if old and old['shift']!=new['shift']: counts['shift_change']+=1
            if not old: append('add',None,new,'เพิ่มรหัสใหม่',list(EDIT_FIELDS))
            elif old['department']!=d: append('transfer',old,new,'ย้ายจาก '+old['department']+' → '+d,['department']+fields)
            elif int(old['active']) and not new['active']: append('deactivate',old,new,'Active=NO ในไฟล์',fields)
            elif not int(old['active']) and new['active']: append('reactivate',old,new,'เปิดใช้งานกลับ',fields)
            elif fields: append('update',old,new,'ปรับข้อมูลตามไฟล์',fields)
            else: counts['unchanged']+=1
        for old in master['employees']:
            if old['department']==d and int(old['active']) and old['employee_code'] not in incoming:
                append('deactivate',old,None,'ไม่อยู่ในไฟล์ล่าสุด', ['active'])
        return dict(department=d, filename=pack['filename'],sheet=pack['sheet'],sheets=pack['sheets'],
            warnings=pack['warnings'],filename_mismatch=pack['filename_mismatch'],
            filename_department=pack['filename_department'],file_rows=len(incoming),
            active_before=sum(x['department']==d and int(x['active']) for x in master['employees']),
            active_after=sum(r['active'] for r in incoming.values()),counts=counts,changes=changes,
            affected_departments=sorted({d}|{x['from_department'] for x in changes if x['action']=='transfer'}))

    def preview(self,blob,filename,department,sheet=''):
        pack=parse_workbook(blob,filename,department,sheet)
        token=secrets.token_urlsafe(32); h=hashlib.sha256(token.encode()).hexdigest()
        now=datetime.now(timezone.utc); expires=now+timedelta(minutes=PREVIEW_MINUTES)
        with self.store.tx(serial=True) as c:
            master=self._master(c); plan=self._plan(master,pack)
            c.execute("DELETE FROM master_sync_previews WHERE expires_at<? AND status='preview'",(now.isoformat(),))
            c.execute('DELETE FROM master_sync_previews WHERE created_at<?',((now-timedelta(days=1)).isoformat(),))
            c.execute('INSERT INTO master_sync_previews(token_hash,created_at,expires_at,department,payload_json,snapshot_hash) '
                      'VALUES(?,?,?,?,?,?)',(h,now.isoformat(),expires.isoformat(),pack['department'],encode(pack),digest(master)))
        return dict(ok=True,preview_token=token,expires_at=expires.isoformat(),**plan)

    def apply(self, token, confirmation):
        if not isinstance(token,str) or len(token)<20 or len(token)>160:
            raise MasterSyncError('กรุณา Preview ไฟล์ก่อน', 'PREVIEW_REQUIRED',409)
        h=hashlib.sha256(token.encode()).hexdigest()
        with self.store.tx(serial=True) as c:
            row=c.execute('SELECT * FROM master_sync_previews WHERE token_hash=?',(h,)).fetchone()
            if not row: raise MasterSyncError('Preview หมดอายุ กรุณาเลือกไฟล์ใหม่','PREVIEW_EXPIRED',409)
            row=dict(row)
            if text(confirmation.get('confirm_department')).upper()!=row['department']:
                raise MasterSyncError('พิมพ์ชื่อแผนกเพื่อยืนยันให้ตรงกัน','CONFIRM_DEPARTMENT',400)
            if row['status']=='applied':
                a=c.execute('SELECT summary_json FROM master_sync_audits WHERE id=?',(row['audit_id'],)).fetchone()
                if a: return dict(ok=True,replayed=True,audit_id=row['audit_id'],**json.loads(a[0]))
                raise MasterSyncError('งานนี้บันทึกไปแล้ว กรุณา Refresh','ALREADY_APPLIED',409)
            if datetime.now(timezone.utc)>datetime.fromisoformat(row['expires_at']):
                raise MasterSyncError('Preview เกิน 20 นาที กรุณา Preview ใหม่','PREVIEW_EXPIRED',409)
            master=self._master(c)
            if not hmac.compare_digest(digest(master),row['snapshot_hash']):
                raise MasterSyncError('ข้อมูลแผนกหรือรายชื่อถูกแก้หลัง Preview กรุณา Preview ใหม่ ไม่ได้บันทึกทับ','STALE_PREVIEW',409)
            pack=json.loads(row['payload_json']); plan=self._plan(master,pack)
            for count,key,msg in [(plan['counts']['deactivate'],'ack_remove','ยืนยันรายชื่อที่จะปิดใช้งาน'),
                                   (plan['counts']['transfer'],'ack_transfer','ยืนยันการย้ายแผนก'),
                                   (plan['filename_mismatch'],'ack_filename','ยืนยันชื่อไฟล์ที่ไม่ตรงแผนก')]:
                if count and confirmation.get(key) is not True: raise MasterSyncError(msg,'CONFIRM_REQUIRED',400)
            # A complete before-image in the same transaction; includes query results at commit time.
            backup=dict(ok=True,format='cc-attendance-all-v1211',version='12.1.2',exported_at=timestamp(),**master)
            for table in ('attendance','auto_schedules'):
                backup[table]=[dict(x) for x in c.execute('SELECT * FROM '+table)]
            from shift_backup import export_archive
            backup.update(export_archive(c))
            oldmap={r['employee_code']:r for r in master['employees']}
            changed={r['employee_code'] for r in plan['changes']}
            now=timestamp(); invalidated=0
            for r in pack['rows']:
                if r['employee_code'] not in changed: continue
                old=oldmap.get(r['employee_code'])
                position=old.get('position','') if old else ''
                c.execute('INSERT INTO employees('+','.join(FIELDS)+') VALUES('+','.join('?' for _ in FIELDS)+') '
                          'ON CONFLICT(employee_code) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in FIELDS[1:]),
                          tuple(dict(r,position=position,updated_at=now).get(k,'') for k in FIELDS))
                # Never show a cached PRESENT from the old shift/department as the new assignment.
                if old and (old['department']!=r['department'] or old['shift']!=r['shift'] or
                            old['group_code']!=r['group_code'] or (not old['active'] and r['active'])):
                    invalidated+=max(0,c.execute('DELETE FROM attendance WHERE employee_code=?',(r['employee_code'],)).rowcount)
            incoming={r['employee_code'] for r in pack['rows']}
            for change in plan['changes']:
                if change['action']=='deactivate' and change['employee_code'] not in incoming:
                    c.execute('UPDATE employees SET active=0,updated_at=? WHERE employee_code=? AND department=?',
                              (now,change['employee_code'],pack['department']))
            audit_id=secrets.token_hex(16)
            summary={k:v for k,v in plan.items() if k not in ('changes','warnings','sheets')}
            summary.update(applied_at=now,attendance_cache_reset=invalidated)
            c.execute('INSERT INTO master_sync_audits(id,created_at,department,filename,summary_json,backup_json) '
                      'VALUES(?,?,?,?,?,?)',(audit_id,now,pack['department'],pack['filename'],encode(summary),encode(backup)))
            c.execute("UPDATE master_sync_previews SET status='applied',audit_id=?,payload_json='{}' WHERE token_hash=?",(audit_id,h))
            # Retain the newest 20 pre-import backups; never delete employee/history tables.
            older=[r[0] for r in c.execute('SELECT id FROM master_sync_audits ORDER BY created_at DESC LIMIT 100000 OFFSET 20')]
            for id_ in older: c.execute('DELETE FROM master_sync_audits WHERE id=?',(id_,))
        return dict(ok=True,replayed=False,audit_id=audit_id,**summary)

    def history(self,department):
        d=dep(department)
        with self.store.tx() as c:
            rows=[dict(x) for x in c.execute('SELECT id,created_at,filename,summary_json FROM master_sync_audits '
                                           'WHERE department=? ORDER BY created_at DESC LIMIT 20',(d,))]
        return dict(ok=True,imports=[dict(id=x['id'],created_at=x['created_at'],filename=x['filename'],
                                         summary=json.loads(x['summary_json'])) for x in rows])

    def backup(self,id_):
        if not re.fullmatch('[a-f0-9]{32}',id_): raise MasterSyncError('ไม่พบ Backup','NOT_FOUND',404)
        with self.store.tx() as c:r=c.execute('SELECT backup_json FROM master_sync_audits WHERE id=?',(id_,)).fetchone()
        if not r: raise MasterSyncError('ไม่พบ Backup (เก็บ 20 รอบล่าสุด)','NOT_FOUND',404)
        return json.loads(r[0])


def register_master_sync(app,store,query_lock):
    from flask import request,jsonify
    sync=MasterSync(store);sync.init()
    def guard():
        # Optional existing-access hardening without changing the unattended Query token.
        configured=os.getenv('MASTER_ADMIN_PASSWORD','')
        if configured and not hmac.compare_digest(configured,request.headers.get('X-Master-Admin-Key','')):
            raise MasterSyncError('ต้องใช้รหัส Master Admin','ADMIN_REQUIRED',401)
        origin=request.headers.get('Origin','')
        if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):
            raise MasterSyncError('ต้องเรียกจากหน้าเว็บ Attendance เดียวกัน','CROSS_ORIGIN',403)
    @app.errorhandler(MasterSyncError)
    def sync_error(exc): return jsonify(ok=False,error=str(exc),code=exc.code),exc.status
    @app.post('/api/master-sync/preview')
    def preview_route():
        guard();f=request.files.get('file')
        if not f: raise MasterSyncError('เลือก Excel ก่อน')
        return jsonify(sync.preview(f.read(MAX_UPLOAD+1),f.filename,request.form.get('department'),request.form.get('sheet','')))
    @app.post('/api/master-sync/apply')
    def apply_route():
        guard();x=request.get_json(silent=True) or {}
        if not isinstance(x,dict): raise MasterSyncError('Invalid JSON')
        if not query_lock.acquire(blocking=False):
            raise MasterSyncError('กำลัง Query กรุณารอให้เสร็จแล้วกดยืนยันอีกครั้ง','QUERY_BUSY',409)
        try:return jsonify(sync.apply(x.get('preview_token'),x))
        finally:query_lock.release()
    @app.get('/api/master-sync/history')
    def history_route():
        guard();return jsonify(sync.history(request.args.get('department')))
    @app.get('/api/master-sync/audit/<audit_id>/backup')
    def backup_route(audit_id):
        guard();res=jsonify(sync.backup(audit_id))
        res.headers['Content-Disposition']='attachment; filename="CC_Attendance_before_'+audit_id+'.json"'
        return res
    return sync
