/**
 * main.js — entry point.
 * Wires up the main menu and bootstraps VNEngine.
 *
 * Dev-jump URL params (for Dashboard integration):
 *   ?devScene=<bg_id>    — start at first @scene bg=<bg_id>
 *   ?devChapter=<N>      — start at chapter N (0-indexed)
 */
import { VNEngine } from './core/engine.js';
import { MenuUI }   from './ui/menu.js';

const STORY_CONFIG = {
  title: '暗渠之書',
  chapters: [
    '../scripts/taichung-anqu/chapter1.vns',
    '../scripts/taichung-anqu/chapter2.vns',
    '../scripts/taichung-anqu/chapter3.vns',
  ],
  // character display names
  characters: {
    narrator:   { name: '（旁白）' },
    diao_caidi: { name: '刁才弟' },
  },
};

const root        = document.getElementById('vn-root');
const mainMenu    = document.getElementById('main-menu');
const gameScreen  = document.getElementById('game-screen');

// ── Dev-jump params ──────────────────────────────────────────────
const _devParams  = new URLSearchParams(location.search);
const DEV_SCENE   = _devParams.get('devScene');    // e.g. ?devScene=shrine_interior
const DEV_CHAPTER = _devParams.get('devChapter');  // e.g. ?devChapter=1

let engine = null;
let menuUI = null;

function _devStartIndex(eng) {
  if (DEV_SCENE) {
    // Find first @scene command with matching bg id
    const idx = eng.allCommands.findIndex(
      c => c.type === 'scene' && c.bg === DEV_SCENE
    );
    if (idx >= 0) return idx;
    console.warn(`[Dev] Scene "${DEV_SCENE}" not found — starting from 0`);
  }
  if (DEV_CHAPTER !== null) {
    const chNum = parseInt(DEV_CHAPTER, 10);
    // Find the first command that belongs to chapter chNum
    const cmds = eng.allCommands;
    let charCount = 0;
    for (let i = 0; i < cmds.length; i++) {
      if (cmds[i]._chapterIdx === chNum) return i;
    }
    console.warn(`[Dev] Chapter ${chNum} not found — starting from 0`);
  }
  return 0;
}

async function startGame() {
  mainMenu.classList.remove('active');
  gameScreen.classList.add('active');

  engine = new VNEngine(root, '../assets');
  menuUI = new MenuUI(root, engine);

  try {
    await engine.loadStory(STORY_CONFIG);
    const startIdx = _devStartIndex(engine);

    if ((DEV_SCENE || DEV_CHAPTER !== null) && startIdx > 0) {
      _showDevBanner(DEV_SCENE ? `Scene: ${DEV_SCENE}` : `Chapter: ${DEV_CHAPTER}`);
    }

    await engine.start(startIdx);
  } catch (err) {
    console.error('Failed to load story:', err);
    showError(err.message);
  }
}

function _showDevBanner(label) {
  const banner = document.createElement('div');
  banner.style.cssText = [
    'position:absolute', 'top:0', 'left:0', 'right:0',
    'background:rgba(192,120,32,.85)', 'color:#000',
    'font-family:monospace', 'font-size:10px', 'text-align:center',
    'padding:2px 8px', 'z-index:9999', 'pointer-events:none',
    'letter-spacing:.05em',
  ].join(';');
  banner.textContent = `⌘ DEV JUMP → ${label}`;
  root.appendChild(banner);
  setTimeout(() => banner.remove(), 4000);
}

function showError(msg) {
  const el = document.createElement('div');
  el.style.cssText = `
    position:absolute; inset:0; display:flex; flex-direction:column;
    align-items:center; justify-content:center; background:#080810;
    color:#e8dcc8; font-family:monospace; gap:1rem; padding:2rem; z-index:999;
  `;
  el.innerHTML = `
    <p style="color:#c17a24; font-size:1.2rem;">⚠ 無法載入故事</p>
    <p style="color:#9e9280; font-size:0.85rem;">${msg}</p>
    <p style="color:#9e9280; font-size:0.8rem;">請確認已透過 HTTP Server 開啟（執行 python serve.py）</p>
  `;
  root.appendChild(el);
}

/* ── Main Menu Wiring ── */
document.querySelectorAll('.menu-btn[data-action]').forEach(btn => {
  btn.addEventListener('click', () => {
    const action = btn.dataset.action;
    if (action === 'start') startGame();
    if (action === 'load') {
      // TODO: show load menu without starting fresh
    }
  });
});

/* ── Keyboard shortcut: Enter on main menu ── */
document.addEventListener('keydown', e => {
  if (e.code === 'Enter' && mainMenu.classList.contains('active')) startGame();
});
