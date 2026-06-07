/**
 * settings.js — 遊戲設定（文字速度 / 自動延遲 / 音量 / 全螢幕）。
 * localStorage 持久化；主選單與 HUD 共用同一個 overlay。
 */
const KEY = 'vn_settings';

export const DEFAULTS = {
  textSpeed: 28,   // ms/字（越小越快）
  autoDelay: 2200, // 自動模式每句停留 ms
  bgmVol:    0.6,
  sfxVol:    0.8,
};

export function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveSettings(s) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* ignore */ }
}

export function openSettings(root) {
  root.querySelector('#overlay-settings')?.classList.remove('hidden');
}

/**
 * 綁定設定 overlay。getEngine() 回傳目前 engine（可為 null —— 主選單
 * 階段也能調整，待 engine 建立時再套用 loadSettings()）。
 */
export function initSettingsUI(root, getEngine) {
  const overlay = root.querySelector('#overlay-settings');
  if (!overlay || overlay.dataset.bound) return;
  overlay.dataset.bound = '1';

  const s = loadSettings();

  const fields = [
    { id: 'set-textspeed', key: 'textSpeed', fmt: v => `${v}ms/字` },
    { id: 'set-autodelay', key: 'autoDelay', fmt: v => `${(v / 1000).toFixed(1)}s` },
    { id: 'set-bgmvol',    key: 'bgmVol',    fmt: v => `${Math.round(v * 100)}%` },
    { id: 'set-sfxvol',    key: 'sfxVol',    fmt: v => `${Math.round(v * 100)}%` },
  ];

  for (const f of fields) {
    const input = overlay.querySelector(`#${f.id}`);
    const label = overlay.querySelector(`#${f.id}-v`);
    if (!input) continue;
    input.value = s[f.key];
    if (label) label.textContent = f.fmt(s[f.key]);
    input.addEventListener('input', () => {
      const v = parseFloat(input.value);
      s[f.key] = v;
      if (label) label.textContent = f.fmt(v);
      saveSettings(s);
      getEngine()?.applySettings(s);
    });
  }

  overlay.querySelector('#set-fullscreen')?.addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen?.();
  });

  overlay.querySelector('#settings-close')?.addEventListener('click', () => {
    overlay.classList.add('hidden');
  });
}
