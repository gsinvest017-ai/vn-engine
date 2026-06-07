# 進度 — 對話框頭像常駐 + Dev Dashboard 開發者體驗改進

## 目標

1. **對話框頭像**：遊戲畫面目前 narrator 立繪只在 `@char show` 時出現在
   角色層；要讓「正在說話的人」的頭像**常駐顯示在對話框內**——旁白行
   顯示 narrator（主角視角）、角色對白顯示該角色，表情跟隨劇本
   `@char expr=` 變化。
2. **Dashboard DX**：讓開發者能直接在 dashboard 開發劇本——
   file selector 匯入 .vns 劇本檔、中央檢視器可切換編輯模式直接改稿
   （Ctrl+S 儲存 + 即時重新驗證），不用離開瀏覽器。

## 計畫 Milestone

| # | 內容 | 預期產出 |
|---|------|---------|
| M1 | 對話框頭像 | `engine/index.html` 加 `#portrait`；`engine.css` 頭像框樣式（含 RWD）；`textbox.js` 接收 portrait 參數；`engine.js` 追蹤每角色最後表情、dialogue/narration 都帶頭像 |
| M2 | serve.py 寫入 API | `POST /api/scripts/save`（編輯儲存）、`POST /api/scripts/upload`（匯入劇本，multipart）；path-traversal 防護 + 副檔名白名單 |
| M3 | Dashboard UI | SCRIPTS panel「⊕ 匯入」按鈕（file selector 多檔、可選目標故事目錄）；中央 viewer「✎ 編輯」模式（textarea + Ctrl+S）；存檔後自動 re-validate |
| M4 | 驗證 + 文件 | Playwright 驗證頭像顯示與上傳/編輯 flow；README + 進度檔收尾 |

## 設計決策

- **頭像來源**：直接重用 `assets/characters/<id>/<expr>.png` 立繪
  （800×1600 全身圖），用 `object-fit: cover; object-position: 50% 8%`
  裁出頭部區域，不需要額外產一套頭像素材。PNG 失敗 fallback SVG。
- **旁白 = narrator**：此遊戲為第一人稱偵探視角，旁白行視為主角內心
  獨白，故旁白顯示 narrator 頭像。`main.js` STORY_CONFIG 加
  `narratorPortrait: 'narrator'`，其他故事可設 `null` 關閉。
- **表情追蹤**：engine 維護 `_exprState`（charId → 最後表情），
  `char_show` / `char_expr` 都更新；頭像取 `_exprState[id] || 'normal'`，
  即使角色立繪不在場上，表情變化也反映在頭像。
- **上傳安全**：只收 `.vns` / `.yaml`、單檔 ≤ 2MB、檔名 sanitize
  （只留 `[\w\-.]`）、目標限制在 `scripts/<story>/` 下、
  resolve 後驗證仍在 ROOT 內。
- **編輯儲存**：覆寫前先把原檔備份到 `.bak`（同目錄、單一輪替），
  讓 git 之外多一層即時安全網。

## 進度日誌

（隨 milestone 完成追加）

## Fallback 指引

- 變更檔案：`engine/index.html`、`engine/css/engine.css`、
  `engine/js/ui/textbox.js`、`engine/js/core/engine.js`、
  `engine/js/main.js`（M1）；`serve.py`（M2）；`dashboard/index.html`（M3）。
- Rollback：`git log --oneline | grep 'M[0-9]:'` 後 `git revert <hash>`。
- 驗證：`python3 serve.py 8081 --no-browser`，開 `/engine/` 點開始遊戲
  看對話框左側頭像；開 `/dashboard/` 試 ⊕ 匯入與 ✎ 編輯。
