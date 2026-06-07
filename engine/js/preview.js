/**
 * preview.js — Dev Dashboard 雙欄編輯的即時預覽模式（?devPreview=1）。
 *
 * 不跑互動主迴圈：收到 postMessage {type:'vns-preview', content, line} 後，
 * parse 劇本並從頭累積「游標行（含）之前」的持續狀態（背景 / 天氣 / BGM /
 * 角色 pos+expr / 最後一句台詞），與上次套用結果 diff，只更新變動部分，
 * 用真實 managers 渲染 — 與遊戲本體零視覺漂移。
 *
 * 瞬時類指令（shake / flash / fade / wait / choice 跳轉）預覽中不執行。
 */
import { parseScript }     from './core/parser.js';
import { accumulateState } from './core/replay.js';
import { SceneManager }   from './managers/scene.js';
import { CharManager }    from './managers/character.js';
import { AudioManager }   from './managers/audio.js';
import { EffectsManager } from './managers/effects.js';
import { TextBox }        from './ui/textbox.js';

export class PreviewDriver {
  constructor(root, assetBase = '../assets', storyConfig = {}) {
    this.root    = root;
    this.config  = storyConfig;
    this.scene   = new SceneManager(root, assetBase);
    this.chars   = new CharManager(root, assetBase);
    this.audio   = new AudioManager(assetBase);
    this.fx      = new EffectsManager(root);
    this.textbox = new TextBox(root, assetBase);

    this._applied = { bg: null, weather: null, bgm: null, chars: {}, text: null,
                      dim: null, vignette: null };
    this._soundOn = false;
    this._pendingBgm = null;

    // 直接進入遊戲畫面
    root.querySelector('#main-menu')?.classList.remove('active');
    root.querySelector('#game-screen')?.classList.add('active');

    this._buildHud();
    this._listen();
  }

  /* ── 預覽 HUD：BGM badge（兼聲音解鎖按鈕）+ 模式標記 ── */

  _buildHud() {
    const hud = document.createElement('div');
    hud.id = 'preview-hud';
    hud.style.cssText = [
      'position:absolute', 'top:6px', 'left:8px', 'z-index:9999',
      'display:flex', 'gap:6px', 'align-items:center',
      'font-family:monospace', 'font-size:11px', 'pointer-events:auto',
    ].join(';');

    this._bgmBadge = document.createElement('button');
    this._bgmBadge.style.cssText = [
      'background:rgba(8,6,2,.82)', 'border:1px solid rgba(192,120,32,.45)',
      'color:#c88020', 'padding:2px 10px', 'cursor:pointer',
      'font:inherit', 'letter-spacing:.05em',
    ].join(';');
    this._bgmBadge.textContent = '♪ —';
    this._bgmBadge.title = '點擊開關預覽聲音（瀏覽器需手勢解鎖音訊）';
    this._bgmBadge.addEventListener('click', () => this._toggleSound());

    const tag = document.createElement('span');
    tag.textContent = 'PREVIEW';
    tag.style.cssText = [
      'background:rgba(192,120,32,.85)', 'color:#000', 'padding:2px 8px',
      'letter-spacing:.12em', 'font-size:10px',
    ].join(';');

    hud.appendChild(tag);
    hud.appendChild(this._bgmBadge);
    this.root.appendChild(hud);
  }

  _toggleSound() {
    this._soundOn = !this._soundOn;
    if (this._soundOn) {
      this.audio._resume();
      if (this._pendingBgm) this.audio.bgm(this._pendingBgm, 400);
      this._updateBgmBadge();
    } else {
      this.audio.bgmStop(200);
      this._updateBgmBadge();
    }
  }

  _updateBgmBadge() {
    const id = this._pendingBgm;
    this._bgmBadge.textContent = `${this._soundOn ? '♪' : '🔇'} ${id || '—'}`;
    this._bgmBadge.style.color = this._soundOn ? '#e8a030' : '#8a7a60';
  }

  /* ── postMessage 接線 ── */

  _listen() {
    window.addEventListener('message', e => {
      if (e.origin !== window.location.origin) return;
      const d = e.data;
      if (d?.type === 'vns-preview' && typeof d.content === 'string') {
        this.apply(d.content, d.line | 0);
      }
    });
    // 握手：告知 parent 可以開始送內容
    window.parent?.postMessage({ type: 'vns-preview-ready' }, window.location.origin);
  }

  /* ── 狀態重建（共用 core/replay.js） ── */

  _stateAt(commands, line) {
    return accumulateState(commands, { uptoLine: line > 0 ? line : Infinity });
  }

  /* ── diff 套用 ── */

  async apply(content, line) {
    let cmds;
    try { cmds = parseScript(content); }
    catch (e) { console.warn('[preview] parse error', e); return; }

    const st = this._stateAt(cmds, line);
    const prev = this._applied;

    // 背景（無轉場，瞬切）
    if (st.bg !== prev.bg && st.bg) this.scene.set(st.bg, 'none');

    // 天氣
    const wKey = JSON.stringify(st.weather);
    if (wKey !== JSON.stringify(prev.weather) && st.weather) {
      this.fx.setWeather(st.weather);
    }

    // 角色：per-char diff（移除 → hide；新增/變動 → show/setExpr）
    for (const id of Object.keys(prev.chars)) {
      if (!st.chars[id]) this.chars.hide(id);
    }
    for (const [id, c] of Object.entries(st.chars)) {
      const p = prev.chars[id];
      if (!p || p.pos !== c.pos) this.chars.show(id, c.pos, c.expr);
      else if (p.expr !== c.expr) this.chars.setExpr(id, c.expr);
    }

    // dim / vignette
    if (st.dim !== prev.dim) this.fx.dim(st.dim ?? 0);
    if (st.vignette !== prev.vignette) this.fx.vignette(st.vignette ?? 0);

    // BGM：badge 永遠更新；實際播放只在聲音解鎖後
    if (st.bgm !== prev.bgm) {
      this._pendingBgm = st.bgm;
      this._updateBgmBadge();
      if (this._soundOn) {
        if (st.bgm) this.audio.bgm(st.bgm, 300);
        else this.audio.bgmStop(300);
      }
    }

    // 台詞（instant，speaker 高亮與頭像跟遊戲一致）
    const tKey = JSON.stringify(st.text);
    if (tKey !== JSON.stringify(prev.text)) {
      if (st.text) {
        const displayName = st.text.charId
          ? (this.config.characters?.[st.text.charId]?.name || st.text.charId)
          : '';
        if (st.text.charId) this.chars.highlight(st.text.charId);
        else this.chars.clearHighlight();
        const narratorId = this.config?.narratorPortrait !== undefined
          ? this.config.narratorPortrait : 'narrator';
        const pid = st.text.charId || narratorId;
        this.textbox.show(st.text.text, {
          speaker: displayName,
          style: st.text.style,
          portrait: pid ? { id: pid, expr: st.exprState[pid] || 'normal' } : null,
          instant: true,
        });
      } else {
        this.textbox.hide();
      }
    }

    this._applied = st;
  }
}
