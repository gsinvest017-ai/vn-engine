/**
 * TextBox — typewriter dialogue/narration display.
 */
export class TextBox {
  constructor(root) {
    this.root     = root;
    this.box      = root.querySelector('#textbox');
    this.nameEl   = root.querySelector('#speaker-name');
    this.textEl   = root.querySelector('#dialogue-text');
    this.arrow    = root.querySelector('#advance-arrow');
    this._typing  = false;
    this._skipReq = false;
    this._speed   = 28;  // ms per character
  }

  async show(text, { speaker = '', style = 'normal' } = {}) {
    this.box.classList.remove('hidden');
    this.arrow.style.visibility = 'hidden';
    this._typing  = true;
    this._skipReq = false;

    this.nameEl.textContent = speaker;

    if (style === 'quote') {
      this.textEl.className = 'narration-quote';
    } else {
      this.textEl.className = '';
    }

    this.textEl.textContent = '';

    await this._typewrite(text);
    this._typing = false;
    this.arrow.style.visibility = 'visible';
  }

  _typewrite(text) {
    return new Promise(resolve => {
      let i = 0;
      const tick = () => {
        if (this._skipReq || i >= text.length) {
          this.textEl.textContent = text;
          this._skipReq = false;
          resolve();
          return;
        }
        this.textEl.textContent += text[i++];
        setTimeout(tick, this._speed);
      };
      tick();
    });
  }

  isTyping() { return this._typing; }

  skipType() {
    if (this._typing) this._skipReq = true;
  }

  hide() {
    this.box.classList.add('hidden');
    this.textEl.textContent = '';
    this.nameEl.textContent = '';
  }

  setSpeed(ms) { this._speed = ms; }
}
