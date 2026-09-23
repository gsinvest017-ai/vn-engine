# sign_fix 使用說明：假漢字「平面追蹤換字」

工具：`tools/video/sign_fix.py`（規格欄位的權威定義在模組 docstring）。
一個 clip 對應一個規格檔 `video_out/remaster_v2/sign_fix/specs/<clip 名>.json`，同一個 clip 的多個物件都寫在同一檔的 `objects` 裡，會依序套用。

輸出：
| 產物 | 位置 |
|---|---|
| 修補後 clip（x264 crf 10、同 fps／解析度、bt709、音訊原樣 copy） | `video_out/remaster_v2/clips_fixed/<原檔名>` |
| 對照圖（修補前／後／追蹤框 ＋ 一張全幅） | `sign_fix/contact/<clip>__<id>.jpg` |
| canvas 除錯圖（原圖｜遮罩｜成品｜混合權重） | `sign_fix/debug/<clip>__<id>.png` |
| 追蹤與合成量測 | `sign_fix/reports/<clip>.json` |
| 錨點 quad 格線預覽 | `sign_fix/preview/<clip>__<id>__t<秒>.png` |

原始 `video_out/clips/` 只讀、不會被覆寫。

## 一、流程（每個物件約 10–20 分鐘）

```powershell
cd C:\Users\User\vn-engine-remaster
$env:PYTHONIOENCODING = "utf-8"
python tools/video/sign_fix.py init H060              # 1. 從 hanzi 報告產生規格草稿＋格線預覽
#   → 修改 specs/<clip>.json 裡的 quad／text／direction（見第三節）
python tools/video/sign_fix.py preview video_out/remaster_v2/sign_fix/specs/<clip>.json   # 2. 反覆看 quad 貼不貼
python tools/video/sign_fix.py run --no-encode video_out/remaster_v2/sign_fix/specs/<clip>.json  # 3. 只做追蹤＋對照圖（快）
python tools/video/sign_fix.py run video_out/remaster_v2/sign_fix/specs/<clip>.json       # 4. 滿意後正式輸出
```

`init` 會把同一 clip 的物件附加到同一個規格檔（同 id 會覆蓋），並在 `_todo` 欄寫下還要人工處理的事；
`_todo`、`_hanzi`、`note` 這些欄位工具不會讀，可以留著當註記。
一次 run 12 秒的 clip 大約 20–60 秒（純 CPU，不用 GPU）。

## 二、規格欄位

```jsonc
{
  "clip": "第一章_01_3_294f_t.mp4",
  "note": "自由註記",
  "objects": [{
    "id": "H024",
    "mode": "replace",          // replace 換真字 | erase 抹成素面 | defocus 失焦
    "text": "神恩浩蕩",          // replace 用；一個 quad 只放一行（一條聯），字數要等於你想要的格數
    "direction": "h",           // h 橫書 | v 直書（上→下）
    "order": "ltr",             // 橫書 ltr 左→右 | rtl 右→左（傳統匾額）
    "range": [0, 6.95],         // clip 內的秒數；省略＝整段。clip 中途切鏡頭時一定要截在切點前
    "anchors": [                // 至少一個；t（秒）或 frame（幀號）擇一
      {"t": 3.0, "quad": [[412,462],[485,404],[485,459],[412,522]]}
    ],
    "base_anchor": 0,           // 用哪個錨點做底圖：挑物件最大、最清楚、沒被擋的那格
    "text_box": [0,0,1,1],      // 字排在 quad 裡哪一塊（quad 框整塊匾、字只在中間時用）
    "font": "kaiu",             // kaiu 標楷體（聯、匾、桌裙、手寫）| msjh / msjhbd 微軟正黑（現代招牌）| mingliu | 字型檔路徑
    "pad": [0.06, 0.06],        // 每個字格的留白比例（x, y）
    "keep_aspect": false,       // true＝字不拉伸（格子明顯比字寬時用，例如 4 格匾放 3 個字）
    "weight": "auto",           // auto＝對齊原筆畫寬；或數字（畫面像素，+粗 −細）
    "text_color": "auto",       // auto＝取原筆畫顏色；或 [r,g,b]
    "text_color2": "auto",      // 字的第二色（低頻紋理的亮端），金字可給較亮的金
    "outline": null,            // {"color":[r,g,b], "width":1.0} 描邊
    "blur": 0.3,                // 字的模糊（畫面像素）；原片越糊越大
    "grain": "auto",            // 補洞處與字上的靜態顆粒（8bit 單位）
    "temporal_grain": "auto",   // 逐幀顆粒；auto＝量原片
    "mask_thresh": "auto",      // 原筆畫偵測門檻（Lab 距離）；抓不到暗字時手動調低（15–30）
    "mask_dilate": 1.5,         // 原筆畫遮罩外擴（畫面像素）；邊緣有殘影時加大（2–3）
    "fill": "blur",             // 素面補法 blur（正規化卷積，平滑底）| telea
    "blend": "strokes",         // strokes＝只蓋筆畫附近（預設，較不像貼紙）| quad＝整塊蓋掉
    "feather": 2.0,             // 羽化（畫面像素）
    "protect_luma": null,       // 例 200：比這亮的像素（燈管、燭火等前景）保留原畫面
    "gain_smooth": 0,           // 逐幀增益平滑視窗（0＝不平滑，閃電／閃光才跟得上）
    "defocus_sigma": 3.0,       // defocus 模式的模糊強度
    "upscale": 4,               // canvas 放大倍數（不用改）
    "track": {
      "pad": 30,                // quad 外擴多少像素當追蹤區
      "poly": null,             // 自訂追蹤多邊形（基準錨點幀座標）：只圈跟字同一個平面的區域
      "static": false,          // true＝不追蹤，quad 固定（真的完全不動才用）
      "smooth": 9,              // 角點軌跡 Savitzky–Golay 視窗（幀）；固定鏡頭可 15
      "min_cc": 0.6             // ECC 相關係數低於此值＝低信心幀，用鄰幀內插
    }
  }]
}
```

### quad 的定義

四個角的順序是**文字正立時**的 左上、右上、右下、左下（不是畫面座標的左上）。直書對聯也一樣：字頭朝上時的左上角。
quad 描的是**文字那一塊平面**：邊要順著招牌／桌裙／紙頁的透視（斜面就畫平行四邊形／梯形），把所有原字**完整包住並留 1–2 px**，
但不要吃到旁邊的金邊、框線（會被當成筆畫抹掉）。字的格子是把 quad 內（text_box）沿書寫方向等分成 `len(text)` 格，
透視會由 homography 自動套上，所以近大遠小不用自己算。

## 三、從 hanzi 報告的 bbox 快速得到 quad

1. `init <Hxxx>` 會拿 `bbox_traj_sampled` 的第一格與最後一格當兩個錨點，quad 先填 OCR 外接框的四角，並輸出格線預覽圖
   （`preview/` 下，5 倍放大，每 10px 一條格線、每 50px 標座標，紅點＝quad 第一個角）。
2. 打開預覽圖，照字的實際位置改四角：
   - 正面平視的匾額、標題：外接框就差不多，只要各邊外擴 1–2 px。
   - 斜面（桌裙側面、牆上招牌斜看）：先找字列的**上緣線**和**下緣線**（最左字與最右字的頂／底各一點連線），
     左右邊通常是鉛直線，交出四個角。
   - 直書對聯：quad 是細高條，`direction` 設 `v`；一條聯一個物件。
3. `preview` 再看一次，四邊都貼著字外緣就可以 run。
4. 只需要一個錨點就能跑（整段追蹤）；鏡頭推很多（物件放大 >1.3 倍）或有遮擋時，在後段再加一個錨點（在那一幀重新描 quad），
   報告裡的「錨點落差」就是兩個錨點互追的差距，<2 px 表示追蹤和標註一致。
5. OCR 框會抖、也常只框到部分字，**不要直接用 OCR 框當最終 quad**。

## 四、檢查結果（contact sheet 看什麼）

對照圖標題列有：cc 平均／最低（ECC 相關係數，>0.9 很穩、0.6–0.9 要看、<0.6 會被標低信心並內插）、
低信心幀數、抖動（角點二階差分 RMS，<0.3 px 肉眼看不出）、錨點落差。

逐張看：
1. **第三列追蹤框**：綠框是否一直貼著招牌（紅框＝低信心幀）。框有滑動、跳動 → 加 `track.poly` 圈同一平面，或加錨點。
2. **第二列修補後**：
   - 原字殘影（字旁邊有舊筆畫的碎片、暗色邊）→ 加大 `mask_dilate`、調低 `mask_thresh`，或 quad 沒包住原字（擴大）。
     看 `debug/` 圖第二格：紅＝偵測到的原筆畫、綠＝補洞範圍、藍＝新字；原字沒被紅／綠蓋到的地方就是殘影來源。
   - 新字太粗／太細／太糊 → `weight` 給數字、`blur` 調整。
   - 顏色不對（例如金字變褐色）→ `text_color` / `text_color2` 手動給；只在某段時間不對通常是受光變化，工具已用原筆畫逐幀算「字的增益」，
     看報告 `text_gain_range`。
   - 整塊像貼紙（底色比周圍亮或糊）→ 用預設 `blend: strokes`，`fill` 試 `telea`。
   - 前景物（燈管、人、煙）被字蓋住 → 亮的前景用 `protect_luma`；暗的前景目前沒有自動保護，改 `range` 避開或退回 defocus。
3. **全幅縮圖**：以正常觀看大小看字的大小、位置是否自然。
4. 最後用播放器看整段 `clips_fixed/<clip>`（至少看 range 的頭尾和鏡頭運動最大的地方），確認沒有閃爍、滑動。
   報告的 `untouched_mean_abs_diff`（修補區外平均差）正常約 0.4–0.7（重編碼雜訊），>1.5 表示色彩轉換出問題。

## 五、失敗時的退路

依序嘗試：
1. **追蹤不穩**（cc 低、框滑動）：`track.poly` 只圈同平面 → 加錨點（每 2–3 秒一個）→ 縮小 `range` 只修成片實際用到的段（hanzi 報告的 `src_sec`）。
2. **換字做不好看**（字太小、材質太複雜、嚴重遮擋）：改 `"mode": "erase"`（抹成素面，保留招牌本體）。
3. **erase 也不自然**（底紋複雜、補不乾淨）：改 `"mode": "defocus"`，`defocus_sigma` 3–6；quad 框整塊字區即可，精度要求低。
4. 真的都不行：在報告註明，交回主控決定重生該段 clip。

不要為了硬修而把 quad 畫到其他平面、或把 `min_cc` 調到很低來掩蓋追蹤失敗。

## 六、已完成的 4 個（正式產物，批次不用重做）

| id | clip | 內容 | 重點設定 | cc 最低 | 抖動 |
|---|---|---|---|---|---|
| H024 | 第一章_01_3_294f_t | 桌裙「神恩浩蕩」（斜面） | 單錨點、smooth 15 | 0.990 | 0.06 px |
| H037 | 第一章_02_0_192f | 水路圖標題「翰溪庄水路圖」 | 單錨點 | 0.934 | 0.05 px |
| H094 | 第三章_00_5_294f_t | 廟門匾額「翰溪壇」 | 兩錨點、rtl、keep_aspect、protect_luma 200（燈管在匾前）、mask_thresh 30 | 0.957 | 0.01 px |
| H047 | 第一章_03_2_294f_t | 桌裙「合境保平安」（緩推、下緣出畫） | range 0–6.95（7.0s 切鏡頭）、track.poly、mask_thresh 20、mask_dilate 2.5 | 0.978 | 0.11 px |

經驗值：
- 暗紅布、深色匾上的暗金字，自動門檻常抓不到陰影裡的字 → `mask_thresh` 20–30。
- 閃電場景（第三章夜景）亮度逐幀跳動，`gain_smooth` 保持 0。
- 招牌前有燈管、燭火時一定要 `protect_luma`，否則字會蓋在燈上。
- clip 中途切鏡頭（例如 H047 在 7.0s 切到檔案簿特寫）：`range` 一定要截在切點前，否則追蹤會追到另一個鏡頭。

## 七、第 5 批加的選項（皆預設關閉，舊規格行為不變）

| 欄位 | 用途 | 範例 |
|---|---|---|
| `mask_mode: "dark"` | 暗處紅布／匾上的**墨字**：以灰階閉運算當局部底色，筆畫＝變暗比例 > `mask_thresh`（0–1，auto=Otsu）；陰影漸層不會被當字 | 第二章_00_3 H068/H069（`mask_thresh` 0.2） |
| `text_rel` | 字色＝素面底色 × 比例（跟著底色明暗走；auto＝原筆畫/底色亮度比） | 0.3 |
| `anchors[k].poly` | 該錨點自己的追蹤多邊形（該錨點幀座標），優先於 `track.poly`；鏡頭推近 2 倍、後段錨點要圈不同區域時用 | H069L 第二錨點 |
| `text_gain: "bg"` | 字的逐幀增益跟底色（原筆畫後段被前景擋住時，避免字忽明忽暗） | H069 |
| `occlusion.close` | 遮擋遮罩閉運算（暗色遮擋物蓋在暗筆畫上時差很小，補起遮擋區內的洞） | `{"thresh":24,"blur":3,"close":5}` |
| `track_on: "orig"` | 用原片追蹤（同一平面前面的物件已先 erase 掉紋理時；例如整頁先抹再寫字） | 第二章_00_6 H071 |

經驗：無紋理小物件（紅牌、暗神龕）平面追蹤不可靠 → `track.static: true` 配每 0.25–0.5 秒一個錨點（可用顏色分割量外框）線性內插，只做 defocus。
