/**
 * GameState — save/load via localStorage.
 */
export class GameState {
  constructor() {
    this.chapter   = 0;
    this.cmdIndex  = 0;
    this.variables = {};
    this.history   = [];  // [{speaker, text}]
  }

  /** Serialize snapshot to plain object. */
  snapshot() {
    return {
      chapter:   this.chapter,
      cmdIndex:  this.cmdIndex,
      variables: { ...this.variables },
    };
  }

  save(slot = 0, meta = {}) {
    const data = {
      snap: this.snapshot(),
      history: this.history.slice(-200),   // 對話記錄一併存檔
      meta: { ...meta, savedAt: Date.now() },
    };
    try {
      localStorage.setItem(`vn_save_${slot}`, JSON.stringify(data));
      return true;
    } catch { return false; }
  }

  load(slot = 0) {
    try {
      const raw = localStorage.getItem(`vn_save_${slot}`);
      if (!raw) return null;
      const { snap, history, meta } = JSON.parse(raw);
      this.chapter   = snap.chapter ?? 0;
      this.cmdIndex  = snap.cmdIndex ?? 0;
      this.variables = snap.variables ?? {};
      this.history   = Array.isArray(history) ? history : [];
      return meta;
    } catch { return null; }
  }

  static listSlots() {
    const slots = [];
    for (let i = 0; i < 9; i++) {
      const raw = localStorage.getItem(`vn_save_${i}`);
      if (raw) {
        try { slots.push({ slot: i, ...JSON.parse(raw).meta }); }
        catch { slots.push({ slot: i }); }
      } else {
        slots.push({ slot: i, empty: true });
      }
    }
    return slots;
  }

  addHistory(entry) {
    this.history.push(entry);
    if (this.history.length > 200) this.history.shift();
  }

  setVar(key, value) { this.variables[key] = value; }
  getVar(key, def = null) { return this.variables[key] ?? def; }
}
