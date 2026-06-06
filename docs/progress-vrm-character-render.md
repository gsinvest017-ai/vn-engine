# VRM 角色立繪渲染進度

## 目標
透過 Blender MCP 將 VRoid Hub 的 VRM 格式角色模型匯入 Blender，
以 VN 立繪規格（400×800 透明背景 PNG）批次渲染 narrator（6 表情）
與 diao_caidi（3 表情），替換現有 SVG 立繪，提升角色視覺品質。

## 計畫 Milestone

| # | 項目 | 預期產出 |
|---|------|---------|
| M1 | 安裝 VRM Addon for Blender | Blender 可 import .vrm 格式 |
| M2 | 取得 VRM 角色模型 | 至少一個可用 .vrm 檔案 |
| M3 | Blender MCP 匯入 + 設定渲染場景 | 角色在 Blender 中，打光/相機就位 |
| M4 | 渲染 narrator 6 個表情 PNG | `assets/characters/narrator/*.png` × 6 |
| M5 | 渲染 diao_caidi 3 個表情 PNG + 更新引擎 | 全部 PNG 就位，引擎切換為 PNG 優先 |

## 進度日誌

## M1 — VRM Addon 安裝
- 下載 `VRM_Addon_for_Blender-4_2_2.zip`（1.5MB）
- 解壓縮至 `%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\VRM_Addon_for_Blender-release\`
- Blender MCP 執行 `bpy.ops.preferences.addon_enable(module='VRM_Addon_for_Blender-release')` 成功
- `import_scene.vrm` operator 已可用

## M2 — 取得 VRM 角色模型
- 系統無既有 VRM 檔案，VRoid Studio 未安裝
- 從 `vrm-c/vrm-specification` 官方倉庫下載免費樣本 Seed-san.vrm（10.4MB）
- 存至 `tools/vrm/Seed-san.vrm`
- Seed-san 是動漫風格女性角色（VRM 1.0 格式），授權：CC0
- **決策**：以 Seed-san 驗證渲染流程；用戶可在 VRoid Hub 登入後下載男性角色替換

## M3 — Blender 匯入 + 渲染場景設定
- Seed-san.vrm 匯入成功，Armature + 6 個 mesh（head/hair/wear/robo_arm 等）
- 三點打光：Key 光（強度 5W，右前方）、Fill 光（1W，左側）、Rim 光（3W，後方輪廓）
- VN 立繪相機：85mm 鏡頭，初始全身鏡頭，後調整為上半身/臉部特寫
- Cycles 引擎、256 samples + Denoising、RGBA 透明背景
- 頭部 Mesh 有 44 個 Shape Keys 可控制表情

## M4 — narrator 6 個表情 PNG
- 相機調整為臉+上胸特寫（z=1.35，y=-1.5，85mm）
- 全部以 Seed-san.vrm Shape Keys 組合渲染：
  - `normal`：預設中性
  - `tired`：eye_close(0.6) + face_sad(0.5) + eye_brow_down(0.5) + lip_down(0.3)
  - `troubled`：face_angry(0.6) + eye_brow_down(0.7) + eye_angry(0.6) + mouth_short(0.5)
  - `silent`：face_relax(0.6) + look_down(0.75) + eye_close(0.25)
  - `thoughtful`：eye_brow_up_R(0.9) + eye_brow_down_L(0.3) + look_right(0.45)
  - `reading`：look_down(0.65) + face_relax(0.5) + eye_close(0.15)
- 產出：`assets/characters/narrator/*.png` × 6（約 362KB/張）

## M5 — diao_caidi 3 個表情 PNG + 引擎更新
- diao_caidi 使用同一 Seed-san 模型，不同 Shape Key 組合渲染：
  - `normal`：face_happy(0.7) + cheek(0.5) + eye_smile(0.5) + lip_up(0.3)
  - `questioning`：eye_brow_up_L(0.95) + eye_brow_down_R(0.35) + look_right(0.45) + mouse_open(0.25)
  - `shocked`：face_surprise(1.0) + eye_brow_up(0.85) + mouse_open(1.0) + eye_black_big(0.6)
- 產出：`assets/characters/diao_caidi/*.png` × 3
- `engine/js/managers/character.js`：`spriteUrl()` 預設改為 `.png`，onerror fallback 改為 `.svg`
- `assets/manifest.json`：9 個角色表情 entry 全部更新為 `.png` + source 說明

## Fallback 指引

- 還原角色：`git checkout HEAD -- assets/characters/`
- VRM Addon 手動安裝：Blender → Edit → Preferences → Add-ons → Install → 選 .zip
- 若 VRM 模型取得失敗，可從 VRoid Hub (https://hub.vroid.com) 登入下載免費模型
  存至 `C:\Users\User\vn-engine\tools\vrm\` 再重新跑 M2
