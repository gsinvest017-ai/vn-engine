/**
 * CharManager — character sprite display.
 */
export class CharManager {
  constructor(root, assetBase) {
    this.root      = root;
    this.assetBase = assetBase;
    this.slots     = {
      left:   root.querySelector('#slot-left'),
      center: root.querySelector('#slot-center'),
      right:  root.querySelector('#slot-right'),
    };
    // charId → { pos, expr, el }
    this.displayed = {};
  }

  spriteUrl(id, expr = 'normal') {
    return `${this.assetBase}/characters/${id}/${expr}.svg`;
  }

  show(id, pos = 'center', expr = 'normal') {
    const slot = this.slots[pos];
    if (!slot) return;

    // If already displayed somewhere else, remove from old slot
    if (this.displayed[id] && this.displayed[id].pos !== pos) {
      this._removeFrom(id);
    }

    let el = slot.querySelector(`[data-char-id="${id}"]`);
    if (!el) {
      el = document.createElement('img');
      el.className = 'char-sprite';
      el.dataset.charId = id;
      el.onerror = () => {
        // SVG not found → try png
        el.onerror = null;
        el.src = this.spriteUrl(id, expr).replace('.svg', '.png');
      };
      slot.appendChild(el);
    }

    el.src = this.spriteUrl(id, expr);
    slot.classList.remove('hidden');
    el.style.opacity = '0';
    el.style.transition = 'opacity 300ms ease';
    requestAnimationFrame(() => { el.style.opacity = '1'; });

    this.displayed[id] = { pos, expr, el };
    this._updateDim(id);
  }

  hide(id) {
    if (id === 'all') {
      Object.keys(this.displayed).forEach(k => this.hide(k));
      return;
    }
    const info = this.displayed[id];
    if (!info) return;
    const el = info.el;
    el.style.transition = 'opacity 300ms ease';
    el.style.opacity = '0';
    setTimeout(() => {
      el.remove();
      const slot = this.slots[info.pos];
      if (slot && !slot.querySelector('.char-sprite')) {
        slot.classList.add('hidden');
      }
    }, 320);
    delete this.displayed[id];
  }

  setExpr(id, expr) {
    const info = this.displayed[id];
    if (!info) return;
    info.expr = expr;
    info.el.src = this.spriteUrl(id, expr);
    this.displayed[id] = info;
  }

  move(id, newPos, duration = 400) {
    const info = this.displayed[id];
    if (!info) return;
    const oldSlot = this.slots[info.pos];
    const newSlot = this.slots[newPos];
    if (!newSlot || info.pos === newPos) return;

    const el = info.el;
    // Quick slide: fade out, swap slot, fade in
    el.style.transition = `opacity ${duration / 2}ms ease`;
    el.style.opacity = '0';
    setTimeout(() => {
      oldSlot?.classList.add('hidden');
      el.remove();
      newSlot.appendChild(el);
      newSlot.classList.remove('hidden');
      el.style.opacity = '0';
      requestAnimationFrame(() => {
        el.style.transition = `opacity ${duration / 2}ms ease`;
        el.style.opacity = '1';
      });
    }, duration / 2 + 20);

    info.pos = newPos;
    this.displayed[id] = info;
  }

  /** Dim all characters except the one speaking. */
  highlight(speakerId) {
    for (const [id, info] of Object.entries(this.displayed)) {
      const slot = this.slots[info.pos];
      if (!slot) continue;
      if (id === speakerId) {
        slot.classList.remove('dimmed');
      } else {
        slot.classList.add('dimmed');
      }
    }
  }

  clearHighlight() {
    Object.values(this.slots).forEach(s => s?.classList.remove('dimmed'));
  }

  _removeFrom(id) {
    const info = this.displayed[id];
    if (!info) return;
    info.el.remove();
    delete this.displayed[id];
  }

  _updateDim(activeId) {
    const count = Object.keys(this.displayed).length;
    if (count > 1) this.highlight(activeId);
    else this.clearHighlight();
  }
}
