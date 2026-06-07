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

## M1 — 對話框頭像常駐（commit `7206301`）

- `engine/index.html` textbox 加 `#portrait`（古舊照片框）+ `#textbox-main`
  包住原 speaker/text；textbox 改 flex row。
- **關鍵發現**：立繪 PNG 透明邊每張位置不同（narrator 內容從 50% 高度起、
  diao_caidi 從 31%），固定 `object-position` 裁不到頭。改為離屏 canvas
  下取樣 64px 掃 alpha 找 content bounding box，「內容寬貼框寬、內容頂
  貼框頂」動態定位，結果按 src 快取；window resize 重定位。
- engine 維護 `_exprState`（charId → 最後表情）：`char_show`/`char_expr`
  更新；`char_expr` 時若頭像正顯示該角色則即時刷新。
- 旁白行 → `config.narratorPortrait`（預設 `'narrator'`，設 null 關閉）；
  對白行 → 說話者 + 其最後表情。
- RWD：`--portrait-w` token 118 → 100（平板）→ 84（手機）→ 70/72（直式/矮視口）。

## M2 — serve.py 劇本寫入 API（commit `72f3ff9`）

- `POST /api/scripts/save`：`{path, content}`，覆寫前 `.bak` 備份。
- `POST /api/scripts/upload`：`{story, files:[{name,content}]}` JSON 批次匯入
  （劇本是小文字檔，不用 multipart）；story/檔名 sanitize、`.txt`→`.vns`、
  單檔 ≤2MB、副檔名白名單 `.vns`/`.yaml`、路徑鎖死 `scripts/` 下。
- curl 驗證 path traversal（`scripts/../serve.py`、story=`../../etc`）均擋下。
- `.gitignore` 加 `scripts/**/*.bak`。

## M3 — Dashboard 匯入 + 編輯（commit `83dc431`）

- 「⊕ 匯入」：file selector（多選）→ modal（目標故事目錄 datalist）→
  upload → refresh → 自動開啟第一個匯入檔。
- 「✎ 編輯」：viewer ⇄ textarea、Ctrl+S 儲存、dirty ● 標記、離頁警告、
  切檔未存 confirm；存檔後 VALIDATE 與統計即時重跑（不離開編輯模式）。
- **修既有 bug ×2**：
  1. `_api_scripts`/`_api_validate` 用 `ROOT.rglob('scripts/**/*.vns')` 誤掃
     `dist/scripts/` 打包產物 → 劇本清單重複 6 筆、點到 dist 副本存檔被拒。
     改為 `(ROOT/'scripts').rglob('*.vns')`。
  2. `colorizeVNS` 先注入 `<span class="t-cmd">` 再跑 key=val regex，把注入
     的 `class="t-cmd"` 也當參數改寫 → `@` 行渲染破碎 HTML。改為先
     tokenize 逐段 escape（同時消除 XSS 面）。
- `refreshAll`/`confirmImport` 的 `loadScript` 補 await 消除競態。

## 後續 — pack_demo.py 排除 .bak（單發修補）

dashboard 編輯/匯入產生的 `scripts/**/*.bak` 雖然 gitignore 了，但
`pack_demo.py` 是從檔案系統複製，會把備份檔打進 dist/。加
`SKIP_SUFFIXES = {'.bak'}` 排除；驗證：放測試 .bak 跑打包，dist 內
0 個 .bak、正式檔案數不變。

## M4 — 回歸驗證 + 文件（本 commit）

- Playwright 回歸：2 頁 × 4 視口水平溢出 8/8 通過；遊戲流程在手機橫/直式
  與平板實測頭像、textbox、HUD 全部正常。
- E2E：編輯 → Ctrl+S → server 內容更新 → 還原；匯入 .vns+.txt → 3+2 筆
  劇本清單 → 自動開啟匯入檔。
- README 補「Dev Dashboard 劇本工作流」與頭像說明。

## Fallback 指引

- 變更檔案：`engine/index.html`、`engine/css/engine.css`、
  `engine/js/ui/textbox.js`、`engine/js/core/engine.js`、
  `engine/js/main.js`（M1）；`serve.py`（M2）；`dashboard/index.html`（M3）。
- Rollback：`git log --oneline | grep 'M[0-9]:'` 後 `git revert <hash>`。
- 驗證：`python3 serve.py 8081 --no-browser`，開 `/engine/` 點開始遊戲
  看對話框左側頭像；開 `/dashboard/` 試 ⊕ 匯入與 ✎ 編輯。
