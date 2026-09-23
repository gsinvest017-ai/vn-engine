# 局部修正工具調研（2026-09-23）

測試產物都在 `video_out/remaster_v2/tools_survey/`（未進版控，5.6GB，含模型）。

| 需求 | 首選 | 備選 | 狀態 |
|---|---|---|---|
| 旁白改讀音 | CosyVoice2 **同音字替換**（只改送進 TTS 的文字，字幕不變）：模型相同，音色一致 | Fun-CosyVoice3-0.5B 拼音 hotfix（`那袋[l][è][s][è]`，prompt 前要加 `You are a helpful assistant.<\|endofprompt\|>`）；F5-TTS speech_edit ＋ pypinyin 台灣詞典 | CV2 沒有拼音 token（已查原始碼並實測，會逐字唸出括號內容）；CV3 hotfix 已實測能改動讀音，聲調對不對仍需人耳確認；CV3 音色與 CV2 有差異 |
| 讀音資料 | 萌典 API `moedict.tw/uni/<詞>`、g0v/moedict-data | pypinyin `load_phrases_dict` 蓋掉讀音（已驗證） | 已驗證 |
| 慢動作補幀 | rife-ncnn-vulkan 20221029（Windows Vulkan 版，不受 sm_120 影響） | minterpolate mci、Practical-RIFE、GIMM-VFI | 已實測：48 幀→120 幀 5.9 秒；mci 要 18.2 秒 |
| 段落銜接 | ffmpeg xfade＋acrossfade、依場景曝光匹配 | color-matcher（GPL-3.0） | — |
| 畫面換字 | PaddleOCR 偵測 → 平面 homography 追蹤 → 單張乾淨底圖＋真字 → 逐幀 warp 貼回 | H3 Fun ControlNet mask inpaint（要另下載 2.3GB patch，擴散模型可能又生出假字）、Wan2.1 VACE、ProPainter（非商用授權） | cv2.inpaint 單幀已驗證 |
| 配樂 | numpy/scipy 物理合成（無授權問題、可精確控制稀疏度、可重現） | Stable Audio Open 做單音取樣、ACE-Step 1.5（MIT） | 合成版已產出 |

不推薦：MusicGen（權重 CC-BY-NC）、AudioLDM2（非商用、已停更）、ProPainter/DiffuEraser 用於可能商用的成片（S-Lab 非商用授權）。
