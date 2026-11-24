"""Optional real-browser acceptance checks. Requires playwright + installed Chromium.
Run: pip install playwright==1.62.0; python -m playwright install chromium
     python scripts/browser_check.py [--browser-path /path/to/chromium]
Starts its own isolated server and database; never uses the research ledger.
"""
import argparse
import json
import socket
import tempfile
import threading
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from marketlens.app import create_app
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser();p.add_argument('--browser-path');a=p.parse_args()
with tempfile.TemporaryDirectory() as tmp:
    app=create_app(tmp)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        if not server.started:raise RuntimeError('Local server did not start')
        checks=[];errors=[]
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,**({'executable_path':a.browser_path} if a.browser_path else {}))
            page=browser.new_page(viewport={'width':1440,'height':1000},bypass_csp=True)  # Playwright string predicates use eval, which the app's CSP correctly forbids
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}')
            page.wait_for_function("document.querySelector('#session').options.length === 6")
            assert 'MarketLens' in page.title();checks.append('dashboard loads')
            assert 'synthetic_demo' in page.locator('#source').inner_text();checks.append('synthetic provenance visible')
            page.locator('#run').click();page.locator('#execution').wait_for(state='visible')
            assert page.locator('#comparison tbody tr').count()==3;checks.append('three execution policies render')
            assert page.locator('#executionChart svg').count()==1;checks.append('execution chart renders')
            assert page.locator('#jsonExport').get_attribute('href').endswith('/export.json');checks.append('evidence export linked')
            page.locator('[data-view=history]').click();page.locator('#historyTable button').first.wait_for()
            page.locator('#historyTable button').first.click();page.locator('#execution').wait_for(state='visible');checks.append('history reopens saved experiment')
            page.locator('#training').fill('2026-01-01T00:00');page.locator('#run').click();page.locator('#error').wait_for(state='visible')
            assert 'training_end' in page.locator('#error').inner_text();checks.append('invalid training cutoff shown')
            page.set_viewport_size({'width':390,'height':844});page.reload();page.locator('#run').wait_for()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2');checks.append('mobile page has no horizontal overflow')
            assert not errors,errors;checks.append('no uncaught JavaScript errors')
            browser.close()
        print(json.dumps({'passed':len(checks),'checks':checks},indent=2))
    finally:
        server.should_exit=True;thread.join(timeout=5)
