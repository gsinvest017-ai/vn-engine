/**
 * EffectsManager — visual effects: rain, shake, dim, flash, fade, flicker, vignette.
 */
export class EffectsManager {
  constructor(root) {
    this.root    = root;
    this.fxDim   = root.querySelector('#fx-dim');
    this.fxFlash = root.querySelector('#fx-flash');
    this.fxFade  = root.querySelector('#fx-fade');
    this.fxVig   = root.querySelector('#fx-vignette');
    this.canvas  = root.querySelector('#weather-canvas');
    this._rain   = null;

    this._resizeCanvas();
    window.addEventListener('resize', () => this._resizeCanvas());
  }

  /* ── Dim ── */
  dim(level = 0.4) {
    this.fxDim.style.opacity = String(Math.max(0, Math.min(1, level)));
  }

  /* ── Vignette ── */
  vignette(intensity = 0.6) {
    this.fxVig.style.opacity = String(intensity);
  }

  /* ── Flash ── */
  flash(color = 'white', duration = 200) {
    return new Promise(resolve => {
      this.fxFlash.style.background = color;
      this.fxFlash.style.transition = 'none';
      this.fxFlash.style.opacity = '0.9';
      setTimeout(() => {
        this.fxFlash.style.transition = `opacity ${duration}ms ease`;
        this.fxFlash.style.opacity = '0';
        setTimeout(resolve, duration + 50);
      }, 50);
    });
  }

  /* ── Fade ── */
  fade(direction = 'out', color = 'black', duration = 800) {
    return new Promise(resolve => {
      this.fxFade.style.background = color;
      this.fxFade.style.transition = `opacity ${duration}ms ease`;
      this.fxFade.style.opacity = direction === 'out' ? '1' : '0';
      setTimeout(resolve, duration + 60);
    });
  }

  /* ── Shake ── */
  shake(intensity = 0.5, duration = 500) {
    return new Promise(resolve => {
      const cls = intensity > 0.7 ? 'shaking-lg' : intensity > 0.4 ? 'shaking-md' : 'shaking-sm';
      const gameScreen = this.root.querySelector('#game-screen');
      gameScreen.style.animationDuration = `${duration}ms`;
      gameScreen.classList.add(cls);
      setTimeout(() => {
        gameScreen.classList.remove(cls);
        gameScreen.style.animationDuration = '';
        resolve();
      }, duration + 50);
    });
  }

  /* ── Flicker ── */
  async flicker(count = 3) {
    for (let i = 0; i < count; i++) {
      await this.flash('rgba(255,255,240,0.15)', 80);
      await this._sleep(60 + Math.random() * 80);
      await this.flash('rgba(0,0,0,0.3)', 60);
      await this._sleep(40 + Math.random() * 60);
    }
  }

  /* ── Weather ── */
  setWeather(cmd) {
    this._stopRain();
    const rain = cmd.rain || 'none';
    if (rain !== 'none') {
      const intensity = { drizzle: 0.2, light: 0.45, heavy: 0.75, storm: 1.0 }[rain] ?? 0.5;
      this._startRain(intensity, cmd.wind || 0);
    }
  }

  _startRain(intensity, wind = 0) {
    const ctx    = this.canvas.getContext('2d');
    const w      = this.canvas.width;
    const h      = this.canvas.height;
    const count  = Math.floor(w * h * intensity * 0.0004);
    const drops  = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      len: 8 + Math.random() * 20 * intensity,
      speed: 8 + Math.random() * 14 * intensity,
      alpha: 0.2 + Math.random() * 0.5 * intensity,
    }));
    const angle = (wind * 25) * Math.PI / 180;
    const dx    = Math.sin(angle);
    const dy    = Math.cos(angle);

    let raf;
    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = `rgba(180,200,220,1)`;
      ctx.lineWidth   = 0.5 + intensity * 0.6;
      for (const d of drops) {
        ctx.globalAlpha = d.alpha;
        ctx.beginPath();
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x + dx * d.len, d.y + dy * d.len);
        ctx.stroke();
        d.x += d.speed * dx;
        d.y += d.speed * dy;
        if (d.y > h || d.x < 0 || d.x > w) {
          d.x = Math.random() * w;
          d.y = -d.len;
        }
      }
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(draw);
    };
    draw();
    this._rain = { raf, ctx };
  }

  _stopRain() {
    if (this._rain) {
      cancelAnimationFrame(this._rain.raf);
      this._rain.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      this._rain = null;
    }
  }

  /* ── Suspense End — cinematic closing sequence ── */
  async suspenseEnd({ message = '', duration = 5200 } = {}) {
    // Phase 1: Vignette intensifies with pulse animation
    this.fxVig.classList.add('vignette-suspense');
    this.fxVig.style.opacity = '0.65';
    await this._sleep(700);

    // Phase 2: Textbox fades out
    const textbox = this.root.querySelector('#textbox');
    if (textbox) {
      textbox.classList.add('fading-out');
    }
    this.dim(0.22);
    await this._sleep(900);

    // Phase 3: Optional closing message
    if (message) {
      const msgEl = this.root.querySelector('#fx-suspense-msg');
      if (msgEl) {
        msgEl.querySelector('span').textContent = message;
        msgEl.classList.add('show');
        await this._sleep(1800);
        msgEl.classList.remove('show');
        await this._sleep(600);
      }
    }

    // Phase 4: Characters drift out
    const charLayer = this.root.querySelector('#characters-layer');
    if (charLayer) {
      charLayer.style.transition = 'opacity 1600ms ease-in, transform 1800ms ease-in';
      charLayer.style.opacity    = '0';
      charLayer.style.transform  = 'translateY(12px)';
    }
    this.fxVig.style.transition = 'opacity 2000ms ease-in';
    this.fxVig.style.opacity    = '1.0';
    await this._sleep(1000);

    // Phase 5: Slow blackout
    const fadeDuration = Math.max(2000, Math.floor(duration * 0.55));
    this.fxFade.style.background  = '#000';
    this.fxFade.style.transition  = `opacity ${fadeDuration}ms ease-in`;
    this.fxFade.style.opacity     = '1';
    await this._sleep(fadeDuration + 120);

    // Restore char layer transform for potential replay
    if (charLayer) {
      charLayer.style.transition = '';
      charLayer.style.transform  = '';
    }
  }

  /* ── Cleanup ── */
  clearAll() {
    this.dim(0);
    this.vignette(0);
    this.fxFlash.style.opacity = '0';
    this.fxFade.style.opacity  = '0';
    this.fxVig.classList.remove('vignette-suspense');
    const charLayer = this.root.querySelector('#characters-layer');
    if (charLayer) { charLayer.style.opacity = ''; charLayer.style.transform = ''; }
    const msgEl = this.root.querySelector('#fx-suspense-msg');
    if (msgEl) msgEl.classList.remove('show');
    const textbox = this.root.querySelector('#textbox');
    if (textbox) textbox.classList.remove('fading-out');
    this._stopRain();
  }

  /* ── Utility ── */
  _resizeCanvas() {
    this.canvas.width  = this.root.offsetWidth  || window.innerWidth;
    this.canvas.height = this.root.offsetHeight || window.innerHeight;
  }

  _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
}
