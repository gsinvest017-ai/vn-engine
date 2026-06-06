# 美術與音效升級進度 — 暗渠之書

## 目標
1. 修復角色去背問題（移除 SVG 全畫面覆蓋矩形）
2. 重繪 narrator + diao_caidi 全部 9 張立繪（清晰瞳孔結構 + 明顯表情差異）
3. 新增打雷聲（`thunder_crack` 程序式 SFX）
4. 修復搖櫓聲迴圈（`oar_creak` 改為持續循環模式）
5. 提供免費開源遊戲素材指引

## 計畫 Milestone

| #  | 項目                        | 預期產出                                            |
|----|-----------------------------|----------------------------------------------------|
| M1 | 修復去背 + 重繪 narrator    | 6 張 narrator SVG（透明背景 + 精緻眼睛 + 明顯表情） |
| M2 | 重繪 diao_caidi             | 3 張 diao_caidi SVG（與 narrator 明顯不同造型）    |
| M3 | 音效修復                   | 打雷聲 SFX + 搖櫓聲真正迴圈 + chapter3 更新        |
| M4 | 免費素材指引               | `docs/free-vn-assets.md` 含實際 URL                |

## 進度日誌

## Fallback 指引
- `git checkout <hash> -- assets/characters/` 還原立繪
- `git checkout <hash> -- engine/js/audio/procedural.js` 還原音效
