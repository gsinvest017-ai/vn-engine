# 進度：《暗渠之書》影片版（ComfyUI MiniMax H3）

## 目標
用老闆給的 AIGF-V2 ComfyUI 工作流（MiniMax H3 圖／文生影片 + 原生環境音），把 `scripts/taichung-anqu/*.vns` 自動轉成有字幕的影片版。先出第一章開頭約 30 秒試片，確認品質與速度後再跑全三章。

## 架構
```
.vns ──vns_shots.parse──▶ Shot（背景/天氣/效果/音效/字幕行/時長）
      ──prompts.build──▶ 英文提示詞（每個 clip 一份）
      ──comfy_client──▶ ComfyUI /prompt（API 格式，攤平 AIGF-V2 subgraph）
      ──render.assemble──▶ ffmpeg：裁切 → 淡入淡出 → concat → ASS 字幕燒錄 → loudnorm
```
- `tools/video/comfy_client.py`：H3 API graph、上傳圖、輪詢、下載
- `tools/video/vns_shots.py`：劇本解析、時長估算（6 字/秒）、字幕切句
- `tools/video/prompts.py`：場景 → 提示詞對照表（每個背景一組）
- `tools/video/render.py`：CLI（`--plan` / `--chapters` / `--max-seconds` / `--res`）
- `tools/video/test_video_tools.py`：9 個單元測試（不需 ComfyUI）

## 環境前置（本機已完成）
- ComfyUI `C:\Users\User\ComfyUI` 從 v0.24.0 更新到 v0.37.0（v0.24 沒有 `MiniMaxH3ImageToVideo`）
- 模型從 `Downloads\AIGF-V2.7z` 解出並放進：
  - `models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors`（21GB）
  - `models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`（15.7GB）
  - `models/vae/minimax_h3_{video_vae_fp16,audio_vae_fp32}.safetensors`
  - `models/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`
- 啟動：`venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188`

## 決策
| 決策 | 理由 |
|---|---|
| 大部分場景用文生影片（t2v），不用遊戲背景圖當首幀 | 遊戲背景多為歐洲街景 stock 圖（石板路、磚牆），與台中舊城不符；實測提示詞能把畫面拉成台灣巷弄（機車、鐵窗） |
| `city_historical`（手繪水路圖）用原圖當首幀（i2v） | 那張是專為遊戲畫的地圖，保留 |
| 長鏡頭拆成 ≤10 秒的 clip，後一段以前一段最後一幀當首幀 | H3 訓練長度約 5–15 秒；接首幀讓鏡頭連續 |
| 不放角色立繪 | 旁白立繪是真人照片，做成動態臉有肖像權風險；影片版走「無人氛圍鏡頭 + 字幕」 |
| 先只上字幕、不配旁白語音 | 使用者尚未決定；字幕版可直接加 CosyVoice 旁白軌，不影響畫面 |
| 預設 8-step turbo LoRA、生成 1056×608、輸出放大到 1080p | 速度與品質折衷（864×480 × 5 秒實測 80 秒含載模型） |
| 提示詞一律英文、禁止畫面文字 | AIGF 教學實測英文效果較好；字幕由 ffmpeg 燒，避免模型亂生中文字 |

## 進度日誌
- M1 `5b9e598`：工具鏈（client / parser / prompts / renderer / 測試）
- M2：第一章 30 秒試片完成 → `video_out/trial_ch1.mp4`（31.4 秒、1920×1080、H.264 + AAC）
  - 4 段 clip：黃昏舊城 3 段（t2v + 2 段續接 i2v）＋ 道壇內 1 段；每段 9 秒約 220–235 秒、5 秒約 100 秒（1056×608、turbo 8 步）
  - 修正：ASS `Dialogue` 少一個空的 Effect 欄，`\fad(a,b)` 的逗號被當欄位切開，字幕漏出 `500)}`；補欄位並加測試守住
  - 調整：H3 產出偏亮、像白天 → 組裝時統一套 `GRADE`（降飽和、壓中間調、暗角），並在提示詞加 late dusk / underexposed
  - 音量：H3 原生環境音約 -50 dB，loudnorm 後 mean -24 dB

## 估算：全三章
`render.py --plan` → 7 shots / 35 clips / 約 322 秒（5.4 分鐘）。依試片速度約 2–2.5 小時 GPU 時間。
```
python tools/video/render.py --name anqu_full        # 已生成的 clip 會快取，可中斷續跑
```

## 已知限制 / 後續
- 模型偶爾生出亂碼中文招牌（畫面背景文字），屬模型限制；可加 `no readable signage` 或挑 seed 重跑該段
- 劇情人物（旁白、刁才弟）目前不入鏡；若要角色，需先準備非真人肖像的立繪再走 i2v
- 旁白配音未做：可用 CosyVoice2 依 ASS 時間軸產生旁白軌，再混進 assemble

## Fallback
- ComfyUI 拒收 prompt：先 `curl 127.0.0.1:8188/object_info/MiniMaxH3ImageToVideo` 確認節點存在（版本 >= v0.37）
- VRAM 不足：`--res low`；Ollama 常駐的 qwen2.5vl 佔 ~8GB，必要時 `ollama stop qwen2.5vl:7b`
- 單段 clip 不滿意：刪 `video_out/clips/<tag>.mp4` 後重跑，或換 `--seed`

## 長鏡頭換角度（2026-09-22）
道壇那場戲一段 68 秒，原本 7 段 clip 全是同一個固定角度接續生成，畫面太悶，而且接續會越來越亮。
改成：4 段以上的 shot，第 2 段起每段換一個角度（香爐特寫、壁癌、雨窗、卷宗、日光燈、神像…，`prompts.ANGLES`）。

試過三種做法，逐幀看結果：
| 做法 | 結果 |
|---|---|
| `MiniMaxH3ReferenceToVideo`，第一段畫面當 `<Picture 1>` | ✗ 整段黏在參考圖構圖上，第 4 秒仍是全景，只是慢慢推進 |
| 同上但不接 video VAE（參考圖只進 text encoder） | ✗ 第一幀仍是參考圖構圖 |
| 純 t2v + 鏡頭描述 | ✓ 開頭仍會先出全景，但約 2.5 秒就到指定特寫 |

→ 採用 t2v，多生 `CUT_HEAD`=2.5 秒、組裝時 `-ss 2.5` 剪掉。成本多約 25%。
ReferenceToVideo 只留給「重回同一場景的第一段全景」（第二、三場道壇戲），這時黏著原構圖正好讓房間一致。
快取後綴：`_t` = 換角度 t2v、`_c` = 重訪參考圖、無後綴 = 一般／接續。

## 全三章成片（2026-09-22）
`video_out/anqu_full.mp4`：5 分 22 秒、1920×1080、188MB；35 段 clip（31 段新生成，每段約 5 分鐘，含換角度多生的 2.5 秒）。
- 音量：mean -24.4 dB、peak -2.0 dB
- 逐秒亮度（YAVG）：全片多在 15–60，第三章停電段落壓到 15 左右；唯一尖峰是 1:34 手繪水路圖（~104），灰白舊紙、有淡入，當作閃回保留
- 已知限制：換角度段落各自 t2v，道壇細節（窗戶位置、神像張數）段與段之間略有差異；特寫多在段落後半才推近
