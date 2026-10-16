"""Read-only diagnostic using the same browser setup and landing URL as Production."""
SOURCE = "https://webapp.calcomp.co.th/att/"

def probe_source():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False,args=[
            "--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"
        ])
        try:
            ctx = browser.new_context(
                ignore_https_errors=True,viewport={"width":1280,"height":900},
                locale="en-US",timezone_id="Asia/Bangkok",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            )
            ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page=ctx.new_page()
            response=page.goto(SOURCE,wait_until="domcontentloaded",timeout=30000)
            status=response.status if response else None
            title=page.title()[:120]
            has_input=page.locator("input").count()>0
            has_go=page.get_by_role("button",name="GO").count()>0
            ready=status==200 and has_input and has_go
            return {"source":"form_ready" if ready else "unavailable",
                    "http_status":status,"page_title":title,
                    "has_input":has_input,"has_go_button":has_go,
                    "safe_to_mark_missing":False,
                    "note":"Read-only form test. No employee queried and no attendance records written."}
        finally:
            browser.close()

def query_employee(employee_no, shift="D", work_date=None):
    """Diagnostic one-person query; absence is INCOMPLETE, never missing."""
    import re, time
    from datetime import datetime, timedelta, time as clock
    from zoneinfo import ZoneInfo
    from playwright.sync_api import sync_playwright
    now=datetime.now(ZoneInfo("Asia/Bangkok"))
    wd=datetime.strptime(work_date,"%Y-%m-%d").date() if work_date else now.date()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False,args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"])
        try:
            ctx=browser.new_context(ignore_https_errors=True,viewport={"width":1280,"height":900},locale="en-US",timezone_id="Asia/Bangkok",user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
            ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page=ctx.new_page()
            response=page.goto(SOURCE,wait_until="domcontentloaded",timeout=30000)
            if not response or response.status!=200: return {"status":"QUERY_ERROR","reason":"source_unavailable","safe_to_mark_missing":False}
            field=page.locator("input").first
            field.wait_for(state="visible",timeout=10000)
            field.fill(employee_no)
            btn=page.get_by_role("button",name=re.compile(r"^\\s*GO\\s*$",re.I))
            btn=btn if btn.count() else page.locator("button,input[type=submit]").first
            btn.click(timeout=5000,no_wait_after=True)
            deadline=time.monotonic()+12
            records=[]
            while time.monotonic()<deadline:
                rows=page.locator("table tbody tr")
                if not rows.count(): rows=page.locator("table tr")
                for i in range(min(rows.count(),250)):
                    cells=rows.nth(i).locator("td")
                    if cells.count()<4: continue
                    values=[v.strip() for v in cells.all_inner_texts()]
                    if values[1].upper()!=employee_no.upper(): continue
                    try: ts=datetime.strptime(values[3],"%d/%m/%Y %H:%M:%S")
                    except ValueError: continue
                    records.append(ts)
                if records: break
                page.wait_for_timeout(350)
            if not records: return {"status":"INCOMPLETE","reason":"no_verifiable_rows","safe_to_mark_missing":False}
            if shift=="N":
                start=datetime.combine(wd,clock(16,0)); end=datetime.combine(wd+timedelta(days=1),clock(12,0))
                scans=[x for x in records if start<=x<=end]
            else:
                scans=[x for x in records if x.date()==wd and x.time()<clock(12,0)]
            return {"status":"SCAN_FOUND" if scans else "INCOMPLETE",
                    "scan_in":min(scans).isoformat() if scans else None,
                    "matching_records":len(records),"safe_to_mark_missing":False,
                    "reason":None if scans else "no_scan_in_window_not_yet_verified"}
        finally:
            browser.close()
