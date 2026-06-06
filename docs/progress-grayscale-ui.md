# 灰階場景 + 古舊 UI + 懸疑結局進度

## 目標
1. 背景場景素材全部灰階，與人物立繪黑白風格一致
2. 地圖素材（city_historical）改為更寫實的繪製風格
3. 遊戲 UI 元件加入古舊紙張質感，符合台中舊城偵探劇情主題
4. 劇情結束加入懸疑 fade-out 特效（vignette → 人物淡出 → 緩慢黑幕）
5. 後台 Dashboard 加入素材工具面板與特效測試按鈕

## 計畫 Milestone

| # | 項目 | 預期產出 |
|---|------|---------|
| M1 | 背景灰階 CSS + 寫實地圖生成 | `.bg-image` CSS filter + `city_historical.png` |
| M2 | UI 古舊感 CSS | textbox/speaker/chapter card 紙張質感更新 |
| M3 | 懸疑 fade-out | `suspenseEnd()` effect + `@suspense_end` VNScript 指令 |
| M4 | Dashboard 工具面板 | 灰階預覽切換 + 特效測試按鈕 + serve.py POST API |

## Fallback 指引
- 還原 engine.css：`git checkout <hash> -- engine/css/engine.css`
- 還原地圖：`git checkout <hash> -- assets/backgrounds/city_historical.png`
- 重建地圖：`python tools/gen_map_realistic.py`
