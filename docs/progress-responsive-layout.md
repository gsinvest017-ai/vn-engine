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

（隨 milestone 完成追加）

## Fallback 指引

- 全部變更只動 3 個檔案：`engine/css/engine.css`、`engine/index.html`、
  `dashboard/index.html`，皆為附加式（原桌面樣式不變，media query 只在
  小螢幕生效）。
- Rollback：`git log --oneline | grep 'M[0-9]:'` 找到對應 commit，
  `git revert <hash>` 即可，無 schema/資料遷移。
- 驗證指令：`python3 serve.py 8081 --no-browser` 後開
  `http://localhost:8081/engine/` 與 `/dashboard/`，DevTools 切換裝置模擬。
