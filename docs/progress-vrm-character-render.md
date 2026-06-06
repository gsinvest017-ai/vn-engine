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

## Fallback 指引

- 還原角色：`git checkout HEAD -- assets/characters/`
- VRM Addon 手動安裝：Blender → Edit → Preferences → Add-ons → Install → 選 .zip
- 若 VRM 模型取得失敗，可從 VRoid Hub (https://hub.vroid.com) 登入下載免費模型
  存至 `C:\Users\User\vn-engine\tools\vrm\` 再重新跑 M2
