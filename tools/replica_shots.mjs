// Screenshot every screen of tools/replica.html, both themes.
//
//   npm i playwright && node tools/replica_shots.mjs [outDir]
//
// Needs a Chromium; set PLAYWRIGHT_CHROMIUM to point at one if the default
// download was skipped.
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const outDir = process.argv[2] || 'out/replica';
mkdirSync(outDir, { recursive: true });
const b = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM
  ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {});
const p = await b.newPage({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 2 });
p.on('pageerror', e => console.log('PAGE ERROR:', e.message));
await p.goto('file://' + new URL('.', import.meta.url).pathname + 'replica.html');
await p.waitForFunction(() => document.body.dataset.ready === '1', { timeout: 15000 });
await p.waitForTimeout(1200);
const cols = await p.$$('.col');
console.log('frames:', cols.length);
for (let i = 0; i < cols.length; i++) {
  const name = (await cols[i].$eval('.caption', e => e.textContent))
    .replace(/[^a-z0-9]+/gi, '-').toLowerCase();
  await cols[i].screenshot({ path: `${outDir}/shot-${String(i).padStart(2,'0')}-${name}.png` });
}
await b.close();
