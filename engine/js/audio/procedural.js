/**
 * ProceduralAudio — Web Audio API 程序式音效生成器（暗渠之書）
 * 在 .ogg 素材缺失時自動接管，無需任何音訊檔案。
 */
export class ProceduralAudio {
  constructor(ctx) {
    this.ctx = ctx;
  }

  // ── Noise buffer helpers ────────────────────────────────────────

  _makeWhiteBuffer(sec = 3) {
    const len = Math.floor(this.ctx.sampleRate * sec);
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  }

  _makePinkBuffer(sec = 3) {
    const len = Math.floor(this.ctx.sampleRate * sec);
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    let b0=0, b1=0, b2=0, b3=0, b4=0, b5=0, b6=0;
    for (let i = 0; i < len; i++) {
      const w = Math.random() * 2 - 1;
      b0 = 0.99886*b0 + w*0.0555179;
      b1 = 0.99332*b1 + w*0.0750759;
      b2 = 0.96900*b2 + w*0.1538520;
      b3 = 0.86650*b3 + w*0.3104856;
      b4 = 0.55000*b4 + w*0.5329522;
      b5 = -0.7616*b5  - w*0.0168980;
      d[i] = (b0+b1+b2+b3+b4+b5+b6 + w*0.5362) * 0.11;
      b6 = w * 0.115926;
    }
    return buf;
  }

  _loopSource(buf) {
    const s = this.ctx.createBufferSource();
    s.buffer = buf;
    s.loop = true;
    return s;
  }

  _bpf(freq, Q = 1) {
    const f = this.ctx.createBiquadFilter();
    f.type = 'bandpass';
    f.frequency.value = freq;
    f.Q.value = Q;
    return f;
  }

  _lpf(freq) {
    const f = this.ctx.createBiquadFilter();
    f.type = 'lowpass';
    f.frequency.value = freq;
    return f;
  }

  _hpf(freq) {
    const f = this.ctx.createBiquadFilter();
    f.type = 'highpass';
    f.frequency.value = freq;
    return f;
  }

  _gain(val) {
    const g = this.ctx.createGain();
    g.gain.value = val;
    return g;
  }

  _lfo(freq, amount, target) {
    const osc = this.ctx.createOscillator();
    osc.frequency.value = freq;
    const g = this._gain(amount);
    osc.connect(g);
    g.connect(target);
    osc.start();
    return osc;
  }

  // ── BGM generators — return { gain, sources[] } ─────────────────

  /** 台中舊城區夜晚環境音：微雨 + 城市底噪 + 遠方機車聲 */
  createCityAmbient(dest) {
    const ctx = this.ctx;
    const out = this._gain(1.0);
    out.connect(dest);
    const sources = [];

    // 60 Hz 電力線低鳴
    [60, 120, 180].forEach((f, i) => {
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.value = f;
      const g = this._gain(0.038 / (i + 1));
      osc.connect(g); g.connect(out);
      osc.start();
      sources.push(osc);
    });

    // 遠方交通：粉紅噪聲過低通濾波
    const pBuf = this._makePinkBuffer(5);
    const traffic = this._loopSource(pBuf);
    const tBpf = this._bpf(170, 0.4);
    const tGain = this._gain(0.10);
    traffic.connect(tBpf); tBpf.connect(tGain); tGain.connect(out);
    traffic.start();
    sources.push(traffic);

    // 細雨聲：白噪聲過帶通
    const wBuf = this._makeWhiteBuffer(4);
    const rain = this._loopSource(wBuf);
    const rBpf = this._bpf(2200, 0.55);
    const rHpf = this._hpf(900);
    const rGain = this._gain(0.07);
    rain.connect(rBpf); rBpf.connect(rHpf); rHpf.connect(rGain); rGain.connect(out);
    rain.start();
    sources.push(rain);

    // 微雨振幅 LFO（呼吸感）
    sources.push(this._lfo(0.08, 0.025, rGain.gain));

    // 空氣暗噪
    const air = this._loopSource(pBuf);
    const airLpf = this._lpf(300);
    const airGain = this._gain(0.05);
    air.connect(airLpf); airLpf.connect(airGain); airGain.connect(out);
    air.start();
    sources.push(air);

    return { gain: out, sources };
  }

  /** 道壇靜謐氛圍音：低鳴 + 泛音 + 香爐空氣 */
  createShrineAmbient(dest) {
    const ctx = this.ctx;
    const out = this._gain(1.0);
    out.connect(dest);
    const sources = [];

    const fundamental = 55; // A1
    [1, 2, 3, 4, 6].forEach((h, i) => {
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.value = fundamental * h;
      const g = this._gain(0.055 / (i * 0.7 + 1));
      // 細微顫音 LFO
      const lfoFreq = 0.10 + i * 0.028;
      const lfo = ctx.createOscillator();
      lfo.frequency.value = lfoFreq;
      const lfoG = this._gain(fundamental * h * 0.003);
      lfo.connect(lfoG); lfoG.connect(osc.frequency);
      osc.connect(g); g.connect(out);
      osc.start(); lfo.start();
      sources.push(osc, lfo);
    });

    // 房間低嗡聲
    const pBuf = this._makePinkBuffer(6);
    const hum = this._loopSource(pBuf);
    const humLpf = this._lpf(180);
    const humGain = this._gain(0.06);
    hum.connect(humLpf); humLpf.connect(humGain); humGain.connect(out);
    hum.start();
    sources.push(hum);

    // 香煙氣流（極細膩）
    const wBuf = this._makeWhiteBuffer(4);
    const inc = this._loopSource(wBuf);
    const incBpf = this._bpf(750, 2.5);
    const incGain = this._gain(0.015);
    inc.connect(incBpf); incBpf.connect(incGain); incGain.connect(out);
    inc.start();
    sources.push(inc);

    return { gain: out, sources };
  }

  /** 暴雨夜間氛圍音：大雨 + 雷聲底噪 + 強風 */
  createRainNight(dest) {
    const ctx = this.ctx;
    const out = this._gain(1.0);
    out.connect(dest);
    const sources = [];

    const wBuf = this._makeWhiteBuffer(5);
    const pBuf = this._makePinkBuffer(5);

    // 中頻雨聲主體
    const r1 = this._loopSource(wBuf);
    const bpf1 = this._bpf(1800, 0.5);
    const g1 = this._gain(0.22);
    r1.connect(bpf1); bpf1.connect(g1); g1.connect(out);
    r1.start();
    sources.push(r1);

    // 高頻雨點打擊感
    const r2 = this._loopSource(wBuf);
    const bpf2 = this._bpf(4500, 0.8);
    const g2 = this._gain(0.13);
    r2.connect(bpf2); bpf2.connect(g2); g2.connect(out);
    r2.start();
    sources.push(r2);

    // 低頻鐵皮屋頂共鳴
    const r3 = this._loopSource(pBuf);
    const bpf3 = this._bpf(430, 0.35);
    const g3 = this._gain(0.18);
    r3.connect(bpf3); bpf3.connect(g3); g3.connect(out);
    r3.start();
    sources.push(r3);

    // 遠雷底噪（極低頻，慢速振幅調製）
    const r4 = this._loopSource(pBuf);
    const lpf4 = this._lpf(75);
    const g4 = this._gain(0.10);
    sources.push(this._lfo(0.045, 0.07, g4.gain));
    r4.connect(lpf4); lpf4.connect(g4); g4.connect(out);
    r4.start();
    sources.push(r4);

    // 風嚎：窄帶通 + 頻率 LFO
    const r5 = this._loopSource(wBuf);
    const bpf5 = this._bpf(310, 3.5);
    const windLfoG = this._gain(42);
    const windLfo = ctx.createOscillator();
    windLfo.frequency.value = 0.22;
    windLfo.connect(windLfoG); windLfoG.connect(bpf5.frequency);
    windLfo.start();
    const g5 = this._gain(0.08);
    r5.connect(bpf5); bpf5.connect(g5); g5.connect(out);
    r5.start();
    sources.push(r5, windLfo);

    return { gain: out, sources };
  }

  // ── SFX generators (one-shot or looping) ─────────────────────────

  /**
   * 播放程序式 SFX。
   * @param {string} id — SFX 識別名
   * @param {AudioNode} dest — 連接至 destination
   * @param {number} volume
   * @returns {{ gain: GainNode, sources: AudioNode[] } | null}
   */
  playSfx(id, dest, volume = 1.0) {
    const out = this._gain(volume);
    out.connect(dest);
    const sources = [];

    switch (id) {
      case 'market_closing':   this._sfxMarket(out, sources);   break;
      case 'footsteps_puddle': this._sfxPuddle(out, sources);   break;
      case 'paper_rustle':     this._sfxPaper(out, sources);    break;
      case 'oar_creak':        this._sfxOar(out, sources);      break;
      case 'water_distant':    this._sfxWater(out, sources);    break;
      case 'rain_heavy':       this._sfxRainHeavy(out, sources); break;
      case 'power_failure':    this._sfxPowerFail(out, sources); break;
      default: out.disconnect(); return null;
    }

    return { gain: out, sources };
  }

  _sfxMarket(dest, srcs) {
    const ctx = this.ctx;
    const now = ctx.currentTime;
    const wBuf = this._makeWhiteBuffer(0.3);

    [0, 0.09, 0.20, 0.33, 0.48, 0.65, 0.84].forEach((t, i) => {
      const osc = ctx.createOscillator();
      osc.type = 'sawtooth';
      osc.frequency.value = 370 + i * 48;
      const g = this._gain(0);
      g.gain.setValueAtTime(0.11 - i * 0.01, now + t);
      g.gain.exponentialRampToValueAtTime(0.001, now + t + 0.20);
      const hpf = this._hpf(240);
      osc.connect(hpf); hpf.connect(g); g.connect(dest);
      osc.start(now + t); osc.stop(now + t + 0.25);
      srcs.push(osc);
    });

    [0.02, 0.14, 0.28, 0.46].forEach(t => {
      const s = ctx.createBufferSource();
      s.buffer = wBuf;
      const g = this._gain(0);
      g.gain.setValueAtTime(0.20, now + t);
      g.gain.exponentialRampToValueAtTime(0.001, now + t + 0.09);
      const bpf = this._bpf(950 + 400 * Math.random(), 1.4);
      s.connect(bpf); bpf.connect(g); g.connect(dest);
      s.start(now + t); s.stop(now + t + 0.12);
      srcs.push(s);
    });
  }

  _sfxPuddle(dest, srcs) {
    const ctx = this.ctx;
    const now = ctx.currentTime;
    const wBuf = this._makeWhiteBuffer(0.4);

    const s1 = ctx.createBufferSource();
    s1.buffer = wBuf;
    const g1 = this._gain(0);
    g1.gain.setValueAtTime(0, now);
    g1.gain.linearRampToValueAtTime(0.38, now + 0.005);
    g1.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
    const bpf1 = this._bpf(580, 0.8);
    s1.connect(bpf1); bpf1.connect(g1); g1.connect(dest);
    s1.start(now); s1.stop(now + 0.22);
    srcs.push(s1);

    const s2 = ctx.createBufferSource();
    s2.buffer = wBuf;
    const g2 = this._gain(0);
    g2.gain.setValueAtTime(0, now + 0.06);
    g2.gain.linearRampToValueAtTime(0.14, now + 0.065);
    g2.gain.exponentialRampToValueAtTime(0.001, now + 0.23);
    const bpf2 = this._bpf(1200, 1.2);
    s2.connect(bpf2); bpf2.connect(g2); g2.connect(dest);
    s2.start(now + 0.06); s2.stop(now + 0.26);
    srcs.push(s2);
  }

  _sfxPaper(dest, srcs) {
    const ctx = this.ctx;
    const now = ctx.currentTime;
    const wBuf = this._makeWhiteBuffer(0.4);

    [0, 0.13, 0.25].forEach((t, i) => {
      const s = ctx.createBufferSource();
      s.buffer = wBuf;
      const g = this._gain(0);
      const peak = 0.22 - i * 0.04;
      g.gain.setValueAtTime(0, now + t);
      g.gain.linearRampToValueAtTime(peak, now + t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.001, now + t + 0.10);
      const hpf = this._hpf(3000);
      const bpf = this._bpf(5200 + i * 700, 0.7);
      s.connect(hpf); hpf.connect(bpf); bpf.connect(g); g.connect(dest);
      s.start(now + t); s.stop(now + t + 0.12);
      srcs.push(s);
    });
  }

  _sfxOar(dest, srcs) {
    const ctx = this.ctx;
    const now = ctx.currentTime;
    const wBuf = this._makeWhiteBuffer(0.3);

    [0, 1.9, 3.8].forEach(t => {
      const osc = ctx.createOscillator();
      osc.type = 'square';
      osc.frequency.value = 88 + Math.random() * 28;
      const g = this._gain(0);
      g.gain.setValueAtTime(0, now + t);
      g.gain.linearRampToValueAtTime(0.09, now + t + 0.04);
      g.gain.exponentialRampToValueAtTime(0.001, now + t + 0.58);
      const lpf = this._lpf(380);
      osc.connect(lpf); lpf.connect(g); g.connect(dest);
      osc.start(now + t); osc.stop(now + t + 0.62);
      srcs.push(osc);

      const drip = ctx.createBufferSource();
      drip.buffer = wBuf;
      const dg = this._gain(0);
      dg.gain.setValueAtTime(0, now + t + 0.06);
      dg.gain.linearRampToValueAtTime(0.06, now + t + 0.065);
      dg.gain.exponentialRampToValueAtTime(0.001, now + t + 0.32);
      const dbpf = this._bpf(820, 2.2);
      drip.connect(dbpf); dbpf.connect(dg); dg.connect(dest);
      drip.start(now + t + 0.06); drip.stop(now + t + 0.36);
      srcs.push(drip);
    });
  }

  _sfxWater(dest, srcs) {
    const ctx = this.ctx;
    const pBuf = this._makePinkBuffer(6);
    const water = this._loopSource(pBuf);
    const lpf = this._lpf(580);
    const delay = ctx.createDelay(0.5);
    delay.delayTime.value = 0.22;
    const fb = this._gain(0.52);
    const g = this._gain(0.15);
    water.connect(lpf);
    lpf.connect(delay); delay.connect(fb); fb.connect(delay);
    lpf.connect(g); delay.connect(g); g.connect(dest);
    water.start();
    srcs.push(water);
  }

  _sfxRainHeavy(dest, srcs) {
    const wBuf = this._makeWhiteBuffer(5);
    const pBuf = this._makePinkBuffer(5);

    [[wBuf, 2000, 0.38, 0.4], [pBuf, 480, 0.20, 0.3], [wBuf, 5500, 0.10, 0.7]].forEach(
      ([buf, freq, vol, Q]) => {
        const s = this._loopSource(buf);
        const bpf = this._bpf(freq, Q);
        const g = this._gain(vol);
        s.connect(bpf); bpf.connect(g); g.connect(dest);
        s.start();
        srcs.push(s);
      }
    );
  }

  _sfxPowerFail(dest, srcs) {
    const ctx = this.ctx;
    const now = ctx.currentTime;

    [60, 120, 180, 240].forEach((f, i) => {
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.value = f;
      const g = this._gain(0);
      g.gain.setValueAtTime(0.12 / (i + 1), now);
      g.gain.setValueAtTime(0.12 / (i + 1), now + 0.38);
      g.gain.linearRampToValueAtTime(0.0, now + 0.42);
      osc.connect(g); g.connect(dest);
      osc.start(now); osc.stop(now + 0.45);
      srcs.push(osc);
    });

    const wBuf = this._makeWhiteBuffer(0.15);
    const click = ctx.createBufferSource();
    click.buffer = wBuf;
    const cg = this._gain(0);
    cg.gain.setValueAtTime(0.38, now + 0.40);
    cg.gain.exponentialRampToValueAtTime(0.001, now + 0.50);
    const lpf = this._lpf(140);
    click.connect(lpf); lpf.connect(cg); cg.connect(dest);
    click.start(now + 0.40); click.stop(now + 0.52);
    srcs.push(click);
  }
}
