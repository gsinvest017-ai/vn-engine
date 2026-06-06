/**
 * AudioManager — BGM + SFX via Web Audio API.
 * 優先載入 .ogg 音訊檔；檔案缺失時自動切換至 ProceduralAudio 程序式生成。
 */
import { ProceduralAudio } from '../audio/procedural.js';

export class AudioManager {
  constructor(assetBase) {
    this.assetBase  = assetBase;
    this.ctx        = null;
    this.bgmNode    = null;  // file-based BGM BufferSource
    this.bgmGain    = null;  // file-based BGM GainNode
    this.sfxNodes   = {};    // id → { source, gain }  (file-based)
    this._procBgm   = null;  // { gain, sources[] }  (procedural BGM)
    this._procSfx   = {};    // id → { gain, sources[] }  (procedural SFX)
    this._ready     = false;
    this._bgmVol    = 0.6;
    this._sfxVol    = 0.8;
    this._proc      = null;
    this._initCtx();
  }

  _initCtx() {
    try {
      this.ctx    = new (window.AudioContext || window.webkitAudioContext)();
      this.bgmGain = this.ctx.createGain();
      this.bgmGain.gain.value = this._bgmVol;
      this.bgmGain.connect(this.ctx.destination);
      this._proc  = new ProceduralAudio(this.ctx);
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

  // ── BGM ───────────────────────────────────────────────────────────

  async bgm(id, fadeMs = 0) {
    if (!this._ready || !id) return;
    this._resume();
    try {
      const url = `${this.assetBase}/audio/bgm/${id}.ogg`;
      const buf = await this._loadBuffer(url);
      // 成功讀取檔案：先停掉現有 BGM（含程序式）
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
    } catch {
      // 檔案缺失 → 程序式音效 fallback
      await this.bgmStop(Math.min(fadeMs, 600));
      const master = this.ctx.createGain();
      master.gain.value = fadeMs > 0 ? 0 : this._bgmVol;
      master.connect(this.ctx.destination);

      let data = null;
      switch (id) {
        case 'ambient_old_city':   data = this._proc.createCityAmbient(master);  break;
        case 'ambient_shrine':     data = this._proc.createShrineAmbient(master); break;
        case 'ambient_rain_night': data = this._proc.createRainNight(master);    break;
      }

      if (data) {
        this._procBgm = { gain: master, sources: data.sources };
        if (fadeMs > 0) {
          master.gain.linearRampToValueAtTime(
            this._bgmVol,
            this.ctx.currentTime + fadeMs / 1000
          );
        }
      } else {
        master.disconnect();
      }
    }
  }

  async bgmStop(fadeMs = 0) {
    // 停止檔案型 BGM
    if (this.bgmNode) {
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
    // 停止程序式 BGM
    if (this._procBgm) {
      const p = this._procBgm;
      this._procBgm = null;
      if (fadeMs > 0 && p.gain) {
        p.gain.gain.linearRampToValueAtTime(0, this.ctx.currentTime + fadeMs / 1000);
        setTimeout(() => this._stopProcData(p), fadeMs + 100);
      } else {
        this._stopProcData(p);
      }
    }
  }

  bgmVol(value) {
    this._bgmVol = value;
    if (this.bgmGain) this.bgmGain.gain.value = value;
    if (this._procBgm?.gain) this._procBgm.gain.gain.value = value;
  }

  // ── SFX ───────────────────────────────────────────────────────────

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
    } catch {
      // 檔案缺失 → 程序式 SFX fallback
      if (this._procSfx[id]) {
        this._stopProcData(this._procSfx[id]);
        delete this._procSfx[id];
      }
      const data = this._proc.playSfx(id, this.ctx.destination, volume * this._sfxVol);
      if (data) {
        if (loop) {
          this._procSfx[id] = data;
        } else {
          // 非循環：延遲清理（最長 15 秒）
          setTimeout(() => this._stopProcData(data), 15000);
        }
      }
    }
  }

  sfxStop(id, fadeMs = 0) {
    // 停止檔案型 SFX
    const node = this.sfxNodes[id];
    if (node) {
      delete this.sfxNodes[id];
      if (fadeMs > 0) {
        node.gain.gain.linearRampToValueAtTime(0, this.ctx.currentTime + fadeMs / 1000);
        setTimeout(() => { try { node.source.stop(); } catch {} }, fadeMs + 100);
      } else {
        try { node.source.stop(); } catch {}
      }
    }
    // 停止程序式 SFX
    const pNode = this._procSfx[id];
    if (pNode) {
      delete this._procSfx[id];
      if (fadeMs > 0 && pNode.gain) {
        pNode.gain.gain.linearRampToValueAtTime(0, this.ctx.currentTime + fadeMs / 1000);
        setTimeout(() => this._stopProcData(pNode), fadeMs + 100);
      } else {
        this._stopProcData(pNode);
      }
    }
  }

  stopAll() {
    this.bgmStop(300);
    for (const id of Object.keys(this.sfxNodes))  this.sfxStop(id, 200);
    for (const id of Object.keys(this._procSfx))  this.sfxStop(id, 200);
  }

  // ── Internal ─────────────────────────────────────────────────────

  _stopProcData(data) {
    if (!data) return;
    try { data.gain?.disconnect(); } catch {}
    (data.sources || []).forEach(s => {
      try { s.stop(); } catch {}
      try { s.disconnect(); } catch {}
    });
  }
}
