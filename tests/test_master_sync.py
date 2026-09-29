"""Master-sync tests with real SQLite transactions and XLSX parser.
Flask route integration uses the project's test double; no MIS/cloud writes.
"""
import copy
import hashlib
import io
import json
import os
import sqlite3
import sys
import threading
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from master_sync import MasterSync,MasterSyncError,parse_workbook,FIELDS,encode
from persistent_store import Store
from test_persistence import app, fake_flask, emp as legacy_emp

@pytest.fixture
def sync(app): return app.master_sync

def seed(app,code='E001',department='PE',shift='D',active=1,**kwargs):
    app.ensure_department(department)
    data=dict(employee_code=code,full_name='Employee '+code,department=department,position='',active=active,
              updated_at='2026-09-01T08:00:00',location_support='F10',team_support='TEAM',group_code='A',shift=shift)
    data.update(kwargs)
    with app.store.tx(serial=True) as c:
        c.execute('INSERT INTO employees('+','.join(FIELDS)+') VALUES('+','.join('?' for _ in FIELDS)+')',tuple(data[k] for k in FIELDS))
    return data

def pack(rows,department='PE',filename='PE STAFF.xlsx'):
    return dict(filename=filename,sheet='Sheet1',sheets=['Sheet1'],department=department,
                warnings=[],filename_department=department,filename_mismatch=False,file_sha256='TEST',rows=rows)

def row(code='E001',shift='D',active=1,department='PE',name=None,group='A'):
    return dict(employee_code=code,full_name=name or 'Employee '+code,department=department,
                location_support='F10',team_support='TEAM',group_code=group,shift=shift,active=active)

def preview(sync,rows,department='PE',**extra):
    p=pack(rows,department);p.update(extra)
    with patch('master_sync.parse_workbook',return_value=p):
        return sync.preview(b'fake','.xlsx',department)

def commit(sync,prev,**override):
    c=dict(confirm_department=prev['department'],ack_remove=True,ack_transfer=True,ack_filename=True)
    c.update(override)
    return sync.apply(prev['preview_token'],c)

def current(app):
    with app.store.tx() as c:return {x['employee_code']:dict(x) for x in c.execute('SELECT * FROM employees')}

def att(app,code):
    with app.store.tx() as c:
        c.execute("INSERT INTO attendance(employee_code,status,query_at,scan_in,scan_out) VALUES(?,'PRESENT','29/09/2026 08:15:00','X','Y')",(code,))

def test_preview_does_not_mutate_master(app,sync):
    seed(app);before=current(app)
    p=preview(sync,[row(shift='N'),row('E002')]);assert p['counts']['add']==1 and p['counts']['shift_change']==1
    assert current(app)==before

def test_latest_file_updates_adds_omits_and_preserves_departments(app,sync):
    seed(app);seed(app,'LEFT');seed(app,'OTHER','AME');app.ensure_department('EMPTY')
    p=preview(sync,[row(shift='N',name='New name'),row('NEW')]);r=commit(sync,p)
    data=current(app);assert data['E001']['shift']=='N' and data['E001']['full_name']=='New name'
    assert data['LEFT']['active']==0 and data['NEW']['active']==1 and data['OTHER']['department']=='AME'
    assert r['active_after']==2 and r['counts']==dict(add=1,update=1,reactivate=0,transfer=0,deactivate=1,unchanged=0,shift_change=1)
    with app.store.tx() as c:assert c.execute("SELECT code FROM departments WHERE code='EMPTY'").fetchone()

def test_resigned_is_not_deleted_and_returner_reactivated(app,sync):
    seed(app,'OLD');att(app,'OLD');commit(sync,preview(sync,[row('NEW')]))
    assert current(app)['OLD']['active']==0
    with app.store.tx() as c:assert c.execute("SELECT * FROM attendance WHERE employee_code='OLD'").fetchone()
    p=preview(sync,[row('OLD'),row('NEW')]);assert p['counts']['reactivate']==1
    commit(sync,p);assert current(app)['OLD']['active']==1

def test_transfer_scoped_preserves_other_people(app,sync):
    seed(app,'MOVE','PE');seed(app,'KEEP','PE');seed(app,'X','PEM');app.ensure_department('TE')
    p=preview(sync,[row('MOVE',department='TE',shift='N')],'TE')
    assert p['counts']['transfer']==1
    with pytest.raises(MasterSyncError):commit(sync,p,ack_transfer=False)
    assert current(app)['MOVE']['department']=='PE'
    commit(sync,p);data=current(app)
    assert data['MOVE']['department']=='TE' and data['KEEP']['department']=='PE' and data['X']['department']=='PEM'

def test_inactive_person_can_transfer(app,sync):
    seed(app,'MOVE','PE',active=0);app.ensure_department('TE')
    commit(sync,preview(sync,[row('MOVE',department='TE')],'TE'))
    assert current(app)['MOVE']['department']=='TE' and current(app)['MOVE']['active']==1

def test_omissions_apply_whole_department_not_filter(app,sync):
    seed(app,'DAY',shift='D');seed(app,'NIGHT',shift='N')
    p=preview(sync,[row('DAY')]);assert p['counts']['deactivate']==1
    commit(sync,p);assert current(app)['NIGHT']['active']==0

def test_remove_ack_required(app,sync):
    seed(app,'OLD');p=preview(sync,[row('NEW')])
    with pytest.raises(MasterSyncError) as e:commit(sync,p,ack_remove=False)
    assert e.value.code=='CONFIRM_REQUIRED' and set(current(app))=={'OLD'}

def test_filename_mismatch_requires_ack(app,sync):
    seed(app);p=preview(sync,[row()],filename='TE STAFF.xlsx',filename_mismatch=True,filename_department='TE')
    with pytest.raises(MasterSyncError):commit(sync,p,ack_filename=False)

def test_target_confirmation_required(app,sync):
    seed(app);p=preview(sync,[row(shift='N')])
    with pytest.raises(MasterSyncError):commit(sync,p,confirm_department='TE')
    assert current(app)['E001']['shift']=='D'

def test_stale_preview_preserves_newer_edit(app,sync):
    seed(app);p=preview(sync,[row(shift='N')])
    with app.store.tx() as c:c.execute("UPDATE employees SET full_name='Newer manual edit' WHERE employee_code='E001'")
    with pytest.raises(MasterSyncError) as e:commit(sync,p)
    assert e.value.code=='STALE_PREVIEW' and current(app)['E001']['full_name']=='Newer manual edit'

def test_preview_expiry(app,sync):
    seed(app);p=preview(sync,[row()])
    with app.store.tx() as c:c.execute("UPDATE master_sync_previews SET expires_at='2000-01-01T00:00:00+00:00'")
    with pytest.raises(MasterSyncError) as e:commit(sync,p)
    assert e.value.code=='PREVIEW_EXPIRED'

def test_duplicate_apply_idempotent_even_after_new_change(app,sync):
    seed(app);p=preview(sync,[row(shift='N')]);first=commit(sync,p)
    with app.store.tx() as c:c.execute("UPDATE employees SET shift='D' WHERE employee_code='E001'")
    second=commit(sync,p);assert second['replayed'] and first['audit_id']==second['audit_id']
    assert current(app)['E001']['shift']=='D'

def test_backup_is_before_image_and_schedule_untouched(app,sync):
    seed(app);att(app,'E001')
    with app.store.tx() as c:before=[dict(x) for x in c.execute('SELECT * FROM auto_schedules')]
    res=commit(sync,preview(sync,[row(shift='N')]));backup=sync.backup(res['audit_id'])
    assert backup['employees'][0]['shift']=='D' and backup['attendance'][0]['status']=='PRESENT'
    with app.store.tx() as c:assert [dict(x) for x in c.execute('SELECT * FROM auto_schedules')]==before
    assert backup['auto_schedules']==before

@pytest.mark.parametrize('kind',['shift','group','transfer','reactivate'])
def test_old_assignment_cache_reset_but_archived(app,sync,kind):
    seed(app,active=0 if kind=='reactivate' else 1);att(app,'E001')
    d='TE' if kind=='transfer' else 'PE';app.ensure_department(d)
    r=row(department=d,shift='N' if kind=='shift' else 'D',group='B' if kind=='group' else 'A')
    result=commit(sync,preview(sync,[r],d));assert result['attendance_cache_reset']==1
    with app.store.tx() as c:assert not c.execute('SELECT * FROM attendance').fetchone()
    assert len(sync.backup(result['audit_id'])['attendance'])==1

def test_name_only_edit_preserves_attendance(app,sync):
    seed(app);att(app,'E001');commit(sync,preview(sync,[row(name='Revised')]))
    with app.store.tx() as c:assert c.execute('SELECT * FROM attendance').fetchone()['status']=='PRESENT'

def test_transaction_rolls_back_everything_on_error(app,sync):
    seed(app,'OLD');p=preview(sync,[row('NEW')]);before=current(app)
    with app.store.tx() as c:
        c.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON master_sync_audits BEGIN SELECT RAISE(ABORT, 'test injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError):commit(sync,p)
    assert current(app)==before
    with app.store.tx() as c:assert c.execute('SELECT status FROM master_sync_previews').fetchone()[0]=='preview'

def test_two_concurrent_applies_only_once(app,sync):
    seed(app);p=preview(sync,[row(shift='N')]);results=[];errors=[]
    def go():
        try:results.append(commit(sync,p))
        except Exception as e:errors.append(e)
    threads=[threading.Thread(target=go) for _ in range(2)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert not errors and len(results)==2 and sum(r['replayed'] for r in results)==1
    with app.store.tx() as c:assert c.execute('SELECT COUNT(*) FROM master_sync_audits').fetchone()[0]==1

def test_backup_retention_20(app,sync):
    seed(app)
    for i in range(22):commit(sync,preview(sync,[row(name='Rev '+str(i))]))
    assert len(sync.history('PE')['imports'])==20

def test_same_file_twice_no_redundant_changes(app,sync):
    seed(app);commit(sync,preview(sync,[row()]))
    second=preview(sync,[row()]);assert second['counts']['unchanged']==1 and not second['changes']

def test_old_upload_route_cannot_bypass_preview(app):
    res,status=app.app.invoke('POST','/api/upload-master');assert status==409 and res['code']=='PREVIEW_REQUIRED'

def test_apply_route_blocks_while_query_busy(app,sync):
    seed(app);p=preview(sync,[row(shift='N')]);app.query_run_lock.acquire()
    try:r,status=app.app.invoke('POST','/api/master-sync/apply',dict(preview_token=p['preview_token'],confirm_department='PE'))
    finally:app.query_run_lock.release()
    assert status==409 and r['code']=='QUERY_BUSY' and current(app)['E001']['shift']=='D'

def test_optional_admin_password_blocks_uncredentialed_route(app,monkeypatch):
    monkeypatch.setenv('MASTER_ADMIN_PASSWORD','TestMasterKeyLong');fake_flask.request.headers={}
    r,status=app.app.invoke('POST','/api/master-sync/apply',{})
    assert status==401 and r['code']=='ADMIN_REQUIRED'

def test_workflow_matches_release_checksum():
    expected=(ROOT/'tests/expected_workflow.sha256').read_text().strip()
    assert hashlib.sha256((ROOT/'.github/workflows/attendance-auto-query.yml').read_bytes()).hexdigest()==expected

# Excel parser tests write minimal XLSX archives with the standard library. No library export required.
def xlsx(rows,headers=None):
    from xml.sax.saxutils import escape
    import zipfile
    headers=headers or ['EMP NO.','NAME','LOCATION','TEAM SUPPORT','GROUP','SHIFT','ACTIVE']
    lines=[]
    for n,vals in enumerate([headers]+rows,1):
        cells=''.join(f'<c r="{chr(65+i)}{n}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>' for i,v in enumerate(vals) if v is not None)
        lines.append(f'<row r="{n}">{cells}</row>')
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(lines)+'</sheetData></worksheet>')
    return b.getvalue()

def test_parser_valid_mixed_shifts_and_active_defaults():
    p=parse_workbook(xlsx([['X1','Name','F10','T','A','D',None],['X2','Name2','F10','T','B','N','NO']]),'PE STAFF.xlsx','PE')
    assert len(p['rows'])==2 and p['rows'][0]['active']==1 and p['rows'][1]['active']==0

@pytest.mark.parametrize('rows',[
    [], [['X1','Name','F10','T','A','D'],['X1','Other','F10','T','A','N']],
    [['','Name','F10','T','A','D']], [['X1','','F10','T','A','D']],
    [['X1','Name','F10','T','A','X']], [['X1','Name','F10','T','A','D','maybe']],
])
def test_parser_rejects_bad_input(rows):
    with pytest.raises(MasterSyncError):parse_workbook(xlsx(rows),'PE STAFF.xlsx','PE')

def test_parser_filename_warning():
    p=parse_workbook(xlsx([['X1','Name','F10','T','A','D']]),'TE STAFF.xlsx','PE')
    assert p['filename_mismatch'] and p['filename_department']=='TE'

def test_parser_department_mismatch_rejected():
    b=xlsx([['X1','Name','F10','T','A','D','TE']],['EMP NO.','NAME','LOCATION','TEAM SUPPORT','GROUP','SHIFT','DEPT'])
    with pytest.raises(MasterSyncError):parse_workbook(b,'PE STAFF.xlsx','PE')

@pytest.mark.parametrize('filename',['bad.csv','bad.xls','bad.zip'])
def test_parser_extension(filename):
    with pytest.raises(MasterSyncError):parse_workbook(b'bad',filename,'PE')

def test_parser_missing_headers():
    with pytest.raises(MasterSyncError):parse_workbook(xlsx([['X1','Name']],['EMP NO.','NAME']),'PE STAFF.xlsx','PE')

def test_parser_corrupt_file():
    with pytest.raises(MasterSyncError):parse_workbook(b'bad','PE.xlsx','PE')

@pytest.mark.skipif(not Path('/mnt/data/TE STAFF.xlsx').exists(),reason='private input files are not included in release')
def test_private_te_pe_recovery_example(app,sync):
    pte=parse_workbook(Path('/mnt/data/TE STAFF.xlsx').read_bytes(),'TE STAFF.xlsx','TE')
    ppe=parse_workbook(Path('/mnt/data/PE STAFF.xlsx').read_bytes(),'PE STAFF.xlsx','PE')
    assert len(pte['rows'])==54 and len(ppe['rows'])==3
    for r in pte['rows']+ppe['rows']:
        seed(app,r['employee_code'],'PE',r['shift'],full_name=r['full_name'],location_support=r['location_support'],team_support=r['team_support'],group_code=r['group_code'])
    seed(app,'UNTOUCHED','AME');app.ensure_department('TE')
    p=sync.preview(Path('/mnt/data/TE STAFF.xlsx').read_bytes(),'TE STAFF.xlsx','TE')
    assert p['counts']['transfer']==54;commit(sync,p)
    p=sync.preview(Path('/mnt/data/PE STAFF.xlsx').read_bytes(),'PE STAFF.xlsx','PE');commit(sync,p)
    data=current(app)
    assert sum(x['department']=='TE' and x['active'] for x in data.values())==54
    assert sum(x['department']=='PE' and x['active'] for x in data.values())==3
    assert data['UNTOUCHED']['department']=='AME'
