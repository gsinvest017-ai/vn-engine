# 進度 — Dashboard VNS 編輯區 HackMD 式雙欄即時預覽

## 目標

Dev dashboard 的劇本編輯模式升級為 HackMD 式雙欄：左邊文字編輯區、
右邊**即時渲染預覽**——以真實遊戲引擎渲染游標所在行的畫面狀態
（背景 / 角色立繪 / 對話框頭像 / 天氣 / BGM 指示），打字或移動游標
即更新，不用另開分頁重新跑遊戲。

## 計畫 Milestone

| # | 內容 | 預期產出 |
|---|------|---------|
| M1 | Engine 預覽模式 | `parser.js` 指令帶來源行號；`textbox.js` 支援 instant（跳過打字機）；新增 `engine/js/preview.js`（PreviewDriver：劇本全文 + 游標行 → 重建累積狀態 → diff 套用到真實 managers）；`main.js` 走 `?devPreview=1` 分支；postMessage 協議 |
| M2 | Dashboard 雙欄 UI | 編輯模式右側嵌 `/engine/?devPreview=1` iframe；輸入 debounce 同步 + 游標行跟隨；「◧ 預覽」開關（localStorage 記憶）；RWD 窄幅直疊 |
| M3 | E2E 驗證 + 文件 | Playwright：打字改場景行 → 右欄背景即時變化；README + 進度檔收尾 |

## 設計決策

- **預覽 = 真實引擎 iframe**，不另寫 mini-renderer：嵌
  `/engine/?devPreview=1`，同一套 CSS/managers/頭像邏輯，零視覺漂移。
- **狀態重建**：preview 不跑互動主迴圈；每次更新把劇本 parse 後從頭
  累積「游標行之前」的狀態（bg / weather / bgm / 各角色 pos+expr /
  最後一句 text+speaker），與上次套用結果 **diff** 後只更新變動部分
  （背景同 id 不重切、角色只調表情/位置），避免每鍵閃爍。
- **瞬時類指令**（shake/flash/fade/wait）預覽中跳過，只重建「持續狀態」。
- **聲音**：BGM 以 badge 顯示目前曲目（`♪ id`）；瀏覽器 autoplay 限制
  下，AudioContext 需手勢解鎖——badge 即按鈕，點一下啟動聲音播放。
- **行號**：parser 為每個 command 記 `line`（1-based 來源行），同時給
  preview（游標 → 狀態）與未來 lint 使用；choice 選項行歸屬 @choice 行。
- **postMessage 協議**：parent→iframe `{type:'vns-preview', content, line}`；
  iframe→parent `{type:'vns-preview-ready'}`（握手後才開始送）。
  同 origin 檢查。

## 進度日誌

## M1 — Engine 預覽模式（commit `24aedd8`）

- `parser.js` 每個 command 帶 `line`（1-based 來源行號）。
- **修重大既有 bug**：`case 'char'` 用 `firstToken(rest) === 'show'` 判斷
  子指令，但實際格式是 `show=<id>`（firstToken 回傳 `show=narrator`），
  導致**所有** `@char show/expr/move` 從引擎誕生起就是 no-op——立繪
  只剩「對白自動上場」一條路。這正是前一個任務使用者抱怨
  「narrator 圖像根本沒用到」的根因。改用 params key 判斷。
  附帶效果：修好後正式遊戲的立繪/表情指令全部活了。
- `textbox.js` `show()` 加 `instant` 選項（跳過打字機）。
- 新增 `preview.js` `PreviewDriver`：
  - 直接複用 SceneManager / CharManager / EffectsManager / TextBox /
    AudioManager，零視覺漂移。
  - `_stateAt(cmds, line)`：累積游標行前的持續狀態；
    `apply()`：與上次套用 diff，只動變動部分（防打字閃爍）。
  - BGM badge（♪/🔇）兼聲音解鎖按鈕；PREVIEW 標記。
- `main.js`：`?devPreview=1` 動態 import preview.js。

## M2 — Dashboard 雙欄 UI（commit `e5aa04e`）

- `#editor-split` grid：textarea 左 + `/engine/?devPreview=1` iframe 右；
  `no-preview` class 單欄化。
- 同步：input debounce 250ms；keyup/click（游標移動）120ms；
  `vns-preview-ready` 握手後才開始送（同 origin 檢查兩端都有）。
- 「◧ 預覽」開關記憶在 localStorage（`vnsPreviewOn`）。
- RWD：≤1280px 編輯/預覽上下疊；≤768px 各 40vh。
- 預覽 iframe 窄寬會觸發 engine 自身的 RWD breakpoints（畫面如手機版）
  ——視為合理行為（同時可預覽手機版型）。

## M3 — 回歸驗證 + 文件（本 commit）

- E2E：游標移行 → 背景/台詞/頭像跟隨；打字改行 → 900ms 內預覽更新；
  換景行 → old_city_dusk ⇄ shrine_interior 正確切換；開關正常。
- 回歸：遊戲本體對白流程（speaker/頭像）正常；2 頁 × 4 視口
  水平溢出 8/8 通過。
- README 補雙欄預覽說明。

## Fallback 指引

- 變更檔案：`engine/js/core/parser.js`、`engine/js/ui/textbox.js`、
  `engine/js/preview.js`（新檔）、`engine/js/main.js`（M1）；
  `dashboard/index.html`（M2）。
- 預覽模式完全走 `?devPreview=1` 分支，正常遊戲路徑不受影響；
  rollback 只需 revert 對應 commit。
- 驗證：`python3 serve.py 8081 --no-browser` → dashboard 選劇本 →
  ✎ 編輯 → 右欄應出現遊戲畫面並跟隨游標。
