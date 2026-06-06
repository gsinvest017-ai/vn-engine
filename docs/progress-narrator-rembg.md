# narrator 照片去背立繪進度

## 目標
將 tools/vrm/narrator.jpg（老男人黑白寫實攝影）去背處理後，
製作 6 個表情變體（色彩分級模擬情緒差異），輸出為 400×800 透明背景 PNG
供 VN 引擎使用。

## 計畫 Milestone

| # | 項目 | 預期產出 |
|---|------|---------|
| M1 | rembg 去背 + 裁切縮放 + 基礎立繪 | `narrator/normal.png` 去背版本 |
| M2 | 6 個色彩分級表情變體 | normal/tired/troubled/silent/thoughtful/reading |
| M3 | 確認品質 + commit | 全部 6 張 PNG commit |

## 進度日誌

### M1+M2 — rembg 去背 + 6 表情輸出

來源：`tools/vrm/narrator.jpg`（黑白寫實老男人攝影，3439×3633px）

**處理流程**（`tools/rembg_narrator.py`）：
1. rembg u2net 模型去背 → 主體邊框裁切（含 30px padding）
2. 等比縮放至 400×405，底部置中貼於 400×800 透明畫布
3. 6 個 PIL 色彩分級表情變體：

| 表情 | brightness | contrast | 色調 | shadow crush |
|------|-----------|---------|------|-------------|
| normal | 1.00 | 1.00 | 無 | 0 |
| tired | 0.80 | 0.92 | 暖琥珀 | 0.22 |
| troubled | 0.86 | 1.30 | 冷藍 | 0.28 |
| silent | 0.60 | 1.18 | 深藍灰 | 0.42 |
| thoughtful | 1.06 | 1.06 | 暖米 | 0 |
| reading | 0.90 | 1.10 | 暖琥珀 | 0.12 |

**品質評估**：
- 去背品質：優（rembg u2net，毛髮邊緣清晰）
- 表情差異：明顯（silent 暗沉、troubled 高對比、thoughtful 明亮）
- 風格契合度：極高（黑白寫實老人 ↔ 台中舊城 film noir 主題完美搭配）

## Fallback 指引
- 還原舊立繪（VRM 渲染版）：`git checkout 0bb4bdc -- assets/characters/narrator/`
- 重新跑去背：`python tools/rembg_narrator.py`
- 替換來源照片：將新 JPG 存至 `tools/vrm/narrator.jpg` 後重跑腳本
