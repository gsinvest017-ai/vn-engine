/**
 * TextBox — typewriter dialogue/narration display.
 */
export class TextBox {
  constructor(root, assetBase = '../assets') {
    this.root        = root;
    this.assetBase   = assetBase;
    this.box         = root.querySelector('#textbox');
    this.nameEl      = root.querySelector('#speaker-name');
    this.textEl      = root.querySelector('#dialogue-text');
    this.arrow       = root.querySelector('#advance-arrow');
    this.portraitBox = root.querySelector('#portrait');
    this.portraitImg = root.querySelector('#portrait-img');
    this._typing  = false;
    this._skipReq = false;
    this._speed   = 28;  // ms per character
    this._portraitKey = '';  // 目前顯示的 "id:expr"，避免重複載入

    // 視口尺寸改變（轉向/縮放）→ 重新定位頭像裁切
    window.addEventListener('resize', () => {
      const img = this.portraitImg;
      if (img?.src && !this.portraitBox.classList.contains('hidden')) {
        this._placePortrait(img);
      }
    });
  }

  /** 設定對話框頭像；portrait = { id, expr } 或 null（隱藏） */
  setPortrait(portrait) {
    if (!this.portraitBox) return;
    if (!portrait || !portrait.id) {
      this.portraitBox.classList.add('hidden');
      this._portraitKey = '';
      return;
    }
    const { id, expr = 'normal' } = portrait;
    const key = `${id}:${expr}`;
    this.portraitBox.classList.remove('hidden');
    if (key === this._portraitKey) return;
    this._portraitKey = key;

    const img = this.portraitImg;
    img.onerror = () => {
      // PNG 不存在 → 試 SVG；再失敗就隱藏框（不留破圖）
      img.onerror = () => this.portraitBox.classList.add('hidden');
      img.src = `${this.assetBase}/characters/${id}/${expr}.svg`;
    };
    img.style.opacity = '0';
    img.onload = () => {
      this._placePortrait(img);
      img.style.opacity = '1';
    };
    img.src = `${this.assetBase}/characters/${id}/${expr}.png`;
  }

  /**
   * 立繪 PNG 常有大片透明邊（每張內容位置不同），固定 object-position
   * 裁不到頭部。改為下取樣到離屏 canvas 掃 alpha 找內容 bounding box，
   * 再以「內容寬貼齊框寬、內容頂貼齊框頂」定位，結果按 src 快取。
   */
  _contentBBox(img) {
    if (!this._bboxCache) this._bboxCache = new Map();
    if (this._bboxCache.has(img.src)) return this._bboxCache.get(img.src);
    let bbox = null;
    try {
      const S = 64;
      const c = document.createElement('canvas');
      c.width  = S;
      c.height = Math.max(1, Math.round(S * img.naturalHeight / img.naturalWidth));
      const ctx = c.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, c.width, c.height);
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      let x0 = c.width, y0 = c.height, x1 = -1, y1 = -1;
      for (let y = 0; y < c.height; y++) {
        for (let x = 0; x < c.width; x++) {
          if (d[(y * c.width + x) * 4 + 3] > 30) {
            if (x < x0) x0 = x;
            if (x > x1) x1 = x;
            if (y < y0) y0 = y;
            if (y > y1) y1 = y;
          }
        }
      }
      if (x1 >= 0) {
        bbox = {
          x0: x0 / c.width,  y0: y0 / c.height,
          x1: (x1 + 1) / c.width,  y1: (y1 + 1) / c.height,
        };
      }
    } catch (e) { /* SVG taint 或其他失敗 → fallback CSS cover */ }
    this._bboxCache.set(img.src, bbox);
    return bbox;
  }

  _placePortrait(img) {
    const bbox = this._contentBBox(img);
    if (!bbox) {
      // fallback：交回 CSS object-fit cover
      img.style.cssText = '';
      return;
    }
    const fw = this.portraitBox.clientWidth;
    const nw = img.naturalWidth, nh = img.naturalHeight;
    const cx0 = bbox.x0 * nw, cw = (bbox.x1 - bbox.x0) * nw;
    const cy0 = bbox.y0 * nh;
    const scale = fw / cw;
    img.style.position  = 'absolute';
    img.style.maxWidth  = 'none';
    img.style.width     = `${nw * scale}px`;
    img.style.height    = 'auto';
    img.style.objectFit = 'unset';
    img.style.left      = `${-cx0 * scale}px`;
    img.style.top       = `${-cy0 * scale}px`;
  }

  async show(text, { speaker = '', style = 'normal', portrait = undefined } = {}) {
    this.box.classList.remove('hidden');
    this.arrow.style.visibility = 'hidden';
    this._typing  = true;
    this._skipReq = false;

    this.nameEl.textContent = speaker;
    if (portrait !== undefined) this.setPortrait(portrait);

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
