# Blender MCP + VRoid Studio 素材工作流程

本文件說明如何利用 Blender MCP 與 VRoid Studio 為「暗渠之書」製作高品質的角色立繪與場景背景。

---

## 一、Blender MCP 設定（一次性步驟）

### 已自動完成的設定
- ✅ `blender-mcp` Python 套件已安裝 (`pip install blender-mcp`)
- ✅ Blender addon 已存在：`%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\blender_mcp_addon.py`
- ✅ Claude Code MCP 設定已加入：`vn-engine/.mcp.json`

### 你需要手動做的（每次啟動 Blender 前）

1. **開啟 Blender 5.1**

2. **啟用 addon**（只需做一次）
   - `Edit` → `Preferences` → `Add-ons`
   - 搜尋 `Blender MCP`
   - 勾選左側方格 ✓ 啟用
   - 關閉 Preferences 視窗

3. **啟動 MCP Server**（每次開 Blender 都需要）
   - 在 3D Viewport 按 `N` 開啟側欄
   - 找到 `BlenderMCP` 分頁
   - 點擊 `Start MCP Server`
   - 看到 "Server running on localhost:9876" 表示成功

4. **重新開啟 Claude Code 會話**
   - Blender MCP 連線在會話開始時建立
   - 重啟後輸入 `/mcp` 確認 `blender` 伺服器顯示為 connected

---

## 二、Blender MCP 使用場景（連線後 Claude Code 可執行）

### A. 渲染 VN 角色立繪（需先匯入模型）

```
請 Claude Code：
"用 Blender MCP 幫我設定一個 VN 立繪渲染場景：
 - 正面 3/4 視角
 - 白色/透明背景
 - 三點打光（主光 + 補光 + 輪廓光）
 - 渲染輸出 assets/characters/narrator/normal.png
   解析度 400x800，透明背景"
```

### B. 渲染台中舊城背景

```
"用 Blender MCP 建立 shrine_entrance_night 場景：
 - 深夜廟宇門口視角
 - 雨水粒子效果
 - 停電黑暗 + 遠處便利商店綠色點光
 - 渲染 1920x1080 PNG 存至 assets/backgrounds/"
```

### C. 直接用 Python 控制 Blender

當 Blender MCP 連線後，Claude Code 可執行任意 Blender Python：

```python
import bpy

# 清除場景
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# 設定透明背景渲染
bpy.context.scene.render.film_transparent = True
bpy.context.scene.render.image_settings.file_format = 'PNG'
bpy.context.scene.render.image_settings.color_mode = 'RGBA'
```

---

## 三、VRoid Studio 角色立繪工作流程（推薦用於角色）

VRoid Studio 是免費軟體，專為製作 VN/遊戲角色設計，比 Blender 建模簡單很多。

### 安裝
- 下載：https://vroid.com/en/studio
- Windows 版本，免費使用

### 製作「暗渠之書」角色

#### 旁白者（中年偵探）
1. 開啟 VRoid Studio → 新建 Male 角色
2. **臉型**：Face → 選較成熟臉型 → 降低 Eye Size 至約 0.7
3. **頭髮**：略顯凌亂、深棕色或黑色
4. **衣服**：Body → 加長外套（風衣感），顏色選深灰/黑色
5. **表情**：在 Expression 標籤建立：
   - `normal` — 預設
   - `tired` — 眼瞼下垂 (Eyelid Droop +40%)
   - `troubled` — 眉頭上移 (Brow Raise Inner +30%) + 嘴角微下
   - `thoughtful` — 右眉上挑 (Right Brow Raise +25%)

#### 刁才弟（年輕本土男性）
1. 新建 Male 角色
2. **臉型**：較圓，Eye Size 略大 (1.1)
3. **頭髮**：較蓬鬆、微捲
4. **衣服**：休閒短袖 polo 或格子衫，顏色選暖色

### 從 VRoid 匯出 VN 立繪 PNG

**方式一：截圖（最快）**
1. 設定相機為正面 3/4 視角
2. 在 Pose 模式設定表情
3. `File → Export → Export as PNG` 或直接截圖
4. 用 GIMP 去背（若有白底）→ 存為 PNG

**方式二：透過 Blender 匯入渲染（高品質）**
1. VRoid 匯出 `.vrm` 格式（`File → Export → VRM`）
2. 在 Blender 安裝 [VRM Addon for Blender](https://github.com/saturday06/VRM-Addon-for-Blender)
3. 匯入 .vrm → 設定表情的 Shape Keys
4. 用透明背景 + 三點光渲染成 PNG

### 替換 SVG 立繪

將輸出的 PNG 重命名後放入對應路徑，再修改引擎使用 PNG：

```
assets/characters/narrator/normal.png
assets/characters/narrator/tired.png
assets/characters/narrator/troubled.png
```

在 `engine/js/managers/character.js` 中將副檔名從 `.svg` 改為 `.png`：

```js
// 原本
return `assets/characters/${charId}/${expr}.svg`;
// 改成
return `assets/characters/${charId}/${expr}.png`;
```

---

## 四、免費 3D 模型資源

### 人物模型
| 來源 | 內容 | 下載 |
|------|------|------|
| **VRoid Hub** | 大量免費 VRoid 角色，可直接用 | https://hub.vroid.com |
| **Mixamo** | Adobe 免費人物動畫（FBX） | https://www.mixamo.com |
| **Sketchfab Free** | 各式 3D 模型（過濾 Free） | https://sketchfab.com/features/free-3d-models |

### 場景/背景模型
| 來源 | 內容 | 下載 |
|------|------|------|
| **Poly Haven** | 高品質免費 HDRI + 貼圖 + 3D 素材 | https://polyhaven.com |
| **Sketchfab** | 台灣廟宇、街景（搜尋 "taiwan temple"） | https://sketchfab.com |
| **BlendSwap** | Blender 專用場景素材 | https://www.blendswap.com |

> **注意**：Blender MCP 內建 PolyHaven 整合（需 API key）與 Sketchfab 整合（需 API key），
> 有 key 的話可讓 Claude Code 直接從這些平台搜尋並下載素材到 Blender 場景中。

---

## 五、建議的整體工作流程

```
VRoid Hub 下載免費角色模型
    ↓
VRoid Studio 調整表情/衣服
    ↓
匯出 .vrm
    ↓
Blender 匯入 .vrm（需 VRM addon）
    ↓
Blender MCP 讓 Claude Code 自動設定：
  - 相機角度
  - 三點打光
  - 透明背景
  - 批次渲染多個表情
    ↓
PNG 存入 assets/characters/
    ↓
修改 character.js 使用 .png
    ↓
遊戲中看到高品質角色立繪
```
