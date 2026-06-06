# 網頁試玩版部署進度

## 目標
以最快速度讓《暗渠之書》提供可分享的網頁試玩連結。
Engine 為純靜態網站（HTML/CSS/JS + fetch .vns），無後端依賴，任何靜態托管平台均可運行。

## 計畫 Milestone

| # | 項目 | 預期產出 |
|---|------|---------|
| M1 | Root 重導向 + 平台設定檔 | index.html / netlify.toml / vercel.json / .nojekyll |
| M2 | Pack 打包腳本 | pack_demo.py → dist/ + vn-demo.zip |
| M3 | GitHub Actions | .github/workflows/pages.yml 自動部署 |
| M4 | 文件 + README | 三平台 step-by-step 部署指引 |

## Fallback 指引
- rollback M1：`git checkout <hash> -- index.html`
- 重新打包：`python pack_demo.py --zip`
- 確認靜態可行：本地 `python serve.py` → 開 `http://localhost:8080/` 應自動轉到 engine

---

## 三種最快部署方式比較

| 平台 | 所需時間 | 需要帳號 | 自訂網址 | 備注 |
|------|---------|---------|---------|------|
| **Netlify Drop** | ~60 秒 | 不需要（臨時 URL）/ 需要（永久） | ✓ | 最快，拖曳即可 |
| **GitHub Pages** | ~5 分鐘 | GitHub 帳號 | 需自訂域 | 有 git push 即自動重部署 |
| **itch.io** | ~10 分鐘 | itch.io 帳號 | ✓ | 最適合遊戲 demo 分享 |

---

## 平台操作步驟

### 方案 A：Netlify Drop（最快，無需 git）

```bash
# 1. 打包
python pack_demo.py

# 2. 瀏覽器開啟 https://app.netlify.com/drop
# 3. 把 dist/ 資料夾拖進去
# 4. 30 秒後得到 https://xxxx.netlify.app 網址
```

如需固定網址：登入 Netlify → Site settings → Change site name

---

### 方案 B：GitHub Pages（有 GitHub 帳號）

```bash
# 1. 在 GitHub 建立新 repo（例如 vn-engine 或 anqu-demo）
# 2. 綁定 remote
git remote add origin https://github.com/<你的帳號>/vn-engine.git
git branch -M main
git push -u origin main

# 3. 在 GitHub repo → Settings → Pages → Source: GitHub Actions
# 4. Actions 會自動觸發，~2 分鐘後上線
# URL: https://<你的帳號>.github.io/vn-engine/
```

---

### 方案 C：itch.io（最適合遊戲試玩分享）

```bash
# 1. 打包含 zip
python pack_demo.py --zip
# → 產生 vn-demo.zip（~N MB）

# 2. 登入/建立 https://itch.io 帳號
# 3. Dashboard → Create new project
#    - Kind of project: HTML
#    - Title: 暗渠之書
#    - Upload vn-demo.zip
#    - ✓ This file will be played in the browser
#    - Viewport dimensions: 1280 × 720（或不設）
# 4. Save & view page
```

---

## Fallback 指引
- 如果 itch.io 播放畫面空白：確認 index.html 在 zip 根目錄（`dist/` 打包後會是這樣）
- 如果 GitHub Pages 404：確認 repo Settings → Pages → Source 設為 GitHub Actions
- 如果 Netlify Drop 報 CORS：確認 index.html 使用相對路徑（不含 localhost）
