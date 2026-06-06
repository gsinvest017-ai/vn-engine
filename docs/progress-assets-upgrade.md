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

**完成時間**：本次作業

### 完成內容

**`assets/manifest.json`** — 音訊狀態更新：
- 所有 10 個音訊槽位（3 BGM + 7 SFX）`status` 由 `"missing"` → `"procedural"`
- 新增 `procedural_fn` 欄位標注對應的合成函式名稱
- 新增頂層 `_note` 說明程序式 fallback 機制

**`docs/asset-sources.md`** — 新建資源指引：
- 每個音訊 ID 對應的 Freesound / OpenGameArt / Pixabay / Mixkit 搜尋關鍵字
- 授權類型說明（CC0 / CC-BY / Pixabay / Mixkit）
- DIY Audacity 合成替代方案（market_closing、oar_creak、power_failure）
- 字型資源：Noto Serif TC、Source Han Serif（OFL 1.1）+ CSS 嵌入範例

---

## M5 — 角色說話高亮 + Ctrl 快進對話

**Commit**：e7fa720

### 問題背景
- `_doDialogue()` 已有 `@char show=...` 命令支援立繪顯示，但說話時不會高亮說話者（CharManager 的 `highlight()` 從未被呼叫）
- `_doNarration()` 也未呼叫 `clearHighlight()`，導致從對話切換到旁白時高亮殘留
- 沒有持續快進功能（只有 `»` 切換式 skipMode，無法 hold 長按連發）

### 修改內容

**`engine/js/core/engine.js`**：
- `_doDialogue()`: 角色未 display 時自動以 `center` 位置 + `normal` 表情呼叫 `show()`；隨後呼叫 `chars.highlight(cmd.character)` 高亮說話者
- `_doNarration()`: 文字顯示前先呼叫 `chars.clearHighlight()` 恢復所有角色等亮度
- `_bindInput()`:
  - `advance()` 判斷順序修正：先 `isTyping()` 再 `_inputResolve`（原本順序相反）
  - 新增 Ctrl 長按快進：`keydown ControlLeft/Right` 啟動 80ms 定時連發（skip + advance），`keyup` 清除計時器

**`engine/js/managers/character.js`**：
- `highlight()`: 說話者 slot 同時 add `.speaking` / remove `.dimmed`；其他 slot add `.dimmed` / remove `.speaking`
- `clearHighlight()`: 同時移除 `.dimmed` 和 `.speaking`

**`engine/css/engine.css`**：
- `.char-sprite`: transition 加入 `transform 250ms ease, filter 250ms ease`
- 新增 `.char-slot.speaking .char-sprite`: `scale(1.03) translateY(-4px)` + `brightness(1.08)` — 說話者輕微放大前移

**`engine/index.html`**：
- `#hud-skip` title 補充 `「或長按 Ctrl 快進對話」` 說明

---

## Fallback 指引

若需回滾至某 milestone：
- 所有原始 SVG 佔位已由 git 歷史保存
- `git log --oneline` 找到 `M1:` / `M2:` 前的 commit，`git checkout <hash> -- assets/` 可還原指定資產
- 音效引擎可完全移除：刪除 `engine/js/audio/procedural.js`，還原 `engine/js/managers/audio.js` 至前一 commit 即可
- M3 角色立繪若需還原：`git checkout f4617ce -- assets/characters/`
