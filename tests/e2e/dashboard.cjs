/** Dashboard：編輯/儲存/還原、行內 lint、自動完成、新建、匯入（會自我清理） */
const { BASE, launch, check, finish } = require('./lib.cjs');

(async () => {
  const { browser, page, errors } = await launch({ viewport: { width: 1600, height: 900 } });
  await page.goto(`${BASE}/dashboard/`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  // ── 1. 新建劇本（測試專用目錄，結束後由 runner 清理） ──
  await page.evaluate(() => openNewScript());
  await page.fill('#new-story', 'e2e-ci');
  await page.fill('#new-fname', 'spec');
  await page.click('#modal-new .btn.primary');
  await page.waitForTimeout(1500);
  const created = await page.evaluate(() => ({
    active: S.activeFile,
    editing: document.getElementById('content').classList.contains('editing'),
  }));
  check('新建並進入編輯', created.active === 'scripts/e2e-ci/spec.vns' && created.editing);

  // ── 2. 行內 lint ──
  await page.fill('#script-editor', '@scene bg=nope\n@jump nowhere\n');
  await page.waitForTimeout(900);
  const lints = await page.$$eval('#editor-lint .lint-item', els => els.map(e => e.textContent));
  check('lint 抓到背景不存在', lints.some(t => t.includes('nope')));
  check('lint 抓到未定義 label', lints.some(t => t.includes('nowhere')));

  // ── 3. 自動完成 chips ──
  await page.evaluate(() => {
    const ed = document.getElementById('script-editor');
    ed.value = '@scene bg=';
    ed.setSelectionRange(ed.value.length, ed.value.length);
    ed.dispatchEvent(new Event('input'));
  });
  await page.waitForTimeout(400);
  const chips = await page.$$eval('#editor-suggest .sg-chip', els => els.map(e => e.textContent));
  check('bg= 自動完成 chips', chips.length > 0, chips.slice(0, 3).join(','));

  // ── 4. 儲存 → 改 → .bak 還原 ──
  await page.fill('#script-editor', '@chapter 版本一\n');
  await page.keyboard.press('Control+s');
  await page.waitForTimeout(700);
  await page.fill('#script-editor', '@chapter 版本二\n');
  await page.keyboard.press('Control+s');
  await page.waitForTimeout(700);
  await page.click('#btn-restore');
  await page.waitForTimeout(700);
  const restored = await page.$eval('#script-editor', el => el.value.includes('版本一'));
  check('.bak 還原', restored);

  // ── 5. 匯入 zip 之外的劇本檔（JSON upload API 直接驗證） ──
  const upload = await page.evaluate(async () => {
    const r = await fetch('/api/scripts/upload', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ story: 'e2e-ci', files: [
        { name: 'extra.vns', content: '旁白。\n' },
        { name: 'evil.py',   content: 'x' },
      ]}),
    });
    return r.json();
  });
  check('匯入 .vns 成功且擋掉 .py',
    upload.ok && upload.saved.length === 1 && upload.skipped.length === 1);

  // ── 6. path traversal 防護 ──
  const trav = await page.evaluate(async () => {
    const r = await fetch('/api/scripts/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: 'scripts/../serve.py', content: 'pwned' }),
    });
    return r.status;
  });
  check('path traversal 被拒（403）', trav === 403);

  await browser.close();
  finish(errors);
})();
