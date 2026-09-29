"""Offline regression tests with SQLite + existing route test double, not live MIS."""
import sys,json,threading,hashlib
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch,Mock
from concurrent.futures import ThreadPoolExecutor
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shift_history import BKK,resolve_view,normalize_mode,fingerprint,ShiftHistory
from thai_schedule import hhmm,ThaiSchedules
from test_persistence import app,fake_flask,emp,add
from test_master_sync import seed,row,preview,commit

def clock(app,value):app.bkk_now=lambda:datetime.fromisoformat(value).astimezone(BKK)
def at(app,wd='2026-09-28',sh='D',code='E001',department='PE'):
    e=next(e for e in app.history.roster(department,wd,sh) if e['employee_code']==code)
    result=dict(status='PRESENT',name_from_web='Test',latest_datetime='28/09/2026 08:00:00',scan_in='28/09/2026 08:00:00',scan_out='',raw_count=1,ot_minutes=0,work_date='28/09/2026')
    with app.store.tx() as c:app.history.save_result(c,e,wd,sh,result)
    return e

def rules(app,dep='PE',slots=None,days=None):
    p=app.schedules.get(dep)
    if slots is not None:p['slots']=slots
    if days is not None:p['weekdays']=days
    return app.schedules.save(dep,p)

def single(mode='DAY',t='08:15',id='one'):return [dict(id=id,mode=mode,time=t,enabled=True)]

@pytest.mark.parametrize('mode,shift,wd',[('LAST_DAY','D','2026-09-28'),('DAY','D','2026-09-29'),('LAST_NIGHT','N','2026-09-28'),('TONIGHT','N','2026-09-29')])
def test_four_modes_are_bangkok_based(mode,shift,wd):
    # Machine's UTC date is still 28th, Thai date is 29th.
    v=resolve_view(mode,datetime(2026,9,28,18,0,tzinfo=timezone.utc));assert v['work_date']==wd and v['shift']==shift

@pytest.mark.parametrize('now,wd',[('2027-01-01T01:00:00+07:00','2026-12-31'),('2028-03-01T01:00:00+07:00','2028-02-29')])
def test_calendar_rollovers(now,wd):assert resolve_view('LAST_DAY',datetime.fromisoformat(now))['work_date']==wd

def test_naive_clock_rejected():
    with pytest.raises(ValueError):resolve_view('DAY',datetime(2026,1,1))

@pytest.mark.parametrize('t',['04:40','16:40','23:59','00:00'])
def test_24hour_valid(t):assert hhmm(t)==t
@pytest.mark.parametrize('t',['4:40','24:00','16:60','4:40 PM','08:15:00',None])
def test_24hour_invalid(t):
    with pytest.raises(ValueError):hhmm(t)

def test_unknown_history_not_a_known_empty_shift(app):
    clock(app,'2026-09-29T08:00:00+07:00');seed(app)
    assert app.history.roster('PE','2026-09-28','D') is None
    assert app.history.roster('PE','2026-09-29','N')==[]
    d,status=app.app.invoke('GET','/api/dashboard',args={'view':'LAST_DAY','department':'PE'})
    assert status==200 and not d['roster_known'] and d['counts']['NO SCAN TODAY']==0 and d['employees']==[]

def test_previous_day_shift_survives_latest_excel_change(app):
    clock(app,'2026-09-28T08:00:00+07:00');seed(app);at(app)
    clock(app,'2026-09-29T08:00:00+07:00')
    p=preview(app.master_sync,[row(shift='N')]);commit(app.master_sync,p)
    yesterday=app.history.records('PE','2026-09-28','D')
    assert yesterday[0]['shift']=='D' and yesterday[0]['status']=='PRESENT'
    today=app.history.records('PE','2026-09-29','N')
    assert today[0]['status']=='NOT CHECKED'

def test_previous_department_is_preserved_after_transfer(app):
    clock(app,'2026-09-28T08:00:00+07:00');seed(app);at(app);app.ensure_department('TE')
    clock(app,'2026-09-29T08:00:00+07:00')
    commit(app.master_sync,preview(app.master_sync,[row(department='TE')],'TE'))
    assert app.history.records('PE','2026-09-28','D')[0]['department']=='PE'
    assert app.history.records('TE','2026-09-29','D')[0]['status']=='NOT CHECKED'
    assert app.history.roster('PE','2026-09-29','D')==[]

def test_old_roster_for_resigned_person_preserved(app):
    clock(app,'2026-09-28T08:00:00+07:00');seed(app);at(app)
    clock(app,'2026-09-29T08:00:00+07:00');commit(app.master_sync,preview(app.master_sync,[row('NEW')]))
    assert app.history.records('PE','2026-09-28','D')[0]['employee_code']=='E001'
    assert [r['employee_code'] for r in app.history.roster('PE','2026-09-29','D')]==['NEW']

def test_assignment_flip_back_does_not_resurrect_scan(app):
    clock(app,'2026-09-28T08:00:00+07:00');seed(app);at(app)
    clock(app,'2026-09-28T09:00:00+07:00');commit(app.master_sync,preview(app.master_sync,[row(shift='N')]))
    clock(app,'2026-09-28T10:00:00+07:00');commit(app.master_sync,preview(app.master_sync,[row(shift='D')]))
    assert app.history.records('PE','2026-09-28','D')[0]['status']=='NOT CHECKED'

def test_employee_mutation_and_snapshot_rollback_together(app):
    clock(app,'2026-09-28T08:00:00+07:00');seed(app)
    with pytest.raises(RuntimeError):
        with app.store.tx() as c:
            c.execute("UPDATE employees SET shift='N' WHERE employee_code='E001'")
            raise RuntimeError('cancel')
    assert app.history.roster('PE','2026-09-28','D')[0]['shift']=='D'
    assert app.history.roster('PE','2026-09-28','N')==[]

def test_historical_mis_rows_missing_is_not_no_scan(app):
    clock(app,'2026-09-29T08:30:00+07:00')
    result=app.choose([['1','E001','Test','29/09/2026 07:50:00']],'E001',shift='D',requested_work_date='2026-09-28')
    assert result[1]=='NO DATA FOR SHIFT'

def test_today_before_start_reports_not_started(app):
    clock(app,'2026-09-29T05:00:00+07:00')
    r=app.choose([['1','E001','Test','28/09/2026 08:00:00']],'E001',shift='D',requested_work_date='2026-09-29')
    assert r[1]=='NOT STARTED'

def test_manual_query_rejects_stale_date(app):
    clock(app,'2026-09-29T00:00:30+07:00');seed(app)
    d,status=app.app.invoke('POST','/api/query',{'department':'PE','mode':'DAY','work_date':'2026-09-28'})
    assert status==409 and not d['ok']

def test_schedule_imports_old_times_without_reset(app):
    app.ensure_department('PEM')
    app.save_auto_schedule('PEM',dict(enabled=False,weekdays=[0,1],day1_time='08:32',day2_time='17:55',night1_time='20:31',night_final_time='06:11'))
    p=app.schedules.get('PEM');s={x['id']:x for x in p['slots']}
    assert not p['enabled'] and p['weekdays']==[0,1] and s['day1']['time']=='08:32' and not s['last_day']['enabled']

def test_schedule_does_not_change_without_save(app):
    p=app.schedules.get('PE');p['slots'][0]['time']='16:40'
    assert app.schedules.get('PE')['slots'][0]['time']!='16:40'

def test_schedule_stale_etag_rejected(app):
    p=app.schedules.get('PE');q=rules(app,slots=single(t='16:40'))
    with pytest.raises(ValueError):app.schedules.save('PE',p)
    assert any(r['time']=='16:40' for r in app.schedules.get('PE')['slots'])

def test_duplicate_enabled_slots_rejected(app):
    p=app.schedules.get('PE');p['slots']=single()+single(id='other')
    with pytest.raises(ValueError):app.schedules.save('PE',p)

def test_invalid_slot_rejected_without_partial_save(app):
    p=app.schedules.get('PE');old=json.dumps(p);p['slots'][0]['time']='25:00'
    with pytest.raises(ValueError):app.schedules.save('PE',p)
    assert json.dumps(app.schedules.get('PE'))==old

def test_claimed_slot_is_not_duplicated(app):
    clock(app,'2026-09-29T08:16:00+07:00');seed(app);rules(app,slots=single())
    assert len(app.schedules.due())==1
    assert app.schedules.due()==[]

def test_atomic_claim_two_callers(app):
    clock(app,'2026-09-29T08:16:00+07:00');seed(app);rules(app,slots=single())
    with ThreadPoolExecutor(max_workers=4) as ex:r=list(ex.map(lambda _:app.schedules.due(),range(4)))
    assert sum(len(x) for x in r)==1

def test_done_slot_save_same_time_does_not_rerun(app):
    clock(app,'2026-09-29T08:16:00+07:00');seed(app);rules(app,slots=single())
    t=app.schedules.due()[0];app.schedules.complete('PE',t['slot_key'],t['slot_date'],'done')
    app.schedules.save('PE',app.schedules.get('PE'))
    assert app.schedules.due()==[]

def test_changed_time_can_run_again_same_day(app):
    clock(app,'2026-09-29T08:16:00+07:00');seed(app);rules(app,slots=single())
    t=app.schedules.due()[0];app.schedules.complete('PE',t['slot_key'],t['slot_date'],'done')
    p=app.schedules.get('PE');next(r for r in p['slots'] if r['id']=='one')['time']='08:17';app.schedules.save('PE',p)
    clock(app,'2026-09-29T08:18:00+07:00');t2=app.schedules.due()[0]
    assert t2['slot_key']!=t['slot_key'] and t2['late_minutes']==1

def test_done_not_reported_as_next_run_today(app):
    clock(app,'2026-09-29T08:16:00+07:00');seed(app);rules(app,slots=single())
    t=app.schedules.due()[0];app.schedules.complete('PE',t['slot_key'],t['slot_date'],'done')
    d=app.schedules.diagnostics('PE');assert not d['pending'] and d['next_run']['slot_date']=='2026-09-30'

def test_night_final_execution_weekday_is_sunday(app):
    clock(app,'2026-09-26T20:00:00+07:00');seed(app,shift='N');rules(app,slots=single('LAST_NIGHT','06:00'),days=[6])
    clock(app,'2026-09-27T06:02:00+07:00');t=app.schedules.due()[0]
    assert t['work_date']=='2026-09-26' and t['slot_date']=='2026-09-27'

def test_delayed_tick_crosses_midnight_keeps_original_workdate(app):
    clock(app,'2026-09-28T23:00:00+07:00');seed(app);rules(app,slots=single('DAY','23:55'))
    clock(app,'2026-09-29T00:05:00+07:00');t=app.schedules.due()[0]
    assert t['slot_date']=='2026-09-28' and t['work_date']=='2026-09-28' and t['late_minutes']==10
    app.AUTO_QUERY_TOKEN='x';fake_flask.request.headers={'X-Auto-Query-Token':'x'}
    with patch.object(app.threading,'Thread'):
        d,status=app.app.invoke('POST','/api/query',dict(department='PE',source='AUTO',slot_key=t['slot_key'],slot_date=t['slot_date']))
    assert status==200 and d['work_date']=='2026-09-28'

def test_auto_start_requires_authentication(app):
    fake_flask.request.headers={};d,status=app.app.invoke('POST','/api/query',dict(department='PE',source='AUTO'))
    assert status==401

def test_query_duplicates_share_job_atomically(app):
    clock(app,'2026-09-29T08:00:00+07:00');seed(app)
    with patch.object(app.threading,'Thread'):
        a,_=app.app.invoke('POST','/api/query',dict(department='PE',mode='DAY'))
        b,_=app.app.invoke('POST','/api/query',dict(department='PE',mode='DAY',missing_only=True))
    assert b['duplicate'] and a['job_id']==b['job_id']

def test_progress_timestamps_persist_and_delay_visible(app):
    clock(app,'2026-09-29T08:30:00+07:00');seed(app);rules(app,slots=single())
    t=app.schedules.due()[0];app.AUTO_QUERY_TOKEN='x';fake_flask.request.headers={'X-Auto-Query-Token':'x'}
    with patch.object(app.threading,'Thread'):
        d,_=app.app.invoke('POST','/api/query',dict(department='PE',source='AUTO',slot_key=t['slot_key'],slot_date=t['slot_date'],trigger='schedule'))
    jid=d['job_id'];app.setjob(jid,status='running',started_at=app.bkk_now().isoformat());app.setjob(jid,status='done',finished_at=app.bkk_now().isoformat())
    s,_=app.app.invoke('GET','/api/query-status');j=s['recent'][0]
    assert j['start_delay_minutes']==15 and j['trigger']=='schedule'
    assert app.history.previous_jobs()[jid]['status']=='done'

def test_new_archive_is_exported_with_backup(app):
    clock(app,'2026-09-28T08:00:00+07:00');seed(app);at(app)
    b=app.recovery.export_all();assert b['shift_rosters'] and b['shift_results'] and b['schedule_rules']

def test_invalid_archive_rejected_before_employee_writes(app):
    with pytest.raises(ValueError):app.recovery.import_pack(dict(department='PE',employees=[emp(dept='PE')],shift_rosters=[{}]))
    with app.db() as c:assert c.execute('SELECT COUNT(*) FROM employees').fetchone()[0]==0

def test_new_backup_does_not_overwrite_newer_roster(app):
    clock(app,'2026-09-28T08:00:00+07:00');seed(app);b=app.recovery.export_all()
    clock(app,'2026-09-28T09:00:00+07:00');commit(app.master_sync,preview(app.master_sync,[row(shift='N')]))
    app.recovery.import_pack(b)
    assert app.history.roster('PE','2026-09-28','D')==[] and len(app.history.roster('PE','2026-09-28','N'))==1

class BrowserStub:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    @property
    def chromium(self):return self
    def launch(self,**kwargs):return self
    def new_context(self,**kwargs):return self
    def add_init_script(self,*args):pass
    def new_page(self):return self
    def close(self):pass

def test_last_day_actual_worker_does_not_overwrite_today(app):
    clock(app,'2026-09-28T08:00:00+07:00');seed(app);at(app)
    clock(app,'2026-09-29T08:00:00+07:00');app.history.capture_today();today=at(app,'2026-09-29')
    with app.store.tx() as c:
        c.execute("INSERT INTO attendance(employee_code,status,work_date) VALUES('E001','PRESENT','29/09/2026')")
    with patch.object(app.threading,'Thread'):
        d,_=app.app.invoke('POST','/api/query',dict(department='PE',mode='LAST_DAY'))
    rr=dict(status='NO DATA FOR SHIFT',name_from_web='Test',latest_datetime='',scan_in='',scan_out='',raw_count=0,ot_minutes=0,work_date='28/09/2026')
    with patch.object(app,'sync_playwright',return_value=BrowserStub()),patch.object(app,'query_once',return_value=rr),patch.object(app.time,'sleep'):
        app.runquery(d['job_id'],'D','2026-09-28',False,'PE')
    assert app.history.records('PE','2026-09-28','D')[0]['status']=='NO DATA FOR SHIFT'
    assert app.history.records('PE','2026-09-29','D')[0]['status']=='PRESENT'
    with app.db() as c:assert c.execute("SELECT work_date FROM attendance WHERE employee_code='E001'").fetchone()[0]=='29/09/2026'


def test_workflow_pins_schedule_and_keeps_github_cadence():
    s=(Path(__file__).resolve().parents[1]/'.github/workflows/attendance-auto-query.yml').read_text()
    assert "cron: '*/5 * * * *'" in s and 'attendance-auto-query-v12-1' in s
    assert "'slot_key': slot" in s and "'trigger': trigger" in s and "timeout=60, auth=True)" in s
    assert 'cancel-in-progress: false' in s

def test_current_day_legacy_cache_migrates_with_original_timestamp(app):
    clock(app,'2026-09-29T08:30:00+07:00');seed(app,updated_at='2026-09-29T07:00:00+07:00')
    with app.db() as c:c.execute("INSERT INTO attendance(employee_code,status,query_at,work_date) VALUES('E001','PRESENT','29/09/2026 08:20:00','29/09/2026')")
    app.history.init();rr=app.history.records('PE','2026-09-29','D')[0]
    assert rr['status']=='PRESENT' and rr['query_at']=='2026-09-29T08:20:00+07:00'

def test_legacy_cache_before_master_change_is_not_migrated(app):
    clock(app,'2026-09-29T08:30:00+07:00');seed(app,updated_at='2026-09-29T08:25:00+07:00')
    with app.db() as c:c.execute("INSERT INTO attendance(employee_code,status,query_at,work_date) VALUES('E001','PRESENT','29/09/2026 08:20:00','29/09/2026')")
    app.history.init();assert app.history.records('PE','2026-09-29','D')[0]['status']=='NOT CHECKED'

def test_old_day_legacy_cache_does_not_invent_roster(app):
    clock(app,'2026-09-29T08:30:00+07:00');seed(app,updated_at='2026-09-01T08:00:00+07:00')
    with app.db() as c:c.execute("INSERT INTO attendance(employee_code,status,query_at,work_date) VALUES('E001','PRESENT','28/09/2026 08:20:00','28/09/2026')")
    app.history.init();assert app.history.roster('PE','2026-09-28','D') is None

def test_restart_restores_rosters_and_query_journal(app):
    clock(app,'2026-09-28T08:30:00+07:00');seed(app);at(app)
    app.history.save_job('previous',{'status':'done','department':'PE'})
    again=ShiftHistory(app.store,clock=lambda:app.bkk_now());again.init()
    assert again.records('PE','2026-09-28','D')[0]['status']=='PRESENT'
    assert again.previous_jobs()['previous']['status']=='done'

def test_scheduler_heartbeat_differentiates_manual_trigger(app):
    clock(app,'2026-09-29T08:30:00+07:00');app.AUTO_QUERY_TOKEN='x';fake_flask.request.headers={'X-Auto-Query-Token':'x'}
    app.app.invoke('POST','/api/auto-query/tick',{'trigger':'workflow_dispatch'})
    r,_=app.app.invoke('GET','/api/query-status')
    assert r['scheduler_contact']['source']=='GITHUB_MANUAL'
    app.app.invoke('POST','/api/auto-query/tick',{'trigger':'schedule'})
    r,_=app.app.invoke('GET','/api/query-status');assert r['scheduler_contact']['source']=='GITHUB_SCHEDULE'

def test_timestamps_explicit_thai_even_if_host_env_utc(app,monkeypatch):
    monkeypatch.setenv('TZ','UTC');clock(app,'2026-09-29T01:30:00+07:00')
    r,_=app.app.invoke('GET','/api/health');assert r['tz']=='Asia/Bangkok' and r['system_tz']=='UTC' and r['server_time'].endswith('+07:00')
