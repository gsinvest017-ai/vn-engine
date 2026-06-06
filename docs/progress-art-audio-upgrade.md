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

## M1+M2 — 角色立繪全面重繪（commit 56726ac）
- 移除所有 SVG 全畫面覆蓋 `<rect fill="url(#rim_r)">` / `fill="url(#shadow_l)">` → 去背修復
- narrator 6 張（normal/tired/troubled/silent/thoughtful/reading）完整重繪：精緻眼睛結構（白眼球路徑 + 上眼瞼月形 + 虹膜/瞳孔/高光圈）+ 明顯表情差異（眼瞼下垂程度、眉毛角度、嘴型、姿勢）
- diao_caidi 3 張（normal/questioning/shocked）完整重繪：休閒短袖造型（有別於 narrator 風衣）+ 驚嚇張口表情 + 手臂動態

## M3 — 音效修復（commit fd5a27c）
- `_sfxThunder()` 新增：crack 雜訊 + 3 層滾動低頻 + 42Hz sub-bass
- `_sfxOar()` 改為 `_loopSource` + 0.47Hz LFO 持續循環（修復單次播放問題）
- `chapter3.vns` 加入 `@sfx play=thunder_crack` + manifest 更新

## M4 — 免費素材指引（本 commit）
- 建立 `docs/free-vn-assets.md`：角色立繪 / 背景圖 / 音效 / BGM / 字型 完整來源表
- 涵蓋 itch.io / OpenGameArt / Freesound / Unsplash / Google Fonts 各平台授權說明
- 提供 Freesound 搜尋關鍵字對應表（每個 SFX ID 對應搜尋詞）
- 說明 GIMP 背景圖處理工作流程（降飽和 + 暗角 → 風格化台灣夜景）

## Fallback 指引
- `git checkout <hash> -- assets/characters/` 還原立繪
- `git checkout <hash> -- engine/js/audio/procedural.js` 還原音效
