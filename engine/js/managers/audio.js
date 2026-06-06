/**
 * AudioManager — BGM + SFX via Web Audio API.
 * Gracefully degrades when audio files are absent.
 */
export class AudioManager {
  constructor(assetBase) {
    this.assetBase = assetBase;
    this.ctx       = null;
    this.bgmNode   = null;
    this.bgmGain   = null;
    this.sfxNodes  = {};   // id → { source, gain }
    this._ready    = false;
    this._bgmVol   = 0.6;
    this._sfxVol   = 0.8;
    this._initCtx();
  }

  _initCtx() {
    try {
      this.ctx    = new (window.AudioContext || window.webkitAudioContext)();
      this.bgmGain = this.ctx.createGain();
      this.bgmGain.gain.value = this._bgmVol;
      this.bgmGain.connect(this.ctx.destination);
      this._ready = true;
    } catch { /* audio unavailable */ }
  }

  _resume() {
    if (this.ctx?.state === 'suspended') this.ctx.resume();
  }

  async _loadBuffer(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`audio fetch failed: ${url}`);
    const arrayBuf = await res.arrayBuffer();
    return this.ctx.decodeAudioData(arrayBuf);
  }

  async bgm(id, fadeMs = 0) {
    if (!this._ready || !id) return;
    this._resume();
    try {
      const url = `${this.assetBase}/audio/bgm/${id}.ogg`;
      const buf = await this._loadBuffer(url);
      await this.bgmStop(Math.min(fadeMs, 800));
      const src  = this.ctx.createBufferSource();
      src.buffer = buf;
      src.loop   = true;
      const gain = this.ctx.createGain();
      gain.gain.value = fadeMs > 0 ? 0 : this._bgmVol;
      src.connect(gain);
      gain.connect(this.ctx.destination);
      src.start();
      this.bgmNode = src;
      this.bgmGain = gain;
      if (fadeMs > 0) {
        gain.gain.linearRampToValueAtTime(this._bgmVol, this.ctx.currentTime + fadeMs / 1000);
      }
    } catch { /* missing audio file — silent */ }
  }

  async bgmStop(fadeMs = 0) {
    if (!this.bgmNode) return;
    const node = this.bgmNode;
    const gain = this.bgmGain;
    this.bgmNode = null;
    if (fadeMs > 0 && gain) {
      gain.gain.linearRampToValueAtTime(0, this.ctx.currentTime + fadeMs / 1000);
      setTimeout(() => { try { node.stop(); } catch {} }, fadeMs + 100);
    } else {
      try { node.stop(); } catch {}
    }
  }

  bgmVol(value) {
    this._bgmVol = value;
    if (this.bgmGain) this.bgmGain.gain.value = value;
  }

  async sfx(id, { volume = 1, loop = false, delay = 0 } = {}) {
    if (!this._ready || !id) return;
    this._resume();
    try {
      const url = `${this.assetBase}/audio/sfx/${id}.ogg`;
      const buf = await this._loadBuffer(url);
      const src  = this.ctx.createBufferSource();
      src.buffer = buf;
      src.loop   = loop;
      const gain = this.ctx.createGain();
      gain.gain.value = volume * this._sfxVol;
      src.connect(gain);
      gain.connect(this.ctx.destination);
      src.start(this.ctx.currentTime + delay / 1000);
      if (!loop) {
        src.onended = () => { delete this.sfxNodes[id]; };
      }
      this.sfxNodes[id] = { source: src, gain };
    } catch { /* missing sfx file */ }
  }

  sfxStop(id, fadeMs = 0) {
    const node = this.sfxNodes[id];
    if (!node) return;
    delete this.sfxNodes[id];
    if (fadeMs > 0) {
      node.gain.gain.linearRampToValueAtTime(0, this.ctx.currentTime + fadeMs / 1000);
      setTimeout(() => { try { node.source.stop(); } catch {} }, fadeMs + 100);
    } else {
      try { node.source.stop(); } catch {}
    }
  }

  stopAll() {
    this.bgmStop(300);
    for (const id of Object.keys(this.sfxNodes)) this.sfxStop(id, 200);
  }
}
