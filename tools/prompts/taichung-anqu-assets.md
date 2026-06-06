# 台中暗渠 素材 AI 生成提示詞

使用任何 AI 繪圖工具（Midjourney / DALL-E / Stable Diffusion / ComfyUI）生成正式素材時，
請以下列提示詞為基礎，依工具語法微調。

---

## 背景（Backgrounds）

### old_city_dusk（台中舊城區黃昏）
```
photorealistic oil painting, dusk in old Taichung city, traditional Taiwanese market district,
old brick buildings and tin rooftops, orange and amber sunset sky with dark silhouettes,
utility poles with tangled wires, wet asphalt reflections, humid heavy air, noir atmosphere,
no people, 16:9 horizontal, dark muted palette
```
**中文版（SD-XL friendly）:**
```
台中舊城區黃昏，第三市場附近，橙紅夕陽，老舊三合院與鐵皮屋剪影，電線縱橫，
雨後潮濕地面，16:9橫向，寫實油畫風格，暗色調，無人物
```

### shrine_interior（道壇內部）
```
dimly lit interior of an old Taiwanese folk religion shrine, low ceiling, cement walls
with white salt efflorescence patches, incense smoke, flickering oil lamp,
wooden altar in background, oppressive and humid atmosphere, cinematic horror light,
no people, 16:9 horizontal
```

### city_historical（古代水路圖）
```
aged Qing Dynasty Taiwan manuscript map, yellowed rice paper texture, ink brush strokes,
waterway routes around Hanxi settlement, temple location markers, water stains and foxing,
horizontal scroll format, 16:9, minimal color palette (sepia + ink)
```

### archive_room（舊檔案室）
```
dark government archive room at night, wooden shelving units filled with yellowed files
and folders, single desk lamp casting warm amber light, dust particles, claustrophobic,
Taiwan government records aesthetic, 1970s-1980s, no people, 16:9
```

### shrine_entrance_night（道壇入口夜雨）
```
entrance to a Taiwanese folk temple at midnight during typhoon, power outage,
only distant convenience store green sign glowing, torrential rain, wet stone pavement,
complete darkness except small light sources, horror atmosphere, 16:9
```

### underground_river（地下暗渠）
```
underground brick-arched water channel beneath Taichung, dark tunnel,
ancient covered river, faint bioluminescent water surface, a single old wooden boat,
dripping water from ceiling, eerie atmosphere, 16:9
```

---

## 角色立繪（Character Sprites）

### narrator（敘述者）
**Base style:**
```
male figure, mid 40s, Taiwanese appearance, wearing dark navy trench coat, 
tired deep-set eyes, noir detective aesthetic, semi-realistic visual novel art style,
transparent background, full body front-facing, 1:2 aspect ratio (e.g. 800x1600px)
```

| 表情 | 追加關鍵詞 |
|------|-----------|
| `normal` | neutral expression, looking forward |
| `tired` | heavy-lidded eyes, dark circles, slight forward lean |
| `troubled` | furrowed brows, worried expression, hand near face |
| `silent` | eyes downcast, mouth closed, introspective |
| `thoughtful` | one eyebrow slightly raised, slight head tilt, hand to chin |
| `reading` | eyes downward, holding yellowed document in both hands |

### diao_caidi（刁才弟）
**Base style:**
```
male figure, mid 40s, slightly stocky build, Taiwanese working-class appearance,
short-sleeved casual shirt, alert and direct expression, visual novel art style,
transparent background, full body front-facing, 1:2 aspect ratio
```

| 表情 | 追加關鍵詞 |
|------|-----------|
| `normal` | relaxed, slight smile, curious eyes |
| `questioning` | raised eyebrow, one hand slightly raised, open palm |
| `shocked` | wide open eyes, open mouth, arms back |

---

## 音效（Audio SFX）

| ID | 描述 | 建議工具 |
|----|------|---------|
| `market_closing` | 傳統市場鐵捲門關閉聲，數聲交疊 | ElevenLabs SFX / Freesound |
| `footsteps_puddle` | 拖鞋踩積水啪嗒聲 | Freesound |
| `paper_rustle` | 舊紙張翻動聲 | Freesound |
| `oar_creak` | 木槳撥水聲，緩慢有迴響 | 自行錄製 / Freesound |
| `water_distant` | 遠方地下水流聲，循環 | Freesound / SFX Generator |
| `rain_heavy` | 暴雨打鐵皮屋頂聲，循環 | Freesound |
| `power_failure` | 停電電流切斷聲 | SFX Generator |

## BGM（背景音樂）

| ID | 描述 | 建議 |
|----|------|------|
| `ambient_old_city` | 台灣老城環境音，低沉ambient | Suno AI / UDIO prompt: "dark ambient, Taiwan old district, humid night, distant traffic, no melody" |
| `ambient_shrine` | 廟宇靜謐，偶有香煙音 | "dark ambient, incense, silent temple, low drone" |
| `ambient_rain_night` | 暴雨夜，緊張 | "heavy rain on tin roof, thunder, power outage, horror ambient" |
