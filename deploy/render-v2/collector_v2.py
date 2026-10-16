"""Attendance V2 source probe. Fail closed: never infer absence from unavailable source."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

SOURCE = "https://webapp.calcomp.co.th/att/index.php"

def probe_source():
    """Browser-based connectivity probe, not an attendance result."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        try:
            page = browser.new_page()
            response = page.goto(SOURCE, wait_until="domcontentloaded", timeout=25000)
            status = response.status if response else None
            title = page.title()[:120]
            if status != 200:
                return {"source":"unavailable","http_status":status,"safe_to_mark_missing":False}
            return {"source":"reachable","http_status":status,"page_title":title,"safe_to_mark_missing":False,
                    "note":"Source reachable only. Scan query and completeness validation not yet enabled."}
        finally:
            browser.close()
