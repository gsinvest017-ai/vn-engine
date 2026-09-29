# AI 聽音工具（listen.py）建置與驗證

日期：2026-09-25。程式：`tools/video/listen.py`、`tools/video/test_listen.py`。完整數據與模型原文：`report.json`。
**沒有任何結論經過人耳。** 「對／錯」都是拿已知真值比出來的：合成對照組參數、配樂 events.json、旁白字幕、測試渲染的 MIDI。

## 可信度（依實測）

| 層 | 工具 | 可信度 | 依據 |
|---|---|---|---|
| 節拍／速度／swing | beat_this＋自寫 | 高（有完整編制時） | jazz 測試 60.0 BPM／swing 1.97（真值 60／2:1）；EDM 140.0；自由拍標「不穩」不給數字 |
| 旋律比對 | basic-pitch＋對齊 | 分軌高／混音低 | 植入的 2 錯音＋1 漏音時間與音名全對；+30 音分量到 30.0；混音 precision 0.44（鋼琴被當成多餘音） |
| CLAP | laion_clap music ckpt | 高（排序／方向） | 同一 jazz 目標：jazz +0.605、EDM −0.181 |
| 分軌亮度／音量 | numpy | 高（逐版比較） | 植入的「小號調亮」「hi-hat 推大」都抓到；絕對門檻只用少數樣本校準 |
| Essentia 曲風 | discogs400 | 中高 | EDM→Electronic，jazz→Jazz 進前五，旁白→Spoken Word 進前五 |
| Essentia 樂器 | mtg-jamendo | 中低 | 抓不到主奏小號（0.05）、漏掉合成鐘聲 |
| Essentia 情緒 | mtg-jamendo | 低 | 分數普遍 0.05–0.15 |
| audiobox PQ | audiobox-aesthetics | 只反映技術品質 | 合成 EDM 的 PQ 8.06 高於 jazz 7.71 |
| LLM 是非題 | Qwen2.5-Omni-7B 4-bit | 中 | 28 題答對 24–26 題 |
| LLM 轉寫旁白 | Qwen2.5-Omni-7B | 高 | 前 30 秒只差一個同音字 |
| LLM 自由描述 | 同上 | 低 | 會編 BPM、調性、和弦與不存在的樂器 |
| LLM 對照目標自評 | 任一 | 不可信，已停用 | 拿 jazz 目標問 EDM，回答「完全符合」 |

`review` 以量測層為主：LLM 只做盲描述和是非題，不給它看目標。意見衝突的項目放進「需分軌或人耳確認」備註，不當成結論。

## 分不分得出好壞

- **EDM 對照＋jazz 目標**：列出 12 條不符，例如 140 BPM、偏亮、CLAP 更像 EDM、沒有小號。
- **jazz 測試渲染**：0 條不符。另有一條備註：小號 2 kHz 以上能量只占 0.5%，可能過悶。
- **植入 3 缺陷的版本**（hi-hat +22 dB、小號高頻 +15 dB、速度 ×1.2）：3 個全抓到，並給出具體 dB／BPM 修正建議。小號變亮要帶 `--baseline` 逐版比較才抓得到。

## 用法

```
python tools/video/listen.py review mix.wav --brief "<目標>" --ref trumpet.mid --stems <分軌資料夾> --baseline <上一輪 review.json> --target-bpm 60
python tools/video/listen.py describe|ask|score|melody|rhythm|licenses ...
```

環境：WSL `~/.venv-listen`。Windows 呼叫時缺套件會自動轉進 WSL。LLM 用 4-bit，約占 7 GB VRAM。

## 授權

- 可商用：Qwen2.5-Omni／Qwen2-Audio（Apache-2.0）、laion_clap（CC0）、basic-pitch（Apache-2.0）、librosa（ISC）。
- 需標示出處：audiobox-aesthetics（CC-BY-4.0）。
- 需自評：beat_this（MIT，但部分訓練資料有版權限制）。
- 非商用：**Essentia 模型是 CC BY-NC-SA 4.0**，商用要另購授權，或加 `--skip essentia` 跳過。

## 限制

- 門檻只用少數樣本校準，都是經驗值。
- CPU 退回路徑未實測。gb10 記憶體不足，放不下 Qwen3-Omni Captioner，未測。
- 只有 hi-hat、或自由速度的段落，swing 不給數字。
- 混音層級無法單獨評估某一件樂器，要帶分軌。
