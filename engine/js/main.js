/**
 * main.js — entry point.
 * Wires up the main menu and bootstraps VNEngine.
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

let engine = null;
let menuUI = null;

async function startGame() {
  mainMenu.classList.remove('active');
  gameScreen.classList.add('active');

  engine = new VNEngine(root, '../assets');
  menuUI = new MenuUI(root, engine);

  try {
    await engine.loadStory(STORY_CONFIG);
    await engine.start(0);
  } catch (err) {
    console.error('Failed to load story:', err);
    showError(err.message);
  }
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
