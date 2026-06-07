/**
 * MenuUI — save/load overlay + history overlay + HUD wiring.
 */
import { GameState } from '../core/state.js';

export class MenuUI {
  constructor(root, engine) {
    this.root   = root;
    this.engine = engine;

    this._bindHUD();
    this._bindOverlays();
  }

  _bindHUD() {
    this.root.querySelector('#hud-menu')?.addEventListener('click', () => {
      this._showSaveLoad('save');
    });
    this.root.querySelector('#hud-save')?.addEventListener('click', () => {
      this._showSaveLoad('save');
    });
    this.root.querySelector('#hud-history')?.addEventListener('click', () => {
      this._showHistory();
    });

    const autoBtn = this.root.querySelector('#hud-auto');
    autoBtn?.addEventListener('click', () => {
      const on = this.engine.toggleAuto();
      autoBtn.classList.toggle('active', on);
    });

    const skipBtn = this.root.querySelector('#hud-skip');
    skipBtn?.addEventListener('click', () => {
      const on = this.engine.toggleSkip();
      skipBtn.classList.toggle('active', on);
    });
  }

  _bindOverlays() {
    this.root.querySelector('#overlay-close')?.addEventListener('click', () => {
      this.root.querySelector('#overlay-saveload').classList.add('hidden');
    });
    this.root.querySelector('#history-close')?.addEventListener('click', () => {
      this.root.querySelector('#overlay-history').classList.add('hidden');
    });
  }

  _showSaveLoad(mode) {
    const overlay = this.root.querySelector('#overlay-saveload');
    const title   = this.root.querySelector('#overlay-title');
    const slotsEl = this.root.querySelector('#save-slots');

    title.textContent = mode === 'save' ? '存檔' : '讀取';
    slotsEl.innerHTML = '';

    const slots = GameState.listSlots();
    slots.forEach(({ slot, empty, chapter, snippet, savedAt }) => {
      const el = document.createElement('div');
      el.className = 'save-slot';

      const num  = document.createElement('span');
      num.className = 'save-slot-num';
      num.textContent = slot + 1;

      const info = document.createElement('div');
      info.className = 'save-slot-info';

      if (empty) {
        info.innerHTML = '<span class="save-slot-title">— 空槽 —</span>';
      } else {
        const date = savedAt ? new Date(savedAt).toLocaleString('zh-TW') : '—';
        const snip = snippet ? `<br><span class="save-slot-snippet">${snippet}</span>` : '';
        info.innerHTML = `<span class="save-slot-title">第 ${(chapter || 0) + 1} 章</span><br>${date}${snip}`;
      }

      el.appendChild(num);
      el.appendChild(info);
      el.addEventListener('click', () => {
        if (mode === 'save') {
          if (empty || confirm(`覆蓋存檔 ${slot + 1}？`)) {
            const lastText = this.engine.state.history.at(-1)?.text || '';
            const meta = {
              chapter: this.engine.state.chapter,
              snippet: lastText.slice(0, 24),
            };
            this.engine.state.save(slot, meta);
            this._showSaveLoad('save');
          }
        } else {
          if (empty) return;
          const meta = this.engine.state.load(slot);
          if (meta) {
            overlay.classList.add('hidden');
            // 從主選單讀檔時切到遊戲畫面
            this.root.querySelector('#main-menu')?.classList.remove('active');
            this.root.querySelector('#game-screen')?.classList.add('active');
            this.engine.resumeFromSave();
          }
        }
      });

      slotsEl.appendChild(el);
    });

    overlay.classList.remove('hidden');
  }

  _showHistory() {
    const overlay = this.root.querySelector('#overlay-history');
    const list    = this.root.querySelector('#history-list');
    list.innerHTML = '';

    const history = [...this.engine.state.history].reverse();
    history.forEach(({ speaker, text }) => {
      const entry = document.createElement('div');
      entry.className = 'history-entry';
      if (speaker) {
        const sp = document.createElement('div');
        sp.className = 'history-speaker';
        sp.textContent = speaker;
        entry.appendChild(sp);
      }
      const tx = document.createElement('div');
      tx.className = 'history-text';
      tx.textContent = text;
      entry.appendChild(tx);
      list.appendChild(entry);
    });

    overlay.classList.remove('hidden');
  }
}
