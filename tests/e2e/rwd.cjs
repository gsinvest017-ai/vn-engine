/** RWD：engine 與 dashboard 在 4 種視口不得水平溢出 */
const { BASE, launch, check, finish } = require('./lib.cjs');

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet',  width: 900,  height: 1180 },
  { name: 'mobile',  width: 390,  height: 844 },
  { name: 'mobile-landscape', width: 844, height: 390 },
];
const PAGES = [
  { name: 'engine',    url: `${BASE}/engine/` },
  { name: 'dashboard', url: `${BASE}/dashboard/` },
];

(async () => {
  const { browser } = await launch();
  const allErrors = [];
  for (const pg of PAGES) {
    for (const vp of VIEWPORTS) {
      const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
      const page = await ctx.newPage();
      page.on('pageerror', e => allErrors.push(`${pg.name}@${vp.name}: ${e.message}`));
      await page.goto(pg.url, { waitUntil: 'networkidle' });
      await page.waitForTimeout(600);
      const m = await page.evaluate(() => ({
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
      }));
      check(`${pg.name} @ ${vp.name}`, m.scrollW <= m.clientW + 1,
        `scrollW=${m.scrollW} clientW=${m.clientW}`);
      await ctx.close();
    }
  }
  await browser.close();
  finish(allErrors);
})();
