#!/usr/bin/env python3
"""Exercise the real debugger: cached runs, phase seeking, notes, comparisons.

Uses sample VID-20260827-WA0010.mp4 and its cached pose. No model API calls.
Run: .venv/bin/python tools/debugweb/browser_e2e.py --base http://127.0.0.1:8093 --no-start
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', default='http://127.0.0.1:8093')
    ap.add_argument('--no-start', action='store_true')
    ap.add_argument('--out', default='/tmp/barrapp-debugweb-qa')
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    proc = None
    if not args.no_start:
        from urllib.parse import urlparse
        proc = subprocess.Popen([sys.executable, str(ROOT/'tools/debugweb/server.py'), '--port', str(urlparse(args.base).port)], cwd=ROOT)
        for _ in range(60):
            try:
                with urlopen(args.base, timeout=1): break
            except OSError: time.sleep(.25)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width':1500, 'height':1050})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(args.base, wait_until='networkidle')
            page.wait_for_selector('.video-card')
            assert page.locator('#gallery').is_visible()
            page.locator('#search').fill('VID-20260827-WA0010.mp4')
            assert page.locator('.video-card').count() == 1
            page.wait_for_function("document.querySelector('.video-card img').naturalWidth > 0")
            page.locator('#search').fill('')
            page.screenshot(path=str(out/'gallery-desktop.png'), full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(out/'gallery-mobile.png'), full_page=True)
            page.set_viewport_size({'width':1500,'height':1050})
            page.locator('.video-card').filter(has=page.locator('h2', has_text='VID-20260827-WA0010.mp4')).click()
            page.wait_for_selector('#clip')
            page.wait_for_function("document.querySelector('#clip-name').textContent === 'VID-20260827-WA0010.mp4'")
            page.click('#run')
            page.wait_for_function("!document.querySelector('#run').disabled", timeout=120000)
            assert 'err' not in page.locator('#status').get_attribute('class'), page.locator('#status').inner_text()
            page.wait_for_selector('.assessment')
            assert page.locator('.rep').count() == 2
            page.wait_for_function("document.querySelector('#video').readyState >= 2")
            page.wait_for_function("document.querySelector('#media-status').textContent.includes('exact keypoints')")
            # The player is tied to the actual pipeline's phase bounds.
            phase = page.locator('.rep .phases button', has_text='support').first
            phase.click()
            page.wait_for_function("document.querySelector('#video').currentTime > 0")
            page.wait_for_function('''() => {
                const c = document.querySelector('#overlay');
                const pixels = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
                let n=0; for(let i=3;i<pixels.length;i+=4) if(pixels[i]) n++;
                return n > 100;
            }''')
            before = page.locator('#video').evaluate('(v)=>v.currentTime')
            page.click('#next-frame')
            page.wait_for_function('(t)=>document.querySelector("#video").currentTime > t', arg=before)
            page.locator('#review').fill('QA: review support extension at the selected phase.')
            trace = page.locator('#trace').input_value()
            page.reload(wait_until='networkidle')
            try:
                page.wait_for_function('(t)=>document.querySelector("#trace").value === t', arg=trace, timeout=10000)
            except Exception:
                print('Reload state:', page.url, 'expected', trace, 'actual', page.locator('#trace').input_value(), 'status', page.locator('#status').text_content(), 'errors', errors)
                raise
            assert 'review support extension' in page.locator('#review').input_value()
            with page.expect_download() as download:
                page.click('#export')
            path = out/'debug-bundle.json'; download.value.save_as(path)
            data = json.loads(path.read_text())
            assert data['trace']['traceId'] == trace
            assert data['payload']['n_reps'] == 2 and data['review'].startswith('QA:')
            page.click('#diff')
            page.wait_for_selector('pre.diff')
            assert page.locator('#entries-title').text_content().startswith('diff')
            # A failed request must recover the run control and explain the error.
            page.route('**/api/runs', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"QA unavailable"}'))
            page.click('#run')
            page.wait_for_function("!document.querySelector('#run').disabled")
            assert 'QA unavailable' in page.locator('#status').inner_text()
            page.unroute('**/api/runs')
            page.reload(wait_until='networkidle')
            page.wait_for_selector('.assessment')
            page.locator('.rep .phases button', has_text='support').first.click()
            page.wait_for_function("document.querySelector('#video').currentTime > 1")
            page.screenshot(path=str(out/'desktop.png'), full_page=True)
            page.set_viewport_size({'width':390, 'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'horizontal overflow'
            page.screenshot(path=str(out/'mobile.png'), full_page=True)
            # Import a real video through the user-facing file control, then
            # remove only this test's uniquely named copy.
            page.set_input_files('#upload', str(ROOT/'VID-20260827-WA0010.mp4'))
            page.wait_for_function("document.querySelector('#status').textContent.includes('Video imported')", timeout=60000)
            imported = page.locator('#clip').input_value()
            assert imported.startswith('VID-20260827-WA0010-') and imported.endswith('.mp4')
            assert page.locator('#right').inner_text() == ''
            assert (ROOT/'data/videos'/imported).stat().st_size == (ROOT/'VID-20260827-WA0010.mp4').stat().st_size
            (ROOT/'data/videos'/imported).unlink()
            assert not errors, errors
            print(f'PASS: real 2-rep run, pinned pose, phase seeking, frame stepping, review persistence, export, comparison, network failure recovery, mobile layout, real video import. Artifacts: {out}')
            browser.close()
    finally:
        if proc:
            proc.terminate(); proc.wait(timeout=10)

if __name__ == '__main__':
    main()
