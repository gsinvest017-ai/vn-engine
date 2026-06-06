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

## 進度日誌

### M1 — 背景灰階 + 寫實地圖 — commit e2d7b1a
- `.bg-image` CSS filter: `grayscale(90%) contrast(1.08) brightness(0.88)`
- `tools/gen_map_realistic.py`：PIL 生成 1920×1080 灰階地圖（噪點紙底 + 水漬 + 街道格 + 水路 + 地標 + 漢字標注）
- `assets/backgrounds/city_historical.png` 更新

### M2 — UI 古舊感 — commit 5677549
- textbox：水漬 radial-gradient + 纖維紋理 repeating-linear-gradient + 四角 amber 裝飾邊框
- speaker-name：倒梯形印章感（skewX-1deg + 光暈 box-shadow）
- chapter-card：斜線花紋背景 + 橫線 glow 擴展動畫
- choice-box / hud-btn / overlay-panel：皮革 + 古銅金屬底色
- 新增 #fx-suspense-msg、.fading-out、.vignette-suspense CSS

### M3 — 懸疑 fade-out — commit 7a42fb1
- `EffectsManager.suspenseEnd()`: vignette pulse → textbox fading-out → 字幕 → 角色淡出下移 → 緩慢 fade to black
- `@suspense_end message="..." duration=5200` VNScript 指令
- `engine.js _doSuspenseEnd()` + `clearAll()` 還原 suspense 狀態

### M4 — Dashboard 工具面板 — commit (本次)
- dashboard: TOOLS panel（灰階預覽切換、素材重建按鈕、特效測試按鈕）
- serve.py: `do_POST` + `/api/run-tool` whitelist endpoint（gen_map / rembg_narrator / rembg_diao_caidi）
- main.js: `?devEffect=suspense_end|chapter_end|fade_out` URL param 特效即時測試

## Fallback 指引
- 還原 engine.css：`git checkout <hash> -- engine/css/engine.css`
- 還原地圖：`git checkout <hash> -- assets/backgrounds/city_historical.png`
- 重建地圖：`python tools/gen_map_realistic.py`
