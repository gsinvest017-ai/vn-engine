/** 共用：browser 啟動 + base url + 簡易斷言 */
const { chromium } = require('playwright');

const BASE = process.env.BASE_URL || 'http://localhost:8123';

async function launch(opts = {}) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    ...opts,
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());
  return { browser, ctx, page, errors };
}

let _failures = 0;
function check(name, cond, detail = '') {
  const ok = !!cond;
  if (!ok) _failures++;
  console.log(`  [${ok ? 'ok' : 'FAIL'}] ${name}${detail ? ' — ' + detail : ''}`);
  return ok;
}

function finish(errors = []) {
  if (errors.length) {
    _failures++;
    console.log('  [FAIL] JS errors:', errors.join('; '));
  }
  if (_failures) {
    console.log(`✗ ${_failures} failure(s)`);
    process.exit(1);
  }
  console.log('✓ all passed');
}

module.exports = { BASE, launch, check, finish };
