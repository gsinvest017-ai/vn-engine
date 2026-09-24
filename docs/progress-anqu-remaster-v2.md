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
- [x] M1 檢測：發音、銜接、假漢字三份報告＋工具調研（平行 workflow）＋配樂初版
- [x] M2 旁白局部修正：只重合成／替換有問題的句子
- [x] M3 畫面局部修補：假字區域換真字或抹除，只重算受影響 clip
- [x] M4 組裝 v2：RIFE 補幀、段間溶接、色彩匹配、PCM 音訊組裝、配樂混音
- [x] M5 驗收：v1/v2 對照量測、抽幀、成片

## 進度日誌
- 2026-09-23：建工作樹、複製素材、v1 另存；啟動檢測 workflow（`wf_b0e4f46b-c1a`）。

- 2026-09-23：M1 完成（`243e7c6`）：四份檢測報告進 `docs/remaster_v2/`，配樂合成器 `bgm_synth.py`。
- 2026-09-23：啟動修正 workflow（`wf_f01d829b-9e7`）：旁白局部重合成、組裝器 v2、換字工具；6 批 clip 修補待工具完成後另行派出。

- 2026-09-23：M2 `9ea08e9` 旁白 20 句局部重合成（19 句聲學驗證通過；「沖散」未完全解決）；M4 `e4b3b46` 組裝器 v2（全片組裝 423 秒；v1→v2：環境音邊界掉音 52→0、影音長度差 3.48→0 秒、慢動作銳利度起伏中位 0.122→0.011、邊界最大亮度跳變 41.6→9.0）；M3a `3a5c13e` 換字工具（H024/H037/H094/H047 已修）。
- 2026-09-23：派出 6 批 clip 換字（resume `wf_f01d829b-9e7`，78 個物件／43 段 clip）。

- 2026-09-23：M3b `9d81cde` 41 段 clip 換字／抹除完成；正式 v2 成片 `video_out/remaster_v2/anqu_narrated_v2.mp4`（9:15.2、1080p、330MB、13325 幀；影音長度差 0、-17.0 LUFS、TP -2.7 dBTP；組裝約 6 分鐘，完全沒有重新生成 clip）。抽幀確認換字結果。
- 2026-09-24：v2.1b 第一章_03_06:0「檔案」重生：改送「挡案」（`narr_dang.py`），三套 ASR 由「火案」回到「檔／档」、時間軸不變（36 段 sec 與 v2.1 相同、plancheck 53/53）。見 `docs/remaster_v2/narration_fix.md`「v2.1b」節。尚未人耳試聽。
- 2026-09-24：**v2.1** `video_out/remaster_v2/anqu_narrated_v2_1.mp4`（555.208 秒、影音長度一致、-17.0 LUFS）：「沖散」改寫法重生（20/20 聲學驗證、三套 ASR 交叉驗證）、「檔案」唸成「火案」的退步修正、三清題名依傳統位置、桌裙全改右至左、用字定案（翰溪壇／翰溪庄道壇／大昌當舖保留）。
- 2026-09-24：審片頁 `http://gs.video-factory.com/review/`（`tools/video/review_server.py` :9201，gb10 Caddy `handle_path /review/*`）；dashboard 加 `--cinematic-dir` 顯示本工作樹的分鏡與旁白數據。不把成片放進 gs-video-factory 審核佇列，因為那邊「核可」會直接上傳 YouTube。

## 已知限制（未解）
- H084 第三章燈籠大特寫（約 7:45–7:55）、H055 神龕紅聯：曲面／遮擋導致追蹤失敗，保留原畫面；H097 燈籠只做失焦。根治要重生這 3 段 clip（H3 需約 37GB VRAM，這次 GPU 只剩約 6GB）。
- 「沖散」仍唸不準（CosyVoice2 8 個候選都不對；CV3 唸得對但音色不同、長度超出）。
- 發音與換字都只經過機器驗證和抽幀，尚未人耳試聽、完整播放檢查。試聽：`video_out/remaster_v2/narration_fix/ab_compare.mp3`。
- 待確認的自擬用字：「翰溪壇／翰溪庄道壇」、三清題名（玉清聖境／上清靈寶天尊／太清道德天尊）、當舖店號「大昌當舖」、桌裙橫書方向（H024/H065 左→右、H033 右→左不一致）。

## 決策紀錄
- 匾額橫書依台灣傳統由右至左（H094「翰溪壇」畫面上讀作 壇溪翰）。
- **旁白讀音**：用 CosyVoice2 同音字替換（只改送進 TTS 的文字，字幕不變），音色與 v1 一致；CosyVoice3 拼音 hotfix 只當備援（音色會變）。只重合成有問題的句子，並把長度拉回原句，時間軸不動、不需要生成新 clip。
- 「前夕」不改：台灣標準音 ㄒㄧˋ，但台灣口語普遍讀 ㄒㄧ，改了反而怪。「跡」改讀 ㄐㄧ。
- **道壇名稱**：劇本只寫「翰溪庄附近一間老舊的道壇」，畫面用字採用檢測報告自擬的一致用字表：主匾「翰溪壇」、門邊直匾「翰溪庄道壇」、水路圖「翰溪庄水路圖」、桌裙「神恩浩蕩／合境保平安」、對聯見 `docs/remaster_v2/hanzi.md`。
- **換字方法**：平面 homography 追蹤＋單張乾淨底圖逐幀 warp（時間上穩定），失敗就退回失焦；不用 ProPainter（非商用授權），也不用擴散模型 inpaint（又會生出假字）。
- **配樂**：numpy 物理合成（無授權風險、可重現），不用 MusicGen 等非商用權重。
- autopilot 的 hook 旗標是舊的（綁在其他 session），本 session 未武裝；依 autopilot 守則照常推進，不自行改旗標。
