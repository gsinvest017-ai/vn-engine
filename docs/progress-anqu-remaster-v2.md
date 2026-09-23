# 《暗渠之書》影片重製 v2 進度

## 目標
針對 v1 成片（`video_out/anqu_narrated.mp4`，9:15，2026-09-22）做局部修正，不整段重生：
1. 旁白唸錯字、不符台灣讀音的字詞
2. clip 之間銜接卡頓、不一致
3. 畫面招牌／對聯等處的非真實漢字
4. 新增配樂：鐘聲＋風鈴＋鋼片琴，寂寥、稀疏、詭異

## 隔離與版本保留
- 另一個 session（darkgame）同時在 `gs-video-factory` 做 M1 搬遷，本任務**不碰**該 repo，也不寫入 `C:\Users\User\vn-engine` 原 checkout。
- 工作樹：`C:\Users\User\vn-engine-remaster`，分支 `dev/anqu-remaster-v2`（從 `dev/video-narration` @ `c073a2b` 分出）。
- clip、旁白、聲音樣本都是**複製**進工作樹的 `video_out/`；v1 成片另存於 `video_out/v1_baseline/anqu_narrated.mp4`，原 checkout 的所有 v1 產物保持原樣。
- v2 產物一律放 `video_out/remaster_v2/`，修補後的 clip 放 `remaster_v2/clips_fixed/`（不覆寫原 clip）。

## Milestones
- [ ] M1 檢測：發音、銜接、假漢字三份報告＋工具調研（平行 workflow）＋配樂初版
- [ ] M2 旁白局部修正：只重合成／替換有問題的句子
- [ ] M3 畫面局部修補：假字區域換真字或抹除，只重算受影響 clip
- [ ] M4 組裝 v2：RIFE 補幀、段間溶接、色彩匹配、PCM 音訊組裝、配樂混音
- [ ] M5 驗收：v1/v2 對照量測、抽幀、成片

## 進度日誌
- 2026-09-23：建工作樹、複製素材、v1 另存；啟動檢測 workflow（`wf_b0e4f46b-c1a`）。

## 決策紀錄
- autopilot 的 hook 旗標是舊的（綁在其他 session），本 session 未武裝；依 autopilot 守則照常推進，不自行改旗標。
