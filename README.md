# VN Engine — 視覺小說遊戲製作框架

一套輕量級、無需安裝、瀏覽器直跑的視覺小說引擎。  
以**純文字劇情腳本（.vns）**為核心，對位生成角色立繪、場景背景、畫面特效、音效等素材。

> 測試文本：**《暗渠之書》**（台中舊城的記憶）— 三章完整劇本

---

## 快速開始

```bash
# 1. 啟動本地 server（必需，ES modules 不能 file:// 執行）
python serve.py

# 2. 瀏覽器會自動開啟 http://localhost:8080/engine/
```

點選「**開始遊戲**」即可執行《暗渠之書》測試劇本。

---

## 網頁試玩版部署

Engine 為純靜態網站，無需後端，可直接部署至任何靜態托管平台。

### 最快：Netlify Drop（60 秒，不需帳號）
```bash
python pack_demo.py        # 產生 dist/（54 files, ~9.7 MB）
# 拖 dist/ 到 https://app.netlify.com/drop
# → 立即取得 https://xxxx.netlify.app 分享連結
```

### itch.io（最適合遊戲分享）
```bash
python pack_demo.py --zip  # 額外產生 vn-demo.zip（~9.5 MB）
# itch.io → Create new project → Kind: HTML
# 上傳 vn-demo.zip → 勾選「This file will be played in the browser」
```

### GitHub Pages（push 後自動更新）
```bash
git remote add origin https://github.com/<user>/vn-engine.git
git push -u origin main
# repo Settings → Pages → Source: GitHub Actions
# URL: https://<user>.github.io/vn-engine/
```

詳細步驟見 [docs/progress-deploy.md](docs/progress-deploy.md)

---

## 目錄結構

```
vn-engine/
├── engine/                  ← 瀏覽器遊戲本體
│   ├── index.html           ← 入口
│   ├── css/engine.css       ← 全局樣式（黑色電影主題）
│   └── js/
│       ├── main.js          ← 初始化 + 主選單
│       ├── core/
│       │   ├── parser.js    ← .vns 腳本解析器
│       │   ├── engine.js    ← 指令執行引擎
│       │   └── state.js     ← 存/讀檔（localStorage）
│       ├── managers/
│       │   ├── scene.js     ← 背景轉場
│       │   ├── character.js ← 角色立繪管理
│       │   ├── audio.js     ← BGM + SFX（Web Audio API）
│       │   └── effects.js   ← 視覺特效（雨、震、閃、暗）
│       └── ui/
│           ├── textbox.js   ← 打字機文字框
│           ├── choicebox.js ← 選擇分支 UI
│           └── menu.js      ← 存檔/歷史 Overlay
│
├── scripts/                 ← 劇情腳本
│   └── taichung-anqu/
│       ├── config.yaml      ← 故事設定
│       ├── chapter1.vns     ← 第一章
│       ├── chapter2.vns     ← 第二章
│       └── chapter3.vns     ← 第三章
│
├── assets/                  ← 素材資源
│   ├── manifest.json        ← 素材清單 + AI 生成提示詞
│   ├── backgrounds/         ← 場景背景（目前為 SVG 佔位）
│   ├── characters/          ← 角色立繪（目前為 SVG 佔位）
│   └── audio/bgm/ + sfx/    ← 音效（目前為空，見 manifest.json）
│
├── tools/
│   ├── gen_manifest.py      ← 掃描腳本，生成素材狀態報告
│   ├── md_to_vns.py         ← 純文字轉 .vns 草稿
│   └── prompts/
│       └── taichung-anqu-assets.md ← AI 生成提示詞（中/英）
│
├── docs/
│   ├── vnscript-spec.md     ← VNScript 語法完整參考
│   └── progress-vn-framework.md ← 建構進度日誌
│
└── serve.py                 ← 本地開發 server
```

---

## VNScript 格式速覽

```vns
# 這是註解

@chapter 第一章　章節標題

@scene bg=old_city_dusk music=ambient_old_city transition=fade
@weather rain=light

旁白文字直接寫，無需前綴。

@char show=narrator pos=right expr=tired

[diao_caidi] 角色對話用方括號包住 ID。

@char expr=narrator:troubled

> 引號旁白用大於號前綴（顯示不同樣式）。

@effect shake intensity=0.5 duration=600
@wait 1000
@fade out duration=800

@chapter_end
```

完整語法見 → [docs/vnscript-spec.md](docs/vnscript-spec.md)

---

## 遊戲操作

| 動作 | 鍵盤 | 滑鼠 |
|------|------|------|
| 下一行 | Space / Enter / → | 點擊畫面 |
| 跳過打字 | Space | 點擊 |
| 自動模式 | — | HUD ▶ 按鈕 |
| 快速跳過 | — | HUD » 按鈕 |
| 存檔 | — | HUD ■ 按鈕 |
| 對話歷史 | — | HUD ≡ 按鈕 |

### 自適應布局（RWD）

遊戲畫面與 Dev Dashboard 皆支援電腦 / 平板 / 手機自適應：

- **遊戲畫面**：`100dvh` 視口 + safe-area（瀏海/Home indicator）適配；
  平板/手機自動縮小對話框與留白；觸控裝置 HUD 按鈕放大至 ≥44px、
  hover 效果改為按壓回饋；手機直式角色立繪自動調整；橫式矮視口
  （鍵盤外露）對話框再壓縮。
- **Dashboard**：平板（≤1100px）右側 assets 欄移到底部橫排；
  手機（≤768px）單欄堆疊、各 panel 內捲、topbar sticky。

### 對話框頭像

對話框左側常駐顯示說話者頭像：旁白行顯示 `narrator`（主角內心獨白視角，
`main.js` 的 `narratorPortrait` 可換角色或設 `null` 關閉）、角色對白顯示
該角色，表情跟隨 `@char expr=` 即時變化。頭像直接重用
`assets/characters/<id>/<expr>.png` 立繪，runtime 以 canvas 掃 alpha
自動裁出頭部，不需另外準備頭像素材。

### Dev Dashboard 劇本工作流

- **⊕ 匯入**（SCRIPTS panel）：file selector 選本機 `.vns` / `.txt` /
  `.yaml` 批次匯入 `scripts/<故事>/`（`.txt` 自動轉 `.vns`，同名覆蓋前
  自動備份 `.bak`）。
- **✎ 編輯**（中央檢視器）：直接改劇本、`Ctrl+S` 儲存，存檔後 VALIDATE
  與行數統計即時重跑；原檔自動備份 `.bak`。
- **▶ 場景跳轉**：`@scene` 行右側按鈕直接開遊戲跳到該場景測試。

設計細節見 `docs/progress-responsive-layout.md`。

---

## 加入新故事

1. 在 `scripts/<story-name>/` 建立目錄
2. 新增 `config.yaml`（同 taichung-anqu 格式）
3. 撰寫 `chapter1.vns`、`chapter2.vns`...
4. 在 `engine/js/main.js` 的 `STORY_CONFIG` 指向新腳本
5. 在 `assets/` 放置對應素材（或先用 SVG 佔位）
6. 執行 `python tools/gen_manifest.py` 確認素材清單

### 從純文字轉換

```bash
python tools/md_to_vns.py 你的故事.md --output scripts/你的故事/draft.vns
```
輸出為草稿，需手動補充 `@scene`、`@char`、`@effect` 指令。

---

## 素材生成

`assets/manifest.json` 包含所有素材的 **AI 生成提示詞**（中英雙語）。  
`tools/prompts/taichung-anqu-assets.md` 有完整的 Midjourney / SD 提示詞。

```bash
# 確認目前哪些素材已就緒、哪些缺失
python tools/gen_manifest.py
```

---

## 特效清單

| 指令 | 效果 |
|------|------|
| `@weather rain=drizzle/light/heavy/storm` | 雨粒子系統（Canvas） |
| `@effect shake intensity=0.5 duration=500` | 畫面震動 |
| `@effect flash color=white duration=200` | 閃光 |
| `@effect dim level=0-1` | 暗化疊層 |
| `@effect flicker count=3` | 燈光閃爍 |
| `@effect vignette intensity=0.6` | 暈影 |
| `@fade in/out color=black duration=1000` | 淡入/淡出 |
| `@char expr=X:Y` | 即時換表情 |
| `@char move=X pos=left/center/right` | 角色位移 |

---

## 技術棧

- **Pure HTML/CSS/JavaScript** — 無框架，無 build step
- **ES Modules** — 原生模組化，需 HTTP server
- **Web Audio API** — BGM + SFX，支援漸變
- **Canvas API** — 雨效粒子系統
- **localStorage** — 存/讀檔（9 slots）

---

## License

MIT
