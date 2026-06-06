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
    const ctx = this.canvas.getContext('2d');
    const w   = this.canvas.width;
    const h   = this.canvas.height;

    // Rain angle: near-vertical + wind offset
    const windAngle = (wind * 22) * Math.PI / 180;
    const baseAngle = 83 * Math.PI / 180;   // nearly vertical
    const totalAngle = baseAngle + windAngle;
    const adx = Math.cos(totalAngle);       // small horizontal component
    const ady = Math.sin(totalAngle);       // dominant vertical

    // ── Layer 1: Heavy drops (main streaks) ─────────────────────────
    const dropCount = Math.floor(w * h * intensity * 0.00055);
    const drops = Array.from({ length: dropCount }, () => ({
      x:     Math.random() * w * 1.3 - w * 0.15,
      y:     Math.random() * h,
      len:   22 + Math.random() * 42 * intensity,
      speed: 14 + Math.random() * 22 * intensity,
      alpha: 0.18 + Math.random() * 0.55 * intensity,
      width: 0.35 + Math.random() * 0.85 * intensity,
      sway:  (Math.random() - 0.5) * 0.45,
    }));

    // ── Layer 2: Fine spray (smaller, slower, drifts) ───────────────
    const sprayCount = Math.floor(dropCount * 0.7);
    const spray = Array.from({ length: sprayCount }, () => ({
      x:     Math.random() * w,
      y:     Math.random() * h,
      len:   4 + Math.random() * 12 * intensity,
      speed: 5 + Math.random() * 9 * intensity,
      alpha: 0.06 + Math.random() * 0.16 * intensity,
      drift: (Math.random() - 0.5) * 1.4,
    }));

    // ── Layer 3: Mist / ambient haze (drawn once, fades) ────────────
    let mistAlpha = intensity * 0.04;
    let mistPhase = 0;

    let raf;
    const drawFrame = () => {
      ctx.clearRect(0, 0, w, h);

      // Atmospheric mist band (mid-height, oscillating)
      mistPhase += 0.008;
      const mistY = h * 0.45 + Math.sin(mistPhase) * h * 0.08;
      const grad  = ctx.createLinearGradient(0, mistY - h*0.15, 0, mistY + h*0.15);
      grad.addColorStop(0, 'rgba(160,175,190,0)');
      grad.addColorStop(0.5, `rgba(160,175,190,${mistAlpha * 0.9})`);
      grad.addColorStop(1, 'rgba(160,175,190,0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, mistY - h * 0.15, w, h * 0.3);

      // ── Spray layer ────────────────────────────────────────────────
      for (const d of spray) {
        ctx.globalAlpha = d.alpha;
        ctx.strokeStyle = 'rgba(195,210,225,1)';
        ctx.lineWidth   = 0.3;
        ctx.beginPath();
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x + adx * d.len * 0.5 + d.drift, d.y + ady * d.len);
        ctx.stroke();
        d.x += d.speed * adx * 0.6 + d.drift * 0.3;
        d.y += d.speed * ady * 0.7;
        if (d.y > h + d.len || d.x < -60 || d.x > w + 60) {
          d.x = Math.random() * w;
          d.y = -d.len - Math.random() * 80;
        }
      }

      // ── Main drops with motion trail ──────────────────────────────
      for (const d of drops) {
        // Trail: 3 progressively fading segments behind the drop
        for (let t = 2; t >= 0; t--) {
          const trailFade   = (3 - t) / 3;
          const trailOffset = t * d.speed * 0.10;
          ctx.globalAlpha = d.alpha * trailFade * (t === 0 ? 1 : 0.45);
          ctx.strokeStyle = t === 0
            ? 'rgba(210,228,245,1)'
            : 'rgba(180,205,228,1)';
          ctx.lineWidth   = d.width * (t === 0 ? 1 : 0.55);
          ctx.beginPath();
          const ox = d.x - adx * trailOffset;
          const oy = d.y - ady * trailOffset;
          ctx.moveTo(ox, oy);
          ctx.lineTo(ox + adx * d.len, oy + ady * d.len);
          ctx.stroke();
        }

        // Tiny impact splash at bottom of drop
        if (d.y > h - 60 && d.y < h + d.len) {
          const splashAlpha = Math.max(0, (1 - (d.y - (h - 60)) / 60)) * d.alpha * 0.55;
          ctx.globalAlpha = splashAlpha;
          ctx.strokeStyle = 'rgba(200,220,238,1)';
          ctx.lineWidth   = 0.5;
          const sx = d.x + adx * d.len;
          const sy = Math.min(h - 2, d.y + ady * d.len);
          for (let s = 0; s < 4; s++) {
            const sa = (s / 4) * Math.PI * 2;
            ctx.beginPath();
            ctx.moveTo(sx, sy);
            ctx.lineTo(sx + Math.cos(sa) * 4, sy - Math.abs(Math.sin(sa)) * 5);
            ctx.stroke();
          }
        }

        d.x += d.speed * adx + d.sway;
        d.y += d.speed * ady;
        if (d.y > h + d.len + 40 || d.x < -80 || d.x > w + 80) {
          d.x = Math.random() * w * 1.3 - w * 0.15;
          d.y = -d.len - Math.random() * 120;
        }
      }

      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(drawFrame);
    };
    drawFrame();
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
