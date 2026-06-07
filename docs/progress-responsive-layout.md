# 進度 — Dashboard 與遊戲畫面自適應布局（Responsive Layout）

## 目標

讓 VN Engine 遊戲畫面（`engine/`）與 Dev Dashboard（`dashboard/`）能根據
電腦 / 平板 / 手機螢幕尺寸與方向自適應調整布局：桌面維持現有設計，
平板縮小留白，手機重排為可觸控操作的單欄/堆疊布局。

## 計畫 Milestone

| # | 內容 | 預期產出 |
|---|------|---------|
| M1 | Engine 遊戲畫面 RWD | `engine/css/engine.css` 加入 CSS 變數化尺寸 + `dvh` + safe-area + 3 段 breakpoint；`engine/index.html` viewport meta 加 `viewport-fit=cover` |
| M2 | Dashboard RWD | `dashboard/index.html` 3 欄 grid → 平板 2 欄 → 手機單欄堆疊；解除手機端 `overflow:hidden`；topbar 換行適配 |
| M3 | 驗證 + 文件 | 啟動 serve.py 驗證頁面正常；README 補充；本進度檔收尾 |

## 設計決策

- **斷點**：`1024px`（平板）、`768px`（手機橫式/大手機）、`520px`（手機直式）；
  另用 `(orientation: portrait)` 處理直式特例。
- **視口高度**：`100vh` → `100dvh`（保留 `100vh` fallback），解決手機瀏覽器
  網址列吃掉視口的問題。
- **safe-area**：`env(safe-area-inset-*)` 套用於 textbox 底部與 HUD，
  避開 iPhone 瀏海/Home indicator。
- **尺寸變數化**：`--textbox-h`（原硬編碼 190/195/200px 三處不一致）統一為
  CSS 變數，characters-layer 與 choice-box 隨之連動。
- **觸控目標**：手機端 HUD 按鈕從 2rem 放大到 ≥2.75rem（約 44px），
  menu 按鈕加大 padding。
- **Dashboard 手機端**：單欄堆疊（topbar → scripts → validate → 內容 → assets
  → tools），body 改 `overflow-y:auto`，panel 內部仍可獨立捲動。
  不做 JS tab 切換，純 CSS 完成（維持零依賴原則）。

## 進度日誌

## M1 — Engine 遊戲畫面 RWD（commit `3caf94d`）

- `:root` 新增 responsive tokens：`--textbox-h`、`--textbox-pad-x`、
  `--hud-btn-size`、`--char-max-w/h`、`--safe-*`（safe-area inset）。
  統一原本三處不一致的硬編碼（characters bottom 190px / textbox 195px /
  choice bottom 200px），改為由 `--textbox-h` 連動。
- `#vn-root` 高度 `100vh` → `100dvh`（保留 fallback）。
- textbox / HUD / choice-box 套 `env(safe-area-inset-*)`。
- 四段 media query：`≤1024`（平板）、`≤768`（手機）、`≤520`（直式）、
  `max-height ≤480`（橫式矮視口）。choice-box 加 `max-height` + 內捲，
  避免選項過多時超出畫面。
- `(hover:none) and (pointer:coarse)`：hover 位移效果取消、改 `:active`
  回饋；HUD 按鈕在**所有觸控裝置**放大到 2.75rem（≥44px），不依賴寬度
  斷點（修正橫式手機寬 844px 不觸發 768 斷點、HUD 僅 32px 的問題）。
- `engine/index.html` viewport meta 加 `viewport-fit=cover`。

## M2 — Dashboard RWD（commit `33ef97c`）

- 769–1100px（平板）：3 欄 → 2 欄，右側 assets 欄移到底部橫排
  （`grid-row: 2`、橫向捲動、每個 panel `flex: 1 0 230px`）。
  media query 用 `(max-width:1100px) and (min-width:769px)` 區間限定，
  避免 `#sidebar-right .panel` 高優先權規則洩漏到手機版。
- ≤768px（手機）：解除 `html,body overflow:hidden`，`#layout` 改單欄
  flex 堆疊；panel 各自 `max-height: 40vh` 內捲、整頁下捲；topbar 改
  sticky + flex-wrap；觸控目標放大 + `:active` 回饋。
- ≤480px：字級 12px、`#script-topbar` 統計列換行、行號欄縮窄。

## M3 — Playwright 驗證（本 commit）

以 Playwright（Chromium headless）對兩頁 × 4 視口（1440×900 / 900×1180 /
390×844 / 844×390）跑水平溢出檢查：**8/8 通過**（`scrollW == clientW`、
無 JS error）。另對遊戲畫面實際點進對話流程驗證：

| 視口 | textbox 高 | HUD 按鈕 | 結果 |
|------|-----------|----------|------|
| 844×390 橫式手機 | 120px（矮視口規則生效） | 44×44 | ✓ |
| 390×844 直式手機 | 145px | 44×44 | ✓ |
| 1024×768 平板    | 175px | 44×44（touch） | ✓ |

驗證腳本：`/tmp/rwd-check.cjs`、`/tmp/rwd-game.cjs`（一次性，未入 repo；
需要時可從本檔重建，依賴 `NODE_PATH=/mnt/c/Users/User/autogo/node_modules`
借用 autogo 的 playwright）。

## Fallback 指引

- 全部變更只動 3 個檔案：`engine/css/engine.css`、`engine/index.html`、
  `dashboard/index.html`，皆為附加式（原桌面樣式不變，media query 只在
  小螢幕生效）。
- Rollback：`git log --oneline | grep 'M[0-9]:'` 找到對應 commit，
  `git revert <hash>` 即可，無 schema/資料遷移。
- 驗證指令：`python3 serve.py 8081 --no-browser` 後開
  `http://localhost:8081/engine/` 與 `/dashboard/`，DevTools 切換裝置模擬。
