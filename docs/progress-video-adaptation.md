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
- M1：工具鏈（client / parser / prompts / renderer / 測試）
- M2：第一章 30 秒試片

## Fallback
- ComfyUI 拒收 prompt：先 `curl 127.0.0.1:8188/object_info/MiniMaxH3ImageToVideo` 確認節點存在（版本 >= v0.37）
- VRAM 不足：`--res low`；Ollama 常駐的 qwen2.5vl 佔 ~8GB，必要時 `ollama stop qwen2.5vl:7b`
- 單段 clip 不滿意：刪 `video_out/clips/<tag>.mp4` 後重跑，或換 `--seed`
