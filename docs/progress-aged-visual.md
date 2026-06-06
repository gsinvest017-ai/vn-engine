# 全域古舊視覺修正進度

## 目標
1. 遊戲畫面全域古舊膠片感（掃描線 + 噪點紋理 + 暖色調 + 永久暗角）
2. Dashboard 整體改為灰階古舊風格
3. 地圖重建 — 手繪感（搖晃線條 + 墨水滲透字體 + 歲月水漬）
4. 人物邊緣軟化遮罩（rembg 後 feather alpha 邊緣）
5. 雨水多層寫實化（主滴 + 噴霧 + 動態殘影）
6. Dashboard 整合以上所有編輯功能

## 計畫 Milestone

| # | 項目 | 預期產出 |
|---|------|---------|
| M1 | 遊戲畫面全域古舊覆蓋 | grain canvas + 掃描線 + 暖色調 overlay |
| M2 | Dashboard 古舊重設計 | 灰階 + 紙張紋理 + 古銅色系 CSS |
| M3 | 地圖手繪感重建 | gen_map_realistic.py 搖晃線條版 |
| M4 | 人物邊緣軟化 | feather_edges() 重跑 6+3 張立繪 |
| M5 | 雨水寫實多層化 | effects.js 三層雨水重寫 |
| M6 | Dashboard 整合工具 | 所有處理功能加入後台 |

## M5 — 雨水三層寫實化

**完成**。重寫 `engine/js/managers/effects.js` `_startRain()`：
- Layer 1 主滴：83° 近垂直角、3-pass 動態殘影（trail）、底部落地飛濺粒子
- Layer 2 細霧噴霧：較慢、半透明、橫向飄移
- Layer 3 大氣薄霧帶：正弦震盪位置、線性漸層 canvas fill
- 各滴變化：長度 22–64px、寬 0.35–1.2px、alpha 0.18–0.73、獨立 sway
- `devRain=heavy&devWind=0.5` URL param 可直接從 engine/main.js 觸發預覽

## M6 — Dashboard 整合所有工具

**完成**。`dashboard/index.html` + `engine/js/main.js` 新增：
- **雨水預覽**子區塊：intensity select（毛毛雨/小雨/大雨/暴雨）+ 風強度滑桿 + `⛈ 預覽` 按鈕
- 按鈕開新分頁 `/engine/?devRain=heavy&devWind=0`，main.js 讀 `devRain`/`devWind` 後呼叫 `fx.setWeather()`
- 既有工具保留：灰階預覽 toggle、素材重建（地圖/narrator/diao_caidi）、特效測試（懸疑結局/章末/fade）

## Fallback 指引
- 還原任何 engine.css：`git checkout <hash> -- engine/css/engine.css`
- 重跑人物去背：`python tools/rembg_narrator.py && python tools/rembg_diao_caidi.py`
- 重建地圖：`python tools/gen_map_realistic.py`
- 雨水預覽：`http://localhost:8000/engine/?devRain=storm&devWind=0.3`
