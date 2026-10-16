"""Read-only diagnostic using the same browser setup and landing URL as Production."""
SOURCE = "https://webapp.calcomp.co.th/att/"

def probe_source():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=[
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
