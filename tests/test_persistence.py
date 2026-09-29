"""Offline tests: real SQLite + real application route bodies.
Flask itself is a small test double because Flask/psycopg/PostgreSQL are absent
in this test container. This does NOT certify live PostgreSQL/Render integration.
"""
import sys, os, json, importlib, types, sqlite3, re, hashlib
from pathlib import Path
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from persistent_store import Store, DatabaseUnavailable, pg_sql, CompatRow
from data_recovery import Recovery, normalize

class Request:
    def __init__(self):self.body={};self.args={};self.headers={};self.path='/';self.form={};self.files={}
    def get_json(self,**kw):return self.body

class FlaskDouble:
    def __init__(self,*a,**k):self.config={};self.routes={};self.errors={};self.after=[]
    def route(self,path,method):
        def deco(fn):self.routes[(method,path)]=fn;return fn
        return deco
    def get(self,path):return self.route(path,'GET')
    def post(self,path):return self.route(path,'POST')
    def errorhandler(self,exc):
        def deco(fn):self.errors[exc]=fn;return fn
        return deco
    def after_request(self,fn):self.after.append(fn);return fn
    def invoke(self,method,path,body=None,args=None):
        fake_flask.request.body=body or {};fake_flask.request.args=args or {};fake_flask.request.path=path
        try:
            r=self.routes[(method,path)]()
        except Exception as exc:
            for cls,fn in self.errors.items():
                if isinstance(exc,cls):return fn(exc)
            raise
        return (r,200) if not isinstance(r,tuple) else r
fake_flask=types.ModuleType('flask')
fake_flask.Flask=FlaskDouble
fake_flask.request=Request()
fake_flask.jsonify=lambda *a,**kw: a[0] if a else kw
fake_flask.render_template=lambda f:f
fake_flask.send_from_directory=lambda *a,**k:None

@pytest.fixture
def app(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('DATABASE_URL','')
    monkeypatch.setenv('REQUIRE_POSTGRES','false')
    monkeypatch.setitem(sys.modules,'flask',fake_flask)
    # No call to Playwright/browser in persistence tests.
    sys.modules.pop('app',None)
    return importlib.import_module('app')

def emp(code='TEST001',dept='PEM',name='Maintained name',shift='D'):
    return dict(employee_code=code,department=dept,full_name=name,shift=shift,group_code='A',
                location_support='Factory 10',team_support='Test team',active=1)

def add(a,code='TEST001',dept='PEM',name='Maintained name'):
    return a.app.invoke('POST','/api/employees',emp(code,dept,name))

def test_required_missing_fails_without_local_db(tmp_path,monkeypatch):
    monkeypatch.setenv('REQUIRE_POSTGRES','true');p=tmp_path/'absent.db'
    with pytest.raises(DatabaseUnavailable):Store('',p)
    assert not p.exists()

def test_render_default_requires_postgres(tmp_path,monkeypatch):
    monkeypatch.delenv('REQUIRE_POSTGRES',raising=False);monkeypatch.setenv('RENDER','true')
    with pytest.raises(DatabaseUnavailable):Store('',tmp_path/'absent.db')

@pytest.mark.parametrize('url',['https://foo.supabase.co','sqlite:///data.db','not a url'])
def test_bad_url_rejected(url,tmp_path,monkeypatch):
    monkeypatch.setenv('REQUIRE_POSTGRES','false')
    with pytest.raises(DatabaseUnavailable):Store(url,tmp_path/'none.db')

def test_broken_pg_has_no_fallback_or_secret_leak(tmp_path,monkeypatch):
    monkeypatch.setenv('REQUIRE_POSTGRES','false')
    driver=types.ModuleType('psycopg');driver.connect=Mock(side_effect=RuntimeError('password=SECRET_TEST_123'))
    monkeypatch.setitem(sys.modules,'psycopg',driver)
    s=Store('postgresql://u:SECRET_TEST_123@invalid/db',tmp_path/'none.db')
    with pytest.raises(DatabaseUnavailable) as e:s.ping()
    assert 'SECRET_TEST_123' not in str(e.value)
    assert not s.path.exists()

@pytest.mark.parametrize('sql,expected',[
    ("SELECT * FROM x WHERE a=?", "SELECT * FROM x WHERE a=%s"),
    ("SELECT '?' AS a, x FROM t WHERE x=?", "SELECT '?' AS a, x FROM t WHERE x=%s"),
    ("SELECT 'it''s ?' FROM t WHERE x=?", "SELECT 'it''s ?' FROM t WHERE x=%s"),
    ("SELECT * FROM t WHERE name LIKE 'A%' AND x=?", "SELECT * FROM t WHERE name LIKE 'A%%' AND x=%s"),
    ('INSERT OR IGNORE INTO t(k) VALUES(?)','INSERT INTO t(k) VALUES(%s) ON CONFLICT DO NOTHING'),
])
def test_sql_translation(sql,expected):assert pg_sql(sql)==expected

def test_row_mapping_and_index():
    r=CompatRow(a=1,b='test');assert r[0]==r['a']==1 and dict(r)=={'a':1,'b':'test'}

def test_department_and_employee_survive_app_restart(app):
    add(app);add(app,'TEST002','AME','AME maintained')
    app.ensure_department('QA-EMPTY')
    app.save_auto_schedule('PEM',dict(enabled=True,weekdays=[0,1,2,3,4,5],day1_time='08:30',day2_time='18:00',night1_time='20:15',night_final_time='06:00'))
    with app.db() as c:
        c.execute("INSERT INTO attendance(employee_code,status,query_at,work_date) VALUES(?,?,?,?)",('TEST001','PRESENT','26/09/2026 08:30:00','26/09/2026'))
    app=importlib.reload(app)
    d,status=app.app.invoke('GET','/api/departments')
    assert status==200 and {r['code'] for r in d['departments']}=={'PE','PEM','AME','QA-EMPTY'}
    d,status=app.app.invoke('GET','/api/employees',args={'department':'PEM'})
    assert d['employees'][0]['full_name']=='Maintained name'
    assert app.get_auto_schedule('PEM')['day1_time']=='08:30'
    with app.db() as c:assert c.execute('SELECT status FROM attendance WHERE employee_code=?',('TEST001',)).fetchone()[0]=='PRESENT'

def test_preview_readonly(app):
    d=app.recovery.preview(dict(department='AME',employees=[emp(dept='AME')]))
    assert d['departments_to_add']==1 and d['employees_to_add']==1
    with app.db() as c:assert c.execute('SELECT COUNT(*) FROM employees').fetchone()[0]==0

def test_merge_old_backup_preserves_maintained_names(app):
    add(app);add(app,'TEST002','AME','AME maintained')
    d=app.recovery.import_pack(dict(department='PEM',employees=[emp(name='OLD wrong name'),emp('TEST003')]))
    assert d['employees_added']==1
    with app.db() as c:
        assert c.execute('SELECT full_name FROM employees WHERE employee_code=?',('TEST001',)).fetchone()[0]=='Maintained name'
        assert c.execute('SELECT full_name FROM employees WHERE employee_code=?',('TEST002',)).fetchone()[0]=='AME maintained'

def test_old_client_restore_cannot_delete_other_people(app):
    add(app);add(app,'TEST002','PEM','Second')
    d,status=app.app.invoke('POST','/api/state/restore',dict(department='PEM',employees=[emp(name='OLD')]))
    assert status==200 and d['merge_only']
    with app.db() as c:assert c.execute('SELECT COUNT(*) FROM employees').fetchone()[0]==2

def test_legacy_master_replace_is_add_only(app):
    add(app);add(app,'TEST002','PEM','Second')
    d,status=app.app.invoke('POST','/api/master/replace',dict(department='PEM',employees=[emp(name='OLD')]))
    assert status==200
    with app.db() as c:assert c.execute('SELECT COUNT(*) FROM employees WHERE active=1').fetchone()[0]==2

def test_no_silent_cross_department_move(app):
    add(app)
    d,status=add(app,dept='AME',name='OTHER')
    assert status==409 and 'No data was moved' in d['error']
    with app.db() as c:assert c.execute('SELECT department,full_name FROM employees WHERE employee_code=?',('TEST001',)).fetchone()[0]=='PEM'

def test_import_conflict_keeps_server_and_does_not_attach_wrong_attendance(app):
    add(app)
    d=app.recovery.import_pack(dict(department='AME',employees=[emp(dept='AME')],attendance=[dict(employee_code='TEST001',status='PRESENT')]))
    assert len(d['conflicts'])==1 and d['attendance_added']==0 and d['employees_added']==0

def test_import_repeated_is_idempotent(app):
    p=dict(department='PEM',employees=[emp()])
    assert app.recovery.import_pack(p)['employees_added']==1
    assert app.recovery.import_pack(p)['employees_added']==0

@pytest.mark.parametrize('invalid',[{'shift':'X'},{'employee_code':''},{'department':'ALL'}])
def test_invalid_import_does_not_partially_write(app,invalid):
    p=dict(department='PEM',employees=[emp(),{**emp('BAD'),**invalid}])
    with pytest.raises(ValueError):app.recovery.import_pack(p)
    with app.db() as c:assert c.execute('SELECT COUNT(*) FROM employees').fetchone()[0]==0

def test_export_empty_department_and_schedules(app):
    add(app);app.ensure_department('QA-EMPTY')
    p=app.recovery.export_all()
    assert 'QA-EMPTY' in {x['code'] for x in p['departments']}
    assert 'auto_schedules' in p and len(p['employees'])==1
    assert 'DATABASE_URL' not in json.dumps(p)

def test_export_import_roundtrip_to_new_database(app,tmp_path):
    add(app);add(app,'TEST002','AME')
    p=app.recovery.export_all()
    old=app.store
    app.store=Store('',tmp_path/'other.db');app.init();app.init_auto_store()
    app.recovery=Recovery(app.store,app.ensure_auto_schedule)
    result=app.recovery.import_pack(p)
    assert result['employees_added']==2
    assert {r['department'] for r in app.recovery.export_all()['employees']}=={'PEM','AME'}
    app.store=old

def test_database_health_reports_local_honestly(app):
    d,status=app.app.invoke('GET','/api/health')
    assert d['version']=='12.1.3-thai-time-four-views' and not d['persistent_data'] and d['data_store']=='sqlite-local'

def test_backup_invalid_duplicate_codes_rejected(app):
    with pytest.raises(ValueError):app.recovery.import_pack(dict(department='PEM',employees=[emp(),emp()]))

def test_transaction_rollback_preserves_existing(app):
    add(app)
    with pytest.raises(RuntimeError):
        with app.db() as c:
            c.execute('UPDATE employees SET full_name=? WHERE employee_code=?',('TEMP','TEST001'))
            raise RuntimeError('test failure')
    with app.db() as c:assert c.execute('SELECT full_name FROM employees').fetchone()[0]=='Maintained name'

def test_github_workflow_matches_release_checksum():
    p='.github/workflows/attendance-auto-query.yml'
    assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==(ROOT/'tests/expected_workflow.sha256').read_text().strip()

def test_old_browser_automatic_restore_removed():
    s=(ROOT/'templates/index.html').read_text()
    body=s[s.index('async function ensureMasterPersistence()'):s.index('function exportMasterFile()')]
    assert 'restoreState(true)' not in body and 'restoreMaster(true)' not in body
    assert 'ccAttendanceStateV1211' in s

def test_legacy_upload_requires_preview_in_v1212():
    s=(ROOT/'app.py').read_text();s=s[s.index('def upload():'):s.index('# Department-scoped')]
    assert "UPDATE employees SET active=0" not in s
    assert "PREVIEW_REQUIRED" in s and ",409" in s

def test_empty_department_does_not_consume_auto_slot_during_migration(app):
    # Force a due clock matching DAY #1 but there are no employees yet.
    from datetime import datetime
    app.AUTO_QUERY_TOKEN='test-only-token'
    fake_flask.request.headers={'X-Auto-Query-Token':'test-only-token'}
    original=app.bkk_now
    app.bkk_now=lambda:datetime(2026,9,26,8,16,tzinfo=app.BKK)
    r,status=app.app.invoke('POST','/api/auto-query/tick',{})
    assert status==200 and r['tasks']==[]
    with app.db() as c:assert c.execute('SELECT COUNT(*) FROM auto_query_runs').fetchone()[0]==0
    app.bkk_now=original
