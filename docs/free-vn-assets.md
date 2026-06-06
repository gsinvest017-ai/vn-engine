# 免費開源 VN 遊戲素材指引

本文件提供「暗渠之書」可直接下載使用的免費合法資源，
所有資源皆符合 CC0 / CC-BY / 免費商用授權。

---

## 角色立繪 (Character Sprites)

### 替換方式
將下載的 PNG 放入 `assets/characters/<角色id>/<表情>.png`。
引擎會自動以 PNG 覆蓋同名 SVG（SVG 優先順序低於 PNG 實際上不是，CharManager 直接用 `.svg`）。

實際使用：將 PNG 重命名為 SVG 同名，或修改 `engine/js/managers/character.js` 的 `spriteUrl()` 改用 `.png` 副檔名。

### 推薦素材來源

| 來源 | 內容 | 授權 | URL |
|------|------|------|-----|
| **Sutemo's Character Pack** (itch.io) | 9 個免費 VN 風格人物，含多表情，日系風格 | 免費商用 | https://sutemo.itch.io/female-character |
| **FVN Free Characters** (itch.io) | 5 角色 × 6 表情，含透明背景 PNG | CC0 | https://fvn.itch.io/fvn-free-characters |
| **Seliel the Shaper** (itch.io) | 多款 VN 角色資產，部分免費 | 各異 | https://seliel-the-shaper.itch.io/ |
| **OpenGameArt: VN Characters** | 搜尋 "visual novel character" 過濾 CC0 | CC0/CC-BY | https://opengameart.org/art-search?keys=visual+novel+character |
| **VN Character Generator** | 線上生成 VN 立繪（部分模板免費） | 各異 | https://picrew.me |

> **注意**：台灣/亞裔外觀且符合懷舊黑色電影風格的立繪極少，目前最佳方案是使用本 repo 的 SVG 立繪（已重繪版），或委託插畫師製作。

---

## 背景圖 (Backgrounds)

### 替換方式
放入 `assets/backgrounds/<bg_id>.jpg`（或 `.png`, `.webp`）。
引擎優先使用有副檔名的圖，SVG 為 fallback。

### 推薦素材來源

| 來源 | 內容 | 授權 | URL |
|------|------|------|-----|
| **OpenGameArt: VN Backgrounds** | 多款 VN 風格場景（含夜景、廟宇等） | CC0/CC-BY | https://opengameart.org/art-search?keys=visual+novel+background |
| **Unsplash** | 高品質攝影，可用 Canva/GIMP 加濾鏡 | Unsplash License | https://unsplash.com/s/photos/taiwan-night |
| **Pixabay** | 免費可商用圖片，搜尋「Taiwan temple night」 | Pixabay License | https://pixabay.com |
| **Kenney Assets** | 像素/扁平風格場景（可能不符合本遊戲風格） | CC0 | https://kenney.nl/assets |

### 建議工作流程（免費）
1. 從 Unsplash 下載台灣廟宇/舊城區夜景照片
2. 用 **GIMP**（免費）套用：
   - 顏色 → 色相/飽和度（降低飽和度 -60）
   - 顏色 → 亮度/對比度（降低亮度 -20, 提高對比 +30）
   - 濾鏡 → 扭曲 → 鏡頭校正（加暗角）
3. 存為 `backgrounds/<bg_id>.jpg` 即可

---

## 音效 (Sound Effects)

### 替換方式
放入 `assets/audio/sfx/<sfx_id>.ogg`。
引擎優先載入 `.ogg`，缺失時自動用程序式 SFX fallback。

| SFX ID | 搜尋關鍵字 | 推薦來源 |
|--------|-----------|---------|
| `thunder_crack` | "thunder close" / "lightning crack" | Freesound CC0 |
| `oar_creak` | "oar rowing" / "boat oar splash" | Freesound CC0 |
| `rain_heavy` | "heavy rain roof" / "rain on tin roof" | Freesound CC0 |
| `footsteps_puddle` | "footstep puddle" / "wet footstep" | Freesound CC0 |
| `paper_rustle` | "paper rustle" / "paper shuffle" | Freesound CC0 |
| `power_failure` | "power outage" / "electrical failure" | Freesound CC0 |
| `water_distant` | "underground water" / "distant water flow" | Freesound CC0 |
| `market_closing` | "metal shutter" / "rolling gate close" | Freesound CC0 |

### Freesound 使用步驟
1. 前往 https://freesound.org 搜尋關鍵字
2. 過濾 「License: Creative Commons 0」
3. 下載後用 **Audacity**（免費）轉存為 Ogg Vorbis 格式
4. 命名為 `<sfx_id>.ogg` 放入對應目錄

---

## BGM 環境音 (Background Music)

| BGM ID | 搜尋關鍵字 | 推薦來源 |
|--------|-----------|---------|
| `ambient_old_city` | "city night ambient" / "taiwan night" | Freesound CC0 |
| `ambient_shrine` | "temple ambient" / "incense drone" | Freesound CC0 / OpenGameArt |
| `ambient_rain_night` | "rain night atmosphere" / "storm ambient" | Freesound CC0 |

### 其他音樂來源
- **Free Music Archive** (freemusicarchive.org) — CC0/CC-BY
- **Incompetech** (incompetech.filmmusic.io) — Kevin MacLeod 作品，大量免費（CC-BY）
- **Pixabay Music** — 大量免費商用配樂

---

## 字型 (Fonts)

目前使用系統字型。建議替換為：

| 字型 | 風格 | 授權 | 下載 |
|------|------|------|------|
| **Noto Serif TC** | 台灣傳統繁體中文，典雅 | OFL 1.1 (免費) | https://fonts.google.com/noto/specimen/Noto+Serif+TC |
| **Source Han Serif** | Adobe 思源宋體，精緻 | OFL 1.1 (免費) | https://github.com/adobe-fonts/source-han-serif |
| **Cubic 11** | 像素方塊字型，另類 | OFL 1.1 (免費) | https://github.com/ACh-K/Cubic-11 |

### 安裝方式
下載字型檔（.woff2 或 .ttf），放入 `assets/fonts/`，在 `engine/css/engine.css` 頂部加入：

```css
@font-face {
  font-family: 'Noto Serif TC';
  src: url('../assets/fonts/NotoSerifTC-Regular.woff2') format('woff2');
  font-weight: 400;
}
```

然後在 CSS 中將 `font-family` 改為 `'Noto Serif TC', serif`。

---

## 資源整合優先順序建議

1. **立刻有效**：本 repo 重繪的 SVG 立繪（已完成）
2. **音效**：從 Freesound 下載 `thunder_crack.ogg` 和 `oar_creak.ogg` 各一個，替換程序式版本
3. **背景**：從 Unsplash 下載 2-3 張台灣廟宇/夜市照片，加 GIMP 濾鏡
4. **字型**：安裝 Noto Serif TC，對中文排版有顯著提升
5. **立繪**：若要商業品質，考慮在 FVN/Sutemo 找相近風格並重命名
