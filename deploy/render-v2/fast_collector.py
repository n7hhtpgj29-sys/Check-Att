from datetime import datetime,timedelta,time as dtime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright
from collector_v2 import SOURCE
import re,time

def scan_group(ids,shift,work_date):
    day=datetime.strptime(work_date,"%Y-%m-%d").date()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False,args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"])
        try:
            context=browser.new_context(ignore_https_errors=True,locale="en-US",timezone_id="Asia/Bangkok",viewport={"width":1280,"height":900},user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
            context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            context.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image","font","media") else route.continue_())
            page=context.new_page()
            page_ready=False
            for emp in ids:
                try:
                    if not page_ready or page.locator("input").count()==0:
                        response=page.goto(SOURCE,wait_until="domcontentloaded",timeout=20000)
                        if not response or response.status!=200:
                            page_ready=False
                            yield "QUERY_ERROR"
                            continue
                        page_ready=True
                    page.locator("input").first.fill(emp,timeout=8000)
                    button=page.get_by_role("button",name="GO")
                    button.click(timeout=8000,no_wait_after=True)
                    deadline=time.monotonic()+7
                    found=[]
                    while time.monotonic()<deadline:
                        rows_data=page.locator("table tr").evaluate_all(
                            """rows => rows.slice(0,150).map(row =>
                                Array.from(row.querySelectorAll('td'), cell =>
                                    (cell.textContent || '').trim()))""")
                        for values in rows_data:
                            if len(values)<4 or values[1].upper()!=emp.upper():
                                continue
                            try:
                                found.append(datetime.strptime(values[3],"%d/%m/%Y %H:%M:%S"))
                            except ValueError:
                                pass
                        if found:break
                        page.wait_for_timeout(200)
                    if shift=="D":
                        matched=[x for x in found if x.date()==day and x.time()<dtime(12)]
                    else:
                        matched=[x for x in found if datetime.combine(day,dtime(16))<=x<datetime.combine(day+timedelta(days=1),dtime(12))]
                    now=datetime.now(ZoneInfo('Asia/Bangkok'))
                    start=datetime.combine(day,dtime(8,0) if shift=='D' else dtime(20,0),ZoneInfo('Asia/Bangkok'))
                    if matched:
                        yield 'SCAN_FOUND'
                    elif found and now>=start:
                        yield 'NO_SCAN_IN_WINDOW'
                    else:
                        yield 'INCOMPLETE'
                except Exception:
                    page_ready=False
                    yield "QUERY_ERROR"
        finally:
            browser.close()
