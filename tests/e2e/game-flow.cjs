/** 遊戲流程：頭像顯示、@set/@if 分支、存檔 → 讀檔狀態重建 */
const { BASE, launch, check, finish } = require('./lib.cjs');

(async () => {
  const { browser, page, errors } = await launch();

  // ── 1. 開始遊戲 → 旁白 narrator 頭像 ──
  await page.goto(`${BASE}/engine/`, { waitUntil: 'networkidle' });
  await page.click('button[data-action="start"]');
  await page.waitForTimeout(2600);
  for (let i = 0; i < 4; i++) { await page.click('#vn-root'); await page.waitForTimeout(250); }
  const p1 = await page.evaluate(() => ({
    hidden: document.getElementById('portrait').classList.contains('hidden'),
    src: document.getElementById('portrait-img').src,
  }));
  check('旁白顯示 narrator 頭像', !p1.hidden && p1.src.includes('/narrator/'));

  // ── 2. @set/@if 分支（data: URL 劇本；fresh page 避免與主遊戲 engine 打架） ──
  await page.goto(`${BASE}/engine/`, { waitUntil: 'networkidle' });
  const branch = await page.evaluate(async () => {
    const { VNEngine } = await import('./js/core/engine.js');
    const vns = `@set clue=1
@if clue==1 jump=good
不該出現
@label good
正確分支`;
    const eng = new VNEngine(document.getElementById('vn-root'), '../assets');
    await eng.loadStory({ chapters: ['data:text/plain;charset=utf-8,' + encodeURIComponent(vns)],
                          characters: {}, narratorPortrait: null });
    eng.start(0);
    await new Promise(r => setTimeout(r, 1200));
    return { text: document.getElementById('dialogue-text').textContent, vars: eng.state.variables };
  });
  check('@set/@if 跳到正確分支', branch.text === '正確分支' && branch.vars.clue === 1);

  // ── 3. 存檔 → reload → 讀檔重建 ──
  await page.goto(`${BASE}/engine/`, { waitUntil: 'networkidle' });
  await page.click('button[data-action="start"]');
  await page.waitForTimeout(2600);
  for (let i = 0; i < 14; i++) { await page.click('#vn-root'); await page.waitForTimeout(180); }
  await page.waitForTimeout(2500);   // 等打字機打完整行再截取，避免比對到半截字串
  const savedText = await page.$eval('#dialogue-text', el => el.textContent);
  await page.click('#hud-save');
  await page.waitForTimeout(400);
  await page.click('.save-slot');
  await page.waitForTimeout(400);
  await page.click('#overlay-close');

  await page.reload({ waitUntil: 'networkidle' });
  await page.click('button[data-action="load"]');
  await page.waitForTimeout(800);
  await page.click('.save-slot');
  await page.waitForTimeout(2200);
  const restored = await page.evaluate(() => ({
    active: document.getElementById('game-screen').classList.contains('active'),
    text: document.getElementById('dialogue-text').textContent,
    bg: [...document.querySelectorAll('.bg-image')].some(el =>
      el.style.backgroundImage && parseFloat(el.style.opacity || '1') > 0),
  }));
  check('讀檔切到遊戲畫面', restored.active);
  check('讀檔還原台詞', restored.text === savedText, `"${restored.text?.slice(0, 12)}"`);
  check('讀檔還原背景', restored.bg);

  await browser.close();
  finish(errors);
})();
