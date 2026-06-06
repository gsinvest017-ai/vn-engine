# 素材資源指引 — 暗渠之書

所有音訊槽位目前均已由 Web Audio API 程序式合成覆蓋（`engine/js/audio/procedural.js`），遊戲可完整運行。若未來想以真實錄音替換，下面列出對應每個 ID 的免費授權來源搜尋建議。

> **放置方式**：下載後轉換為 `.ogg` 格式，放入 `assets/audio/bgm/` 或 `assets/audio/sfx/`，引擎會優先讀取檔案，程序式版本自動停用。

---

## BGM（背景音樂）

### `ambient_old_city.ogg`

**描述**：台中舊城區夜晚環境音，遠方車聲、鐵皮建築、潮濕底噪

**推薦來源**：

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `taiwan street night ambient` / `asia city night rain` | CC0 / CC-BY |
| OpenGameArt.org | `urban ambient loop` / `city night soundscape` | CC0 |
| Sonniss GDC Pack | 每年 GDC 釋出免費 SFX 包，含 urban ambient | CC0 |

**DIY 合成替代**：在 Audacity 混合以下免費素材：
- CC0 白噪音底層（−30 dB）
- 低頻 hum（60 Hz 正弦波）
- 偶發遠方車聲（Freesound: "distant traffic"）

---

### `ambient_shrine.ogg`

**描述**：廟宇/神壇室內氛圍，燃香靜謐，低頻 drone

**推薦來源**：

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `temple ambient` / `incense drone` / `asia temple interior` | CC0 / CC-BY |
| Incompetech (Kevin MacLeod) | `meditation` / `dark ambient` 類別 | CC-BY 4.0 |
| Pixabay Music | `meditation ambient` / `temple bells` | Pixabay 授權（免費商用） |

**注意**：搜尋 `temple` 容易找到印度/東南亞廟宇，台灣道教氛圍更接近低沉 drone + 偶發木魚聲。

---

### `ambient_rain_night.ogg`

**描述**：城市深夜暴雨，雷聲遠，電氣感

**推薦來源**：

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `heavy rain night urban` / `thunderstorm city` | CC0 / CC-BY |
| OpenGameArt.org | `rain loop` / `storm ambient` | CC0 |
| Pixabay | `heavy rain` / `thunderstorm` | Pixabay 授權 |

---

## SFX（音效）

### `market_closing.ogg`

**描述**：鐵捲門拉下金屬聲

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `metal shutter close` / `rolling shutter` / `gate metal` | CC0 / CC-BY |

---

### `footsteps_puddle.ogg`

**描述**：踩積水一聲，塑膠拖鞋質感

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `footstep splash water` / `puddle step` / `wet footstep` | CC0 |
| Mixkit.co | `water splash footstep` | 免費（Mixkit 授權） |

---

### `paper_rustle.ogg`

**描述**：翻閱舊紙張，1-3 聲

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `paper rustle` / `document flip` / `paper turn` | CC0 |
| Mixkit.co | `paper flip` | 免費 |

---

### `oar_creak.ogg`

**描述**：木製船槳划水，緩慢，地下洞穴感

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `wooden oar water` / `rowing boat creak` / `oar splash` | CC0 / CC-BY |

**提示**：可找 `rowboat oar creak` 後用 Audacity 加 heavy reverb（Room size: Large, Decay: 4s）模擬地下空間迴響。

---

### `water_distant.ogg`

**描述**：遙遠地下水流，迴響循環

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `distant water flow` / `underground water` / `cave water stream` | CC0 |
| OpenGameArt.org | `water loop` / `underground ambient` | CC0 |

---

### `rain_heavy.ogg`

**描述**：暴雨打在鐵皮屋頂，密集，建築共鳴

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `rain metal roof` / `heavy rain corrugated` / `downpour tin roof` | CC0 / CC-BY |
| Pixabay | `rain roof` / `heavy rain loop` | 免費 |

---

### `power_failure.ogg`

**描述**：停電瞬間，電器嗡嗡聲消失 + 電氣切斷聲

| 來源 | 搜尋關鍵字 | 授權 |
|------|-----------|------|
| Freesound.org | `power outage` / `electricity cut` / `lights off hum stop` | CC0 / CC-BY |
| Mixkit.co | `power off` / `electrical shutdown` | 免費 |

**DIY 方式**：錄製電腦/冷氣運轉聲，突然靜音，後段加一聲低頻 click（120 Hz 短脈衝 10ms）。

---

## 授權注意事項

- **CC0（Public Domain）**：可直接使用，無需署名，商用免費
- **CC-BY 4.0**：可使用，需在遊戲 credits 中署名原作者
- **Pixabay / Mixkit 授權**：平台專屬免費授權，可商用，無需署名
- **Kevin MacLeod (Incompetech)**：CC-BY 4.0，通常需要 "Music by Kevin MacLeod (incompetech.com)" 字樣

### 建議 credits 格式

在遊戲的 About 或 Credits 頁面加入：

```
音效素材：
- [素材名稱] by [作者] (Freesound.org) — CC0 / CC-BY 4.0
```

---

## 字型

遊戲目前使用系統字型（`"Noto Serif TC", "Microsoft JhengHei", serif`）。
若需嵌入授權字型：

| 字型 | 用途 | 來源 | 授權 |
|------|------|------|------|
| Noto Serif TC | 正文繁體中文 | Google Fonts | OFL 1.1（免費商用） |
| Noto Sans TC  | UI 標籤      | Google Fonts | OFL 1.1 |
| Source Han Serif (思源宋體) | 高品質正文 | Adobe / Google | OFL 1.1 |

**下載方式**：`https://fonts.google.com/noto/specimen/Noto+Serif+TC`，下載後放入 `assets/fonts/`，在 `engine/css/engine.css` 加入 `@font-face`。

---

## 字型嵌入範例

```css
@font-face {
  font-family: 'Noto Serif TC';
  src: url('../../assets/fonts/NotoSerifTC-Regular.otf') format('opentype');
  font-weight: 400;
  font-display: swap;
}
```

然後在 CSS 變數中使用：

```css
:root {
  --font-main: 'Noto Serif TC', 'Microsoft JhengHei', serif;
}
```
