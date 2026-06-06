/**
 * VNEngine — main command executor.
 * Instantiate once; call engine.loadStory(config) then engine.start().
 */
import { parseScript }   from './parser.js';
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
    this.textbox   = new TextBox(rootEl);
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
      const cont = await this._exec(cmd);
      if (cont === 'wait_input') await this._awaitInput();
      if (cont === 'stop') break;
    }
    if (this.cmdIdx >= this.allCommands.length) this._onEnd();
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
      case 'char_show':   this.chars.show(cmd.id, cmd.pos, cmd.expr); return null;
      case 'char_hide':   this.chars.hide(cmd.id); return null;
      case 'char_expr':   this.chars.setExpr(cmd.id, cmd.expr); return null;
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
      case 'chapter_end': return this._doChapterEnd();
      case 'end':         return 'stop';
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

  async _doDialogue(cmd) {
    this.state.addHistory({ speaker: cmd.character, text: cmd.text });
    const displayName = this.config.characters?.[cmd.character]?.name || cmd.character;

    // Auto-show character sprite if not already on screen
    if (cmd.character && !this.chars.displayed[cmd.character]) {
      this.chars.show(cmd.character, 'center', 'normal');
    }
    // Dim all other characters, highlight the speaker
    this.chars.highlight(cmd.character);

    await this.textbox.show(cmd.text, { speaker: displayName, style: 'dialogue' });
    if (!this.skipMode) return 'wait_input';
    await this._sleep(60);
    return null;
  }

  async _doNarration(cmd) {
    if (!cmd.text) return null;
    this.state.addHistory({ speaker: '', text: cmd.text });
    // Narration: no single speaker, restore all characters to equal brightness
    this.chars.clearHighlight();
    await this.textbox.show(cmd.text, { speaker: '', style: cmd.style });
    if (!this.skipMode) return 'wait_input';
    await this._sleep(40);
    return null;
  }

  async _doChoice(cmd) {
    this.textbox.hide();
    const chosen = await this.choices.show(cmd.options);
    this.choices.hide();
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

  _onEnd() {
    this.textbox.show('— 完 —', { speaker: '', style: 'normal' });
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
    gameScreen?.addEventListener('click', advance);

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
