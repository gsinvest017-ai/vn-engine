# VN Framework 建構進度

## 目標
建立一套完整的視覺小說遊戲製作框架，支援：
- 純文字劇情腳本（.vns 格式）填入
- 對應素材自動對位（角色/場景/特效/音效）
- 以《暗渠之書》（台中暗渠.md）為測試文本
- 瀏覽器直接執行，零安裝

## 計畫 Milestone

| # | 標題 | 預期產出 | 狀態 |
|---|------|---------|------|
| M1 | 結構 + VNScript 規格 + git init | 目錄樹、docs/vnscript-spec.md、.gitignore | ✅ |
| M2 | 核心引擎 HTML/CSS/JS | engine/index.html、engine.css、parser.js、engine.js、state.js | ✅ |
| M3 | 管理器 + UI 元件 | scene/character/audio/effects.js、textbox/choicebox/menu.js | ✅ |
| M4 | 劇本轉換 + SVG 佔位素材 | scripts/taichung-anqu/*.vns、assets/backgrounds/*.svg、assets/manifest.json | ✅ |
| M5 | 工具腳本 + README | tools/md_to_vns.py、gen_manifest.py、README.md | ✅ |

## 進度日誌

### M1 — 結構 + 規格 + git init
- 建立完整目錄樹（engine/、scripts/、assets/、tools/、docs/）
- 撰寫 VNScript 格式規格（docs/vnscript-spec.md）
- 初始化 git repo

## Fallback 指引
若需接手或 rollback：
- 整個專案在 `C:\Users\User\vn-engine\`
- 以瀏覽器開啟 `engine/index.html`（需先執行 `python serve.py`）
- 劇本在 `scripts/taichung-anqu/` 三個章節
- 素材目錄 `assets/`，manifest 在 `assets/manifest.json`
