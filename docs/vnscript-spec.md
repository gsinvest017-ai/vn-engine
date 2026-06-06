# VNScript (.vns) 格式規格

視覺小說腳本語言，設計原則：人類可讀、git-diffable、與素材系統直接對位。

## 基本結構

```
# 這是註解，整行忽略

@chapter 第一章　標題           # 章節宣告
@scene bg=scene_id               # 場景指令
[角色id] 對話文字                # 角色對話
> 強調旁白                       # 引用/強調文字
一般旁白文字                     # 普通旁白（無前綴）
```

---

## 指令完整參考

### `@chapter <title>`
宣告章節標題，顯示章節卡。

```
@chapter 第一章　河流被埋進城市之後
```

### `@scene`
設定背景場景。

| 參數 | 說明 | 預設 |
|------|------|------|
| `bg=<id>` | 背景圖片 ID（對應 assets/backgrounds/<id>.svg 或 .png） | 必填 |
| `music=<id>` | 同步切換 BGM | — |
| `transition=fade\|dissolve\|none\|wipe` | 轉場效果 | `fade` |

```
@scene bg=shrine_interior transition=fade
@scene bg=old_city_dusk music=ambient_city transition=dissolve
```

### `@weather`
天氣/環境效果（疊加層）。

| 參數 | 說明 |
|------|------|
| `rain=none\|drizzle\|light\|heavy\|storm` | 雨量 |
| `fog=<0-1>` | 霧氣濃度 |
| `wind=<0-1>` | 風力（影響雨角度） |

```
@weather rain=heavy fog=0.2
@weather rain=none
```

### `@char`
角色精靈管理。子指令：

**show** — 顯示角色
```
@char show=narrator pos=right expr=tired
@char show=diao_caidi pos=left expr=normal
```

**hide** — 隱藏角色
```
@char hide=narrator
@char hide=all
```

**expr** — 切換表情（不移動）
```
@char expr=narrator:troubled
@char expr=diao_caidi:shocked
```

**move** — 移動位置
```
@char move=narrator pos=center duration=500
```

| 位置 | 說明 |
|------|------|
| `left` | 左側 |
| `center` | 中央 |
| `right` | 右側 |
| `offscreen_left` | 畫面左外 |
| `offscreen_right` | 畫面右外 |

### `@sfx`
音效管理。

```
@sfx play=market_closing volume=0.5
@sfx play=rain_heavy loop=true
@sfx stop=rain_heavy fade=2000
@sfx play=oar_creak volume=0.3 delay=500
```

### `@bgm`
背景音樂管理。

```
@bgm play=ambient_old_city fade=2000
@bgm stop fade=3000
@bgm volume=0.4
```

### `@effect`
視覺特效。

| 特效 | 參數 | 說明 |
|------|------|------|
| `shake` | `intensity=0-1 duration=ms` | 畫面震動 |
| `flash` | `color=white\|black duration=ms` | 閃光 |
| `dim` | `level=0-1` | 暗化疊層 |
| `flicker` | `count=N` | 燈光閃爍 |
| `darkness` | — | 全黑（保留光點） |
| `vignette` | `intensity=0-1` | 暈影效果 |

```
@effect shake intensity=0.3 duration=800
@effect flicker count=3
@effect dim level=0.4
@effect flash color=white duration=200
```

### `@fade`
淡入/淡出。

```
@fade out color=black duration=1000
@fade in duration=800
```

### `@wait`
等待（毫秒）。

```
@wait 1500
```

### `@pause`
等待玩家點擊/按鍵繼續。

### `@choice`
分支選擇。後接 `> 選項文字 -> 標籤` 行。

```
@choice
> 繼續調查 -> label_investigate
> 先離開 -> label_leave
> 什麼都不做 -> label_wait
```

### `@label <name>`
跳躍目標標籤。

```
@label investigate_deeper
```

### `@jump <label>`
無條件跳躍。

```
@jump chapter2_start
```

### `@chapter_end`
章節結束，顯示結束卡，自動進入下一章。

### `@end`
故事結束。

---

## 角色 ID 規範

角色 ID 對應 `assets/characters/<id>/` 目錄：
- `narrator` — 敘述者（主角）
- `diao_caidi` — 刁才弟
- `system` — 系統提示（非角色，無立繪，顯示在中央）

表情 ID 對應 `assets/characters/<id>/<expr>.svg`（或 .png）：

| 通用表情 | 說明 |
|---------|------|
| `normal` | 預設 |
| `happy` | 開心 |
| `sad` | 悲傷 |
| `angry` | 憤怒 |
| `surprised` | 驚訝 |
| `tired` | 疲憊 |
| `troubled` | 困擾 |
| `silent` | 沉默（目光向下） |
| `shocked` | 震驚 |
| `thoughtful` | 沉思 |
| `reading` | 閱讀中 |

---

## 素材 ID 命名慣例

- 背景：`snake_case` 描述性名稱（`old_city_dusk`、`shrine_interior`）
- 音效：`snake_case` 動詞+名詞（`rain_heavy`、`market_closing`、`oar_creak`）
- BGM：`ambient_` 前綴為環境音（`ambient_old_city`）、`theme_` 前綴為主題曲

---

## 完整範例片段

```vns
# 台中暗渠 — 第一章開頭

@chapter 第一章　河流被埋進城市之後
@scene bg=old_city_dusk music=ambient_old_city transition=none
@weather rain=drizzle

黃昏落在舊城區時，總有一種潮濕的重量。

@wait 800

從第三市場往東走，穿過幾條被機車與鐵窗占滿的小巷……

@fade out duration=800
@scene bg=shrine_interior transition=none
@fade in duration=1200

我坐在翰溪庄附近一間老舊的道壇裡。

@char show=narrator pos=right expr=tired
@effect dim level=0.1

屋頂很低。午後下過雨，濕氣沿著牆角向上蔓延。

@char show=diao_caidi pos=left expr=normal

[diao_caidi] 你最近是不是又沒睡？

@char expr=narrator:silent

我沒有回答。
```
