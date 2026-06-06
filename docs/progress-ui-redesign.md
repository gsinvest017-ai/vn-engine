# UI 重設計進度

## 目標
1. 從 VRoid Hub 找到適合的免費男性 VRM 角色（偵探/旁白者 + 本土青年/刁才弟）
2. 重新設計遊戲 UI（engine/css/engine.css + engine/index.html）
3. 重新設計 Dev Dashboard（dashboard/index.html）

主題：台中舊城暗夜偵探 / 地下水道神秘 / 台灣本土 film noir

## 計畫 Milestone

| # | 項目 | 預期產出 |
|---|------|---------|
| M1 | 找 VRoid Hub 免費男性角色 | 至少 2 個候選清單，附截圖與下載方式 |
| M2 | 遊戲 UI 重設計（engine.css） | 更沉浸的主選單、對話框、HUD |
| M3 | Dashboard 修復 + 重設計 | PNG 預覽修復，視覺風格統一 |
| M4 | 主選單視覺升級（動畫+背景） | 更有氛圍感的標題畫面 |
| M5 | 整合測試 + commit | 全部改動 commit |

## 進度日誌

### M1 — VRoid Hub 角色調查
搜尋 URL：https://hub.vroid.com/en/search/man（條件：avatar use + modification allowed）

**⚠️ VRoid Hub 下載需登入 pixiv 帳號**

推薦候選（旁白者/偵探 — 成熟男性外型）：
- 黑西裝深色風格：https://hub.vroid.com/en/characters/2634206014740133981/models/2570375855744653058
- 白衬衫成熟男：https://hub.vroid.com/en/characters/7491007904275077225/models/3864522718273503822

推薦候選（刁才弟 — 本土休閒青年）：
- Losan man 休閒：https://hub.vroid.com/en/characters/1575275029311320602/models/3612498028016912643
- 深色休閒青年：https://hub.vroid.com/en/characters/2858058017868979905/models/2920736224577873605

替代免費 VRM（無需登入）：
- Booth.pm → 搜尋 `VRM 男性 無料`，選免費商品後下載 .vrm
- niconicommons 搜尋 `VRM 男性`

下載後操作：存至 `tools/vrm/<角色名>.vrm`，告知 Claude Code 用 Blender MCP 渲染即可

### M2 — 遊戲 UI 重設計 (engine.css) — commit 28e84b2
- 主選單：水波紋動畫 canvas、金色掃光標題入場、teal 副標、左邊框按鈕滑入效果
- 對話框：頂部 amber 光線 + 右上角裝飾邊框、◆ 角色名徽章、blur(12px) 玻璃效果
- 選擇框：teal 提示 + amber 左邊框選項 + hover 左移動畫
- Chapter card：上下橫線從中心展開動畫
- 新增 CSS 變數：--teal / --teal-light（地下水道水色）、--red-neon（舊城霓虹）

### M3 — Dashboard 修復 — commit 28e84b2
- renderBackgrounds()：PNG 優先（讀 manifest.file 副檔名），背景縮圖正確顯示
- renderCharacters()：PNG 優先 + VRM 來源徽章（.char-src teal 色 badge）

### M4 — 主選單水波動畫 — commit 28e84b2
- engine/index.html 加入 #menu-canvas
- 18 條波線 teal+amber 雙色 canvas 動畫，與 .active class 連動

## Fallback 指引
- 還原 engine.css：`git checkout 0bb4bdc -- engine/css/engine.css`
- 還原 dashboard：`git checkout 0bb4bdc -- dashboard/index.html`
- VRM 渲染流程：見 `docs/progress-vrm-character-render.md`
