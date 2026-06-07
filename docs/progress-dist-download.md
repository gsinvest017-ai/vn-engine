# 進度 — Dashboard 一鍵下載 dist 部署包

## 目標

Dev dashboard 加「⬇ dist」按鈕：點一下由 server 重新執行 `pack_demo.py
--zip`（永遠打包**當下最新版**，含未 commit 的修改），完成後瀏覽器直接
下載 zip（檔名帶時間戳）。

## 計畫 Milestone

| # | 內容 | 預期產出 |
|---|------|---------|
| M1 | serve.py 下載 API | `GET /api/dist/download`：subprocess 跑 `pack_demo.py --zip` → 串流 `vn-demo.zip`（`Content-Disposition` 帶 `vn-demo-<時間戳>.zip`） |
| M2 | Dashboard 按鈕 + E2E | topbar「⬇ dist」按鈕（打包中 disabled + 完成 toast）；Playwright 驗證真實下載 |

## 設計決策

- **單一打包真相**：不在 serve.py 重寫打包規則，直接 subprocess 呼叫
  `pack_demo.py --zip`（排除規則只維護一份，如 `.bak` 排除）。
- **每次重打包**：保證下載的是當下檔案系統最新狀態；~10MB 約 1–2 秒，
  可接受。timeout 180s。
- **下載檔名**：`vn-demo-YYYYMMDD-HHMM.zip`，方便保留多版本不互蓋。
- 前端用 fetch + blob 觸發下載（而非直接導頁），可顯示「⏳ 打包中…」
  與失敗 toast。

## 進度日誌

（隨 milestone 完成追加）

## Fallback 指引

- 變更檔案：`serve.py`（M1）、`dashboard/index.html`（M2）。
- Rollback：`git revert <hash>`；無資料/schema 變更。
- 驗證：dashboard topbar 點「⬇ dist」應下載 zip；或
  `curl -OJ http://localhost:8081/api/dist/download`。
