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

### M1 — 結構 + 規格 + git init（commit 937696c）
- 建立完整目錄樹（engine/、scripts/、assets/、tools/、docs/）
- 撰寫 VNScript 格式規格（docs/vnscript-spec.md）
- 初始化 git repo

### M2 — 核心引擎（commit 668d2dc）
- engine/index.html：主畫面 DOM 結構（主選單/遊戲畫面/Overlay）
- engine/css/engine.css：黑色電影主題（amber accent，CSS 動畫）
- parser.js：.vns 腳本解析器，支援所有指令類型
- engine.js：async 指令執行引擎，支援 auto/skip 模式
- state.js：localStorage 存/讀檔，9 個 slot

### M3 — 管理器 + UI（commit 40a665a）
- scene.js：背景轉場（fade/dissolve/wipe）
- character.js：立繪顯示/表情切換/說話者高亮
- audio.js：BGM + SFX，Web Audio API，缺音檔靜默降級
- effects.js：Canvas 雨粒子 + CSS 震動/閃光/暗化/暈影
- textbox.js：打字機效果，click 跳過
- choicebox.js / menu.js：選擇分支 + 存讀歷史 Overlay

### M4 — 劇本 + 素材（commit 9fd6d9f）
- 《暗渠之書》三章完整 .vns 腳本（原文完整移植）
- 6 張場景 SVG 佔位背景（大氣效果，保有正確色調）
- 2 角色 × 多表情 SVG 立繪（narrator 6 表情，刁才弟 3 表情）
- manifest.json：素材清單 + AI 提示詞（gen_manifest.py 更新後全 ready）
- gen_manifest.py 輸出：背景 5/5 OK，角色 9/9 OK，音效 9/9 missing

### M5 — 工具 + README（commit 2b430af）
- gen_manifest.py：素材狀態掃描工具
- md_to_vns.py：純文字轉 .vns 草稿（Big5/UTF-8 自動偵測）
- prompts/taichung-anqu-assets.md：AI 生成提示詞（中英雙語）
- serve.py：一鍵 HTTP server + 自動開瀏覽器
- README.md：完整使用說明

## Fallback 指引
若需接手或 rollback：
- 整個專案在 `C:\Users\User\vn-engine\`
- 以瀏覽器開啟 `engine/index.html`（需先執行 `python serve.py`）
- 劇本在 `scripts/taichung-anqu/` 三個章節
- 素材目錄 `assets/`，manifest 在 `assets/manifest.json`
