# Dev Dashboard 進度 — 暗渠之書

## 目標
為 VN Engine 開發後臺建立瀏覽器型 Dashboard，讓開發者在 `http://localhost:8080/dashboard/` 可以：
- 瀏覽所有 .vns 腳本（語法高亮 + 命令統計）
- 驗證資產完整性（自動偵測缺失背景/角色/音效）
- 預覽所有背景縮圖、角色表情
- 從任意場景跳入遊戲測試（Dev Jump）
- 查看近期 git 提交記錄

## 計畫 Milestone

| #  | 項目                          | 預期產出                                               |
|----|-------------------------------|--------------------------------------------------------|
| M1 | serve.py API 升級             | `/api/scripts`, `/api/manifest`, `/api/validate` 等路由 |
| M2 | `dashboard/index.html` 核心   | 三欄佈局 + 素材格線 + Git log                          |
| M3 | VNS 語法高亮 + 命令統計       | 腳本檢視器 + 統計列                                    |
| M4 | Dev Jump + main.js 整合       | `?devScene=X` / `?devChapter=N` URL 參數跳入遊戲       |

## 進度日誌

## M1 — serve.py API 升級

**Commit**: 02f55c8

新增 6 個 JSON API 路由（全部加在原有靜態服務之上，不破壞現有功能）：

| 路由 | 用途 |
|------|------|
| `GET /api/scripts` | 列出所有 .vns 檔案 + 命令統計 + 預估時間 |
| `GET /api/scripts/content?f=...` | 讀取腳本內容（限 project root 內） |
| `GET /api/manifest` | 回傳 assets/manifest.json |
| `GET /api/assets/check` | 列出 assets/ 目錄下所有實際存在的檔案 |
| `GET /api/git/log` | 最近 20 筆 git commits |
| `GET /api/validate` | 掃描 .vns 檔案，偵測缺失背景/角色/音效 |

啟動後同時開啟 `/dashboard/` 而非 `/engine/`。

---

## M2+M3 — Dashboard UI + VNS 語法高亮

**Commit**: 02f55c8（同上）

`dashboard/index.html`（單檔，無 build 步驟）：

**三欄佈局**：
- 左欄：腳本列表（點選載入）+ 驗證問題清單 + Git log
- 中欄：VNS 腳本檢視器（語法高亮 + 命令統計列）
- 右欄：背景縮圖格線 + 角色表情格線 + 音訊狀態列表

**VNS 語法高亮**：
- `@cmd` 琥珀色 / `key=` 青色 / `=val` 綠色
- `[char] text` 藍色名 + 白色對話
- `> quote` 斜體淡金 / 旁白灰 / `# comment` 暗灰

**功能**：
- 每個 `@scene` 行旁有 `▶` 按鈕，點選直接開啟 `/engine/?devScene=X` 測試
- 驗證問題內聯顯示（行號 + 錯誤/警告圖示）
- 背景/角色縮圖點擊放大燈箱預覽
- 音訊欄 ✓ 有檔 / ⚡ 程序式 / ✗ 缺失

---

## M4 — Dev Jump（main.js URL 參數跳入）

**Commit**：本次

`engine/js/main.js` 新增：
- `?devScene=<bg_id>` — 啟動後跳至第一個 `@scene bg=<bg_id>` 命令
- `?devChapter=<N>` — 啟動後跳至第 N 章（0-indexed）
- Dev banner：跳入時頂部顯示 4 秒黃色提示條（`⌘ DEV JUMP → Scene: ...`）
- 若場景/章節不存在，fallback 至命令 0，console.warn 提示

## Fallback 指引

- serve.py API 全部為附加功能，不影響靜態檔案服務
- 若要還原：`git checkout <hash> -- serve.py` 即可退回舊版
- dashboard/index.html 為獨立新檔，刪除不影響遊戲
- main.js 的 devJump 功能：若 URL 無 `?devScene` 參數，完全不影響正常遊戲流程
