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

（隨 milestone 完成追加）

## Fallback 指引

- 變更檔案：`engine/js/core/parser.js`、`engine/js/ui/textbox.js`、
  `engine/js/preview.js`（新檔）、`engine/js/main.js`（M1）；
  `dashboard/index.html`（M2）。
- 預覽模式完全走 `?devPreview=1` 分支，正常遊戲路徑不受影響；
  rollback 只需 revert 對應 commit。
- 驗證：`python3 serve.py 8081 --no-browser` → dashboard 選劇本 →
  ✎ 編輯 → 右欄應出現遊戲畫面並跟隨游標。
