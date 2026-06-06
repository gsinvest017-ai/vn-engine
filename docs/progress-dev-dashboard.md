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

<!-- 完成後追加 -->

## Fallback 指引

- serve.py API 全部為附加功能，不影響靜態檔案服務
- 若要還原：`git checkout <hash> -- serve.py` 即可退回舊版
- dashboard/index.html 為獨立新檔，刪除不影響遊戲
- main.js 的 devJump 功能：若 URL 無 `?devScene` 參數，完全不影響正常遊戲流程
