/**
 * SceneManager — background transitions.
 */
export class SceneManager {
  constructor(root, assetBase) {
    this.root      = root;
    this.assetBase = assetBase;
    this.bgA       = root.querySelector('#bg-a');
    this.bgB       = root.querySelector('#bg-b');
    this.active    = 'a';
    this.current   = null;
  }

  _bgUrlResolved(id) {
    const png = `${this.assetBase}/backgrounds/${id}.png`;
    const svg = `${this.assetBase}/backgrounds/${id}.svg`;
    return new Promise(resolve => {
      const img = new Image();
      img.onload  = () => resolve(png);
      img.onerror = () => resolve(svg);
      img.src = png;
    });
  }

  async set(id, transition = 'fade') {
    if (!id || id === this.current) return;
    this.current = id;

    const url  = await this._bgUrlResolved(id);
    const next = this.active === 'a' ? this.bgB : this.bgA;
    const curr = this.active === 'a' ? this.bgA : this.bgB;

    // Load new bg into the "next" layer (hidden)
    next.style.backgroundImage = `url("${url}")`;
    next.style.opacity = '0';

    switch (transition) {
      case 'none':
        curr.style.opacity = '0';
        next.style.opacity = '1';
        break;

      case 'fade':
      default:
        await this._animateOpacity(next, 0, 1, 600);
        await this._animateOpacity(curr, 1, 0, 300);
        break;

      case 'dissolve':
        await Promise.all([
          this._animateOpacity(next, 0, 1, 700),
          this._animateOpacity(curr, 1, 0, 700),
        ]);
        break;

      case 'wipe':
        next.style.clipPath = 'inset(0 100% 0 0)';
        next.style.opacity  = '1';
        await this._animate(next, {
          from: { clipPath: 'inset(0 100% 0 0)' },
          to:   { clipPath: 'inset(0 0% 0 0)' },
          duration: 700,
        });
        curr.style.opacity = '0';
        break;
    }

    this.active = this.active === 'a' ? 'b' : 'a';
  }

  _animateOpacity(el, from, to, duration) {
    return new Promise(resolve => {
      el.style.transition = `opacity ${duration}ms ease`;
      el.style.opacity    = String(to);
      setTimeout(resolve, duration + 50);
    });
  }

  _animate(el, { from, to, duration }) {
    return new Promise(resolve => {
      Object.assign(el.style, { transition: `all ${duration}ms ease`, ...to });
      setTimeout(resolve, duration + 50);
    });
  }
}
