/**
 * VNEngine — main command executor.
 * Instantiate once; call engine.loadStory(config) then engine.start().
 */
import { parseScript }   from './parser.js';
import { accumulateState, applySet, evalCondition } from './replay.js';
import { GameState }     from './state.js';
import { SceneManager }  from '../managers/scene.js';
import { CharManager }   from '../managers/character.js';
import { AudioManager }  from '../managers/audio.js';
import { EffectsManager }from '../managers/effects.js';
import { TextBox }       from '../ui/textbox.js';
import { ChoiceBox }     from '../ui/choicebox.js';

export class VNEngine {
  constructor(rootEl, assetBase = '../assets') {
    this.root      = rootEl;
    this.assetBase = assetBase;
    this.state     = new GameState();
    this.scene     = new SceneManager(rootEl, assetBase);
    this.chars     = new CharManager(rootEl, assetBase);
    this.audio     = new AudioManager(assetBase);
    this.fx        = new EffectsManager(rootEl);
    this.textbox   = new TextBox(rootEl, assetBase);
    this.choices   = new ChoiceBox(rootEl);

    this.chapters  = [];   // loaded command arrays
    this.cmdIdx    = 0;
    this.running   = false;
    this.waitInput = false;
    this.autoMode  = false;
    this.skipMode  = false;
    this.autoDelay = 2200;
    this._inputResolve = null;
    this._autoTimer    = null;
    this._exprState    = {};   // charId → 最後表情（供對話框頭像使用）

    this._bindInput();
  }

  /* ── Story Loading ── */

  async loadStory(config) {
    this.config   = config;
    this.chapters = [];
    for (const chapterPath of config.chapters) {
      const text = await fetch(chapterPath).then(r => r.text());
      this.chapters.push(parseScript(text));
    }
    this.state.chapter  = 0;
    this.state.cmdIndex = 0;
    this._preloadAssets();   // fire-and-forget：背景/立繪預載，消除首次切景閃爍
  }

  /** 掃全劇本出現過的背景與立繪，預載進瀏覽器快取 */
  _preloadAssets() {
    const bgs = new Set(), sprites = new Set();
    for (const cmd of this.allCommands) {
      if (cmd.type === 'scene' && cmd.bg) bgs.add(cmd.bg);
      if (cmd.type === 'char_show') sprites.add(`${cmd.id}/${cmd.expr}`);
      if (cmd.type === 'char_expr') sprites.add(`${cmd.id}/${cmd.expr}`);
      if (cmd.type === 'dialogue' && cmd.character) sprites.add(`${cmd.character}/normal`);
    }
    const urls = [
      ...[...bgs].map(b => `${this.assetBase}/backgrounds/${b}.png`),
      ...[...sprites].map(s => `${this.assetBase}/characters/${s}.png`),
    ];
    for (const url of urls) {
      const img = new Image();
      img.src = url;   // 失敗無妨（svg fallback 在實際顯示時處理）
    }
  }

  get allCommands() {
    // Flatten all chapters into a single array, tagged with chapter index
    if (!this._flat || this._flatSrc !== this.chapters) {
      let offset = 0;
      this._flat = [];
      for (let ci = 0; ci < this.chapters.length; ci++) {
        for (const cmd of this.chapters[ci]) {
          this._flat.push({ ...cmd, _chapterIdx: ci, _offset: offset++ });
        }
      }
      this._flatSrc = this.chapters;
    }
    return this._flat;
  }

  /* ── Main Loop ── */

  async start(fromIndex = 0) {
    this.cmdIdx  = fromIndex;
    this.running = true;
    this._run();
  }

  async _run() {
    while (this.running && this.cmdIdx < this.allCommands.length) {
      const cmd = this.allCommands[this.cmdIdx++];
      // 記錄「目前執行中指令」的 index 與章節，存檔據此恢復
      this.state.cmdIndex = this.cmdIdx - 1;
      if (cmd._chapterIdx !== undefined) this.state.chapter = cmd._chapterIdx;
      const cont = await this._exec(cmd);
      if (cont === 'wait_input') await this._awaitInput();
      if (cont === 'stop') break;
    }
    if (this.cmdIdx >= this.allCommands.length) this._onEnd();
  }

  /* ── 讀檔/中途起跑：重建累積狀態 ── */

  /** 套用 accumulateState 的結果到各 manager（瞬切、無轉場） */
  async applyState(st) {
    if (st.bg) await this.scene.set(st.bg, 'none');
    if (st.weather) this.fx.setWeather(st.weather);
    this.fx.dim(st.dim ?? 0);
    this.fx.vignette(st.vignette ?? 0);
    for (const [id, c] of Object.entries(st.chars)) {
      this.chars.show(id, c.pos, c.expr);
    }
    Object.assign(this._exprState, st.exprState);
    if (st.bgm) this.audio.bgm(st.bgm, 400);
    if (st.text) {
      const displayName = st.text.charId
        ? (this.config.characters?.[st.text.charId]?.name || st.text.charId)
        : '';
      if (st.text.charId) this.chars.highlight(st.text.charId);
      const narratorId = this.config?.narratorPortrait !== undefined
        ? this.config.narratorPortrait : 'narrator';
      const pid = st.text.charId || narratorId;
      await this.textbox.show(st.text.text, {
        speaker: displayName,
        style: st.text.style,
        portrait: pid ? { id: pid, expr: this._exprState[pid] || 'normal' } : null,
        instant: true,
      });
    }
  }

  /** 中途起跑（dev jump / 從游標行開始玩）：先重建 idx 之前的狀態再續跑 */
  async startFrom(idx) {
    if (idx > 0) {
      const st = accumulateState(this.allCommands, { uptoIndex: idx - 1 });
      this.state.variables = st.variables;
      await this.applyState(st);
    }
    return this.start(idx);
  }

  /** 讀檔：重建存檔 index（含）之前的畫面狀態後，從下一指令續跑 */
  async resumeFromSave() {
    const idx = this.state.cmdIndex || 0;
    const st  = accumulateState(this.allCommands, { uptoIndex: idx });
    // 存檔的 variables 為準（含玩家實際走過的分支）
    st.variables = { ...st.variables, ...this.state.variables };
    this.state.variables = st.variables;
    await this.applyState(st);
    this.running = true;
    this.cmdIdx  = idx + 1;
    // 目前這句已重建顯示 → 等輸入後繼續
    await this._awaitInput();
    this._run();
  }

  async _exec(cmd) {
    if (this.skipMode && !['choice','end','chapter_end'].includes(cmd.type)) {
      // fast-forward: only run structural commands
      if (!['chapter','label','jump','fade','scene'].includes(cmd.type)) return null;
    }

    switch (cmd.type) {
      case 'chapter':     return this._doChapter(cmd);
      case 'scene':       return this._doScene(cmd);
      case 'weather':     this.fx.setWeather(cmd); return null;
      case 'char_show':   this._exprState[cmd.id] = cmd.expr; this.chars.show(cmd.id, cmd.pos, cmd.expr); return null;
      case 'char_hide':   this.chars.hide(cmd.id); return null;
      case 'char_expr':   this._exprState[cmd.id] = cmd.expr; this.chars.setExpr(cmd.id, cmd.expr); this._refreshPortrait(cmd.id); return null;
      case 'char_move':   this.chars.move(cmd.id, cmd.pos, cmd.duration); return null;
      case 'sfx_play':    this.audio.sfx(cmd.id, { volume: cmd.volume, loop: cmd.loop, delay: cmd.delay }); return null;
      case 'sfx_stop':    this.audio.sfxStop(cmd.id, cmd.fade); return null;
      case 'bgm_play':    this.audio.bgm(cmd.id, cmd.fade); return null;
      case 'bgm_stop':    this.audio.bgmStop(cmd.fade); return null;
      case 'bgm_volume':  this.audio.bgmVol(cmd.value); return null;
      case 'effect':      return this._doEffect(cmd);
      case 'fade':        return this._doFade(cmd);
      case 'wait':        await this._sleep(cmd.ms); return null;
      case 'pause':       return 'wait_input';
      case 'dialogue':    return this._doDialogue(cmd);
      case 'narration':   return this._doNarration(cmd);
      case 'choice':      return this._doChoice(cmd);
      case 'label':       return null;  // labels are no-ops at runtime
      case 'jump':        this._jump(cmd.label); return 'jump';
      case 'set':         applySet(this.state.variables, cmd); return null;
      case 'if_jump':
        if (evalCondition(this.state.variables, cmd)) { this._jump(cmd.label); return 'jump'; }
        return null;
      case 'chapter_end':   return this._doChapterEnd();
      case 'suspense_end':  return this._doSuspenseEnd(cmd);
      case 'end':           return 'stop';
      default:            return null;
    }
  }

  /* ── Command Handlers ── */

  async _doChapter(cmd) {
    const card = this.root.querySelector('#chapter-card');
    const num  = this.root.querySelector('#chapter-num');
    const name = this.root.querySelector('#chapter-name');
    const match = cmd.title.match(/^(第.章)\s*(.*)/);
    num.textContent  = match ? match[1] : '';
    name.textContent = match ? match[2] : cmd.title;
    card.classList.remove('hidden');
    await this._sleep(this.skipMode ? 100 : 2200);
    card.classList.add('hidden');
    return null;
  }

  async _doScene(cmd) {
    if (cmd.music) this.audio.bgm(cmd.music, 1500);
    await this.scene.set(cmd.bg, cmd.transition);
    return null;
  }

  async _doEffect(cmd) {
    switch (cmd.fx) {
      case 'shake':    await this.fx.shake(cmd.intensity, cmd.duration); break;
      case 'flash':    await this.fx.flash(cmd.color, cmd.duration); break;
      case 'dim':      this.fx.dim(cmd.level); break;
      case 'flicker':  await this.fx.flicker(cmd.count); break;
      case 'darkness': this.fx.dim(0.92); break;
      case 'vignette': this.fx.vignette(cmd.intensity); break;
      case 'clear':    this.fx.clearAll(); break;
    }
    return null;
  }

  async _doFade(cmd) {
    await this.fx.fade(cmd.direction, cmd.color, cmd.duration);
    return null;
  }

  /** 對話框頭像描述：取角色最後表情；narration 用 narratorPortrait 角色 */
  _portraitFor(charId) {
    if (!charId) return null;
    return { id: charId, expr: this._exprState[charId] || 'normal' };
  }

  /** 若目前頭像正是 charId，表情變化時即時刷新 */
  _refreshPortrait(charId) {
    const key = this.textbox._portraitKey || '';
    if (key.startsWith(`${charId}:`)) {
      this.textbox.setPortrait(this._portraitFor(charId));
    }
  }

  async _doDialogue(cmd) {
    this.state.addHistory({ speaker: cmd.character, text: cmd.text });
    const displayName = this.config.characters?.[cmd.character]?.name || cmd.character;

    // Auto-show character sprite if not already on screen
    if (cmd.character && !this.chars.displayed[cmd.character]) {
      this._exprState[cmd.character] ??= 'normal';
      this.chars.show(cmd.character, 'center', 'normal');
    }
    // Dim all other characters, highlight the speaker
    this.chars.highlight(cmd.character);

    await this.textbox.show(cmd.text, {
      speaker: displayName,
      style: 'dialogue',
      portrait: this._portraitFor(cmd.character),
    });
    if (!this.skipMode) return 'wait_input';
    await this._sleep(60);
    return null;
  }

  async _doNarration(cmd) {
    if (!cmd.text) return null;
    this.state.addHistory({ speaker: '', text: cmd.text });
    // Narration: no single speaker, restore all characters to equal brightness
    this.chars.clearHighlight();
    // 旁白 = 主角內心獨白 → 常駐顯示 narrator 頭像（config 可關閉）
    const narratorId = this.config?.narratorPortrait !== undefined
      ? this.config.narratorPortrait : 'narrator';
    await this.textbox.show(cmd.text, {
      speaker: '',
      style: cmd.style,
      portrait: this._portraitFor(narratorId),
    });
    if (!this.skipMode) return 'wait_input';
    await this._sleep(40);
    return null;
  }

  async _doChoice(cmd) {
    this.textbox.hide();
    const chosen = await this.choices.show(cmd.options);
    this.choices.hide();
    if (chosen) this.state.addHistory({ speaker: '▸ 選擇', text: chosen.text });
    if (chosen?.label) this._jump(chosen.label);
    return null;
  }

  async _doChapterEnd() {
    await this.fx.fade('out', 'black', 1200);
    await this._sleep(400);
    await this.fx.fade('in', 'black', 800);
    return null;
  }

  _jump(label) {
    const idx = this.allCommands.findIndex(c => c.type === 'label' && c.name === label);
    if (idx >= 0) this.cmdIdx = idx + 1;
  }

  async _doSuspenseEnd(cmd) {
    this.textbox.hide();
    await this.fx.suspenseEnd({ message: cmd.message, duration: cmd.duration });
    return 'stop';
  }

  _onEnd() {
    this.textbox.show('— 完 —', { speaker: '', style: 'normal', portrait: null, instant: true });
    this._showEndScreen();
  }

  /** 結局出口：回主選單按鈕（reload 重置所有 runtime 狀態，存檔在 localStorage 不受影響） */
  _showEndScreen() {
    if (this.root.querySelector('#end-screen')) return;
    const el = document.createElement('div');
    el.id = 'end-screen';
    el.innerHTML = `<button class="menu-btn" id="end-back-menu">回到主選單</button>`;
    this.root.appendChild(el);
    el.querySelector('#end-back-menu').addEventListener('click', () => location.reload());
    requestAnimationFrame(() => el.classList.add('show'));
  }

  /* ── 設定套用（由設定面板呼叫） ── */

  applySettings(s = {}) {
    if (s.textSpeed != null) this.textbox.setSpeed(Number(s.textSpeed));
    if (s.autoDelay != null) this.autoDelay = Number(s.autoDelay);
    if (s.bgmVol    != null) this.audio.bgmVol(Number(s.bgmVol));
    if (s.sfxVol    != null) this.audio.sfxVol(Number(s.sfxVol));
  }

  /* ── Input Handling ── */

  _bindInput() {
    const advance = () => {
      // Skip typewriter first; next click will advance to the next command
      if (this.textbox.isTyping()) {
        this.textbox.skipType();
        return;
      }
      if (this._inputResolve) {
        const fn = this._inputResolve;
        this._inputResolve = null;
        this.waitInput = false;
        fn();
      }
    };

    const gameScreen = this.root.querySelector('#game-screen');
    gameScreen?.addEventListener('click', e => {
      // HUD / 選擇框上的點擊不推進對話（避免按存檔同時前進一行）
      if (e.target.closest('#hud') || e.target.closest('#choice-box')) return;
      advance();
    });

    // 手機：上滑開對話記錄（menu.js 監聽 vn-swipe-up）
    let _touchY = null, _touchX = null;
    gameScreen?.addEventListener('touchstart', e => {
      _touchY = e.touches[0]?.clientY;
      _touchX = e.touches[0]?.clientX;
    }, { passive: true });
    gameScreen?.addEventListener('touchend', e => {
      if (_touchY == null) return;
      const dy = (e.changedTouches[0]?.clientY ?? _touchY) - _touchY;
      const dx = (e.changedTouches[0]?.clientX ?? _touchX) - _touchX;
      if (dy < -70 && Math.abs(dx) < 50) {
        this.root.dispatchEvent(new CustomEvent('vn-swipe-up'));
      }
      _touchY = _touchX = null;
    }, { passive: true });

    // Space / Enter / → : advance
    document.addEventListener('keydown', e => {
      if (e.code === 'Space' || e.code === 'Enter' || e.code === 'ArrowRight') {
        if (!e.ctrlKey) advance();
      }
    });

    // Ctrl hold → continuous fast-forward (skip typing + auto-advance)
    let _ffTimer = null;
    const _ff = () => {
      if (this.textbox.isTyping()) this.textbox.skipType();
      if (this._inputResolve) {
        const fn = this._inputResolve;
        this._inputResolve = null;
        this.waitInput = false;
        fn();
      }
      _ffTimer = setTimeout(_ff, 80);
    };
    document.addEventListener('keydown', e => {
      if ((e.code === 'ControlLeft' || e.code === 'ControlRight') && !_ffTimer) {
        _ff();
      }
    });
    document.addEventListener('keyup', e => {
      if (e.code === 'ControlLeft' || e.code === 'ControlRight') {
        clearTimeout(_ffTimer);
        _ffTimer = null;
      }
    });
  }

  _awaitInput() {
    if (this.autoMode) {
      return new Promise(res => {
        this._autoTimer = setTimeout(res, this.autoDelay);
      });
    }
    return new Promise(res => {
      this.waitInput = true;
      this._inputResolve = res;
    });
  }

  /* ── Controls ── */

  toggleAuto() {
    this.autoMode = !this.autoMode;
    if (this.autoMode && this.waitInput && this._inputResolve) {
      clearTimeout(this._autoTimer);
      this._autoTimer = setTimeout(() => {
        const fn = this._inputResolve;
        if (fn) { this._inputResolve = null; this.waitInput = false; fn(); }
      }, this.autoDelay);
    }
    return this.autoMode;
  }

  toggleSkip() {
    this.skipMode = !this.skipMode;
    if (this.skipMode && this._inputResolve) {
      const fn = this._inputResolve;
      this._inputResolve = null;
      this.waitInput = false;
      fn();
    }
    return this.skipMode;
  }

  /* ── Utility ── */

  _sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }
}
