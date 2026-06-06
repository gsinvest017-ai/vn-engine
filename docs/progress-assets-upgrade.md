# 資產升級進度 — 暗渠之書

## 目標
以開源免費技術（增強 SVG 藝術 + Web Audio API 程序式音效）大幅提升「暗渠之書」的視覺與聽覺品質，使畫面更貼近台中舊城懸疑氛圍主題。不依賴外部下載，全程可離線運作。

## 計畫 Milestone

| #  | 項目                         | 預期產出                                          |
|----|------------------------------|---------------------------------------------------|
| M1 | 重繪六張背景 SVG              | 高細節氛圍藝術版本替換佔位用原始 SVG             |
| M2 | Web Audio 程序式音效引擎      | `engine/js/audio/procedural.js` + AudioManager 整合 |
| M3 | 強化角色立繪 SVG              | narrator 全表情 + diao_caidi 全表情細節提升      |
| M4 | 素材資源指引 + manifest 更新  | `docs/asset-sources.md` + manifest 狀態更新      |

## 進度日誌

## M1 — 六張背景 SVG 重繪

**完成時間**：本次作業  
**Commit**：f4617ce（M2 commit 包含 M1 成果）

### 完成內容

全部六張背景 SVG 從佔位水準提升至高細節氛圍藝術：

| 背景             | 主要技術                                                              |
|------------------|-----------------------------------------------------------------------|
| `old_city_dusk`  | 多層漸層天空、建築剪影、電線桿垂線（懸鏈線）、街燈光暈、雨條、積水反光 |
| `shrine_interior`| 拱型神壇、香爐煙霧（SVG path + blur）、線香火光、燈籠、重暈影      |
| `city_historical`| feTurbulence 紙質紋理、褪色斑點、毛筆水路線（feDisplacementMap）、漢字標記 |
| `archive_room`   | 書架書脊細節、桌燈梯形光錐、塵埃光點、舊文件、深色 noir 暈影        |
| `shrine_entrance_night` | 近全黑天空、傳統牌樓剪影、停電建築（無亮窗）、7-11 綠光暈、積水反光、密集雨線 |
| `underground_river`     | 6 層透視拱形磚隧道、磷光藍綠水面、feDisplacementMap 水波、舊木船、磷光牆斑 |

### 技術重點
- 所有背景使用純 SVG（無外部依賴）
- SVG filter (`feTurbulence`, `feGaussianBlur`, `feDisplacementMap`, `feBlend`) 產生有機紋理
- 多層 `radialGradient` / `linearGradient` 配合 vignette 遮罩產生電影感暗角

---

## M2 — Web Audio 程序式音效引擎

**完成時間**：本次作業  
**Commit**：f4617ce

### 完成內容

**`engine/js/audio/procedural.js`**：全新 `ProceduralAudio` 類別
- `createCityAmbient()` — 60/120/180 Hz 城市嗡嗡聲 + 粉紅噪音交通底噪 + LFO 呼吸感
- `createShrineAmbient()` — 55 Hz 基音 + 4 泛音 + 音高 LFO 搖擺 + 室內空氣感
- `createRainNight()` — 三層雨聲（中/高/低頻帶通濾波）+ 雷聲次低音 + 風嚎 LFO
- `playSfx()` — 7 種音效程序式合成（市場收攤、踩水、紙聲、船槳、水流、暴雨、停電）

**`engine/js/managers/audio.js`** 整合：
- 優先嘗試載入 `.ogg` 音訊檔
- 檔案缺失時自動 fallback 至 `ProceduralAudio` 程序式生成
- 支援 BGM 淡入/淡出、音量控制、多 SFX 同時播放

### 技術重點
- Paul Kellett 粉紅噪音算法（低品質但 CPU 極省）
- Web Audio API 節點圖：白/粉紅噪音 → BPF/LPF/HPF 濾波 → GainNode → Destination
- LFO（`createOscillator`）調製增益節點產生動態音效

---

## M3 — 角色立繪 SVG 強化

**完成時間**：本次作業

### 完成內容

全部 9 張角色立繪（narrator × 6 + diao_caidi × 3）加入氛圍光照提升：

**新增元素**（每張 SVG 均加）：
- `rim_r` 漸層 — 右側暖琥珀色 rim light（模擬蠟燭/街燈方向光）
- `shadow_l` 漸層 — 左側冷藍紫環境暗影（夜空填充光）
- 臉部右側新月形輝光（warm face crescent）
- 服裝折痕線（narrator 長風衣、diao_caidi 休閒衫）

**各表情客製化**：
- `tired` — 加深眼袋陰影、上眼瞼更厚重
- `troubled` — 眉間皺紋線更明顯、舉手近臉的手掌有額外光暈
- `silent` — 頭頂加深陰影（低頭朝下、遠離頂光）
- `thoughtful` — 下巴處手掌 rim 光、眉毛不對稱更明顯
- `reading` — 文件增加 doc_glow 暖光漸層、下巴反光（文件反射）
- `diao_caidi/questioning` — 舉起的手掌（掌心朝上）強烈 rim 光
- `diao_caidi/shocked` — 臉色淡化（驚嚇蒼白）、手臂張開 rim 強化、牙齒暗示

---

## M4 — 素材資源指引 + manifest 更新

（見下方 M4 完成後追加）

## Fallback 指引

若需回滾至某 milestone：
- 所有原始 SVG 佔位已由 git 歷史保存
- `git log --oneline` 找到 `M1:` / `M2:` 前的 commit，`git checkout <hash> -- assets/` 可還原指定資產
- 音效引擎可完全移除：刪除 `engine/js/audio/procedural.js`，還原 `engine/js/managers/audio.js` 至前一 commit 即可
- M3 角色立繪若需還原：`git checkout f4617ce -- assets/characters/`
