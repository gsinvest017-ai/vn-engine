# 資產升級進度 — 暗渠之書

## 目標
以開源免費技術（增強 SVG 藝術 + Web Audio API 程序式音效）大幅提升「暗渠之書」的視覺與聽覺品質，使畫面更貼近台中舊城懸疑氛圍主題。不依賴外部下載，全程可離線運作。

## 計畫 Milestone

| #  | 項目                         | 預期產出                                          |
|----|------------------------------|---------------------------------------------------|
| M1 | 重繪六張背景 SVG              | 高細節氛圍藝術版本替換佔位用原始 SVG             |
| M2 | Web Audio 程序式音效引擎      | `engine/js/audio/procedural.js` + AudioManager 整合 |
| M3 | 強化角色立繪 SVG              | narrator 全表情 + diao_caidi 全表情細節提升      |
| M4 | 素材資源指引 + manifest 更新  | `docs/asset-sources.md` + manifest 狀態更新      |

## 進度日誌

<!-- 每完成一個 milestone 追加 -->

## Fallback 指引

若需回滾至某 milestone：
- 所有原始 SVG 佔位已由 git 歷史保存
- `git log --oneline` 找到 `M1:` / `M2:` 前的 commit，`git checkout <hash> -- assets/` 可還原指定資產
- 音效引擎可完全移除：刪除 `engine/js/audio/procedural.js`，還原 `engine/js/managers/audio.js` 至前一 commit 即可
