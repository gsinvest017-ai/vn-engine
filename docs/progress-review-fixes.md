# 進度 — Review 清單全量實作（遊戲 P0–P2 + Dashboard P0–P1 + 基礎設施）

## 目標

把 review 找出的所有改進一次做完：遊戲端修掉「壞的」功能（讀檔黑畫面、
主選單死按鈕、history 流失）、補表現力（@set/@if 變數）與體驗（設定面板、
預載、reduced-motion、手勢）；Dashboard 端把寫稿迴圈提速（行內 lint、
自動完成、資產插入、從游標行開始玩）並補工作流（新建、還原、試聽、
分支圖、熱重載）；基礎設施換多執行緒 server 並把 E2E 測試收編 + CI。

## 計畫 Milestone

| # | 內容 | 預期產出 |
|---|------|---------|
| M1 | 遊戲 P0 | `core/replay.js` 共用狀態重建；save/load 完整修復（含 cmdIndex 從未更新的隱藏 bug）；主選單「讀取存檔」「設定」實作；設定面板（文字速度/auto 延遲/音量/全螢幕）；history 持久化；choice 進 history；結局「回主選單」 |
| M2 | 遊戲 P1/P2 | parser+engine 支援 `@set` / `@if`；loadStory 後資產預載；`prefers-reduced-motion`；手機上滑開 history 手勢 |
| M3 | Dashboard P0 | 編輯器行內 lint（前端直接 import 引擎 parser）；context-aware 自動完成 chips；資產縮圖點擊插入指令；「▶ 從游標行」開真實遊戲（devFile+devLine，重用 replay 重建狀態） |
| M4 | Dashboard P1 | ✚ 新建劇本；↩ .bak 還原；音訊試聽（含程序式 fallback）；分支流程圖 modal；存檔熱重載遊戲分頁（BroadcastChannel） |
| M5 | 基礎設施 | serve.py 換 ThreadingHTTPServer + allow_reuse_address；`tests/e2e/` 收編 Playwright 腳本 + GitHub Actions workflow；README/進度檔收尾 |

## 設計決策

- **狀態重建單一來源**：`engine/js/core/replay.js` 的 `accumulateState(commands,
  {uptoIndex, uptoLine})`，preview.js / 讀檔恢復 / devLine 起跑三處共用。
- **save/load 語意**：存檔記「目前顯示中的指令 index」；讀檔 = 重建該 index
  （含）之前的累積狀態（背景/立繪/BGM/台詞/頭像）→ 從 index+1 等輸入。
  順帶修掉 `state.cmdIndex` 在主迴圈從未更新、存檔永遠記 0 的隱藏 bug。
- **@set/@if 語法**：`@set key=value`（number/bool/string 自動判型，支援
  `+=`）；`@if <key><op><value> jump=<label>`（op: == != >= <= > <）。
  choice 影響劇情 = 選項跳到的 label 區塊內寫 `@set`。
- **自動完成不做 caret 浮層**：textarea 算 caret 像素要 mirror-div hack，
  改用編輯器上方 context chips 列（游標在 `bg=`/`show=`/`expr=`/`play=`
  token 時列出 manifest 候選，點擊替換 token），簡單可靠。
- **行內 lint**：dashboard 動態 `import('/engine/js/core/parser.js')` 用
  真 parser；規則：bg/char/expr 不存在（對 manifest+assetMap）、jump 到
  未定義 label、重複 label、@set/@if 格式錯誤。結果列在編輯器下方
  lint 列（點擊跳行），與既有 server 端 VALIDATE 互補。
- **熱重載**：BroadcastChannel `vn-reload`；遊戲分頁（非 preview iframe）
  收到後 reload。
- **CI**：GitHub Actions 起 `python serve.py` + `npx playwright` 跑
  `tests/e2e/*.cjs`（RWD 溢出、預覽、編輯/匯入、讀檔恢復）。

## 進度日誌

（隨 milestone 完成追加）

## Fallback 指引

- M1–M2 動 `engine/js/**` + `engine/index.html` + `engine/css/engine.css`；
  M3–M4 動 `dashboard/index.html` + `serve.py`（新 API）；
  M5 動 `serve.py`、新增 `tests/`、`.github/workflows/e2e.yml`。
- 各 milestone 獨立 commit，`git revert` 即可單獨回退。
- 驗證：`python3 serve.py 8081 --no-browser` + `tests/e2e/` 腳本
  （`NODE_PATH=/mnt/c/Users/User/autogo/node_modules node tests/e2e/<x>.cjs`）。
