// Fill of every sheet of the bench guide under print media: where the content
// ends against the pinned footer, in millimetres. Negative = running into it.
//   node docs/tools/bench-guide-measure.js docs/Level1-Station-v3-C5PHY-Bench-Guide.html
// Needs Playwright with a Chromium (npm i playwright; or set CHROME to a binary).
const path = require('path');
const { chromium } = require('playwright');
(async () => {
  const file = path.resolve(process.argv[2] || 'docs/Level1-Station-v3-C5PHY-Bench-Guide.html');
  const opts = { args: ['--no-sandbox'] };
  if (process.env.CHROME) opts.executablePath = process.env.CHROME;
  const browser = await chromium.launch(opts);
  const page = await browser.newPage({ viewport: { width: 900, height: 1200 } });
  await page.emulateMedia({ media: 'print' });
  await page.goto('file://' + file);
  const rows = await page.evaluate(() => {
    const px2mm = 25.4 / 96, out = [];
    document.querySelectorAll('section.sheet').forEach((s, i) => {
      const sr = s.getBoundingClientRect();
      const body = s.querySelector('.body') || s;
      let bottom = sr.top;
      body.querySelectorAll('*').forEach(el => { const r = el.getBoundingClientRect(); if (r.height > 0 && r.bottom > bottom) bottom = r.bottom; });
      const foot = s.querySelector('.foot');
      const ft = foot ? foot.getBoundingClientRect().top : sr.bottom;
      const h = s.querySelector('h1,h2');
      out.push({ sheet: i + 1, free: +((ft - bottom) * px2mm).toFixed(1), title: h ? h.textContent.trim().slice(0, 50) : '' });
    });
    return out;
  });
  let bad = 0;
  for (const r of rows) { if (r.free < 0) bad++; console.log(`sheet ${String(r.sheet).padStart(2)}  free ${String(r.free).padStart(6)} mm  ${r.title}`); }
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
