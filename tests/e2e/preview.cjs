/** 即時預覽模式：游標行 → 狀態重建（背景/角色/台詞/頭像表情） */
const { BASE, launch, check, finish } = require('./lib.cjs');

const VNS = `@scene bg=shrine_interior transition=none
@weather rain=light
@char show=narrator pos=right expr=tired

我坐在道壇裡。

@char show=diao_caidi pos=left expr=questioning

[diao_caidi] 你最近是不是又沒睡？`;

(async () => {
  const { browser, page, errors } = await launch({ viewport: { width: 960, height: 540 } });
  await page.goto(`${BASE}/engine/?devPreview=1`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  const at = (line) => page.evaluate(async ({ content, line }) => {
    window.postMessage({ type: 'vns-preview', content, line }, location.origin);
    await new Promise(r => setTimeout(r, 1200));
    return {
      bg: window.__previewDriver?.scene.current,
      chars: Object.keys(window.__previewDriver?.chars.displayed || {}).sort(),
      speaker: document.getElementById('speaker-name').textContent,
      text: document.getElementById('dialogue-text').textContent,
      portrait: document.getElementById('portrait-img').src.split('/').slice(-2).join('/'),
    };
  }, { content: VNS, line });

  const full = await at(9);
  check('整段狀態：背景', full.bg === 'shrine_interior');
  check('整段狀態：雙角色', full.chars.join(',') === 'diao_caidi,narrator');
  check('整段狀態：說話者', full.speaker === 'diao_caidi' || full.speaker === '刁才弟');
  check('整段狀態：頭像表情', full.portrait === 'diao_caidi/questioning.png');

  const mid = await at(5);
  check('游標中段：只有 narrator', mid.chars.join(',') === 'narrator');
  check('游標中段：旁白頭像 tired', mid.portrait === 'narrator/tired.png');
  check('游標中段：台詞', mid.text.includes('道壇'));

  await browser.close();
  finish(errors);
})();
