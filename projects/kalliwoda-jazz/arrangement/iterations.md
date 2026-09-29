# AI 試聽修正紀錄（Kalliwoda Romanze → Chet/Evans 風爵士圓舞曲 ballad）

工具：`tools/video/listen.py review`（量測層為主；LLM 只做盲描述與是非題）。沒有經過人耳試聽。
指令：`listen.py review mix.wav --brief "慵懶、抒情、寂寥的爵士圓舞曲 ballad：小號主奏、鋼琴、低音提琴、刷子鼓，58 BPM" --ref arrangement/trumpet_ref.mid --stems <iter>/stems --baseline <上一輪 review.json> --target-bpm 58`
渲染：`_render/music/iterN/`；編曲：`tools/video/jazz_arrange.py build --seed 7`；混音設定：`arrangement/render_config.json`。
分軌 RMS 以整條分軌計算（小號在前奏、鋼琴獨奏、間奏時休息，也算進分母）。

## 渲染前先修的已知問題（sound 報告）

- **小號太悶**（原本 2 kHz 以上只占 0.47%）：原 SFZ 只用 VSCO v1（很暗）力度層。新的 `sound/sfz/trumpet_chet_combo.sfz` 把 v1（暗）與 v3（亮，壓低 20 dB）依力度交叉淡化，低通 3.4 kHz＋力度追蹤，另疊很淡的帶通雜訊氣音層；harmon 弱音器用 CC110 在同一分軌切換。單音實測亮度（2 kHz 以上／250 Hz–2 kHz）：v1 單用 −33 dB → 合成後 −15～−19 dB。
- **掃刷太小聲、斷續；CC21 為何「無效」**：量測後發現 CC21 其實有作用，但它只把衰減時間從約 0.4 秒拉到約 1.5 秒。原廠程式的 stir 是 `loop_mode=one_shot`＋`ampeg_sustain=0`，note 再長也會在 1.5 秒內消失；stir 樣本本身又比刷擊小 10–20 dB。新的 `sound/sfz/brush_jazz.sfz` 改成 `no_loop`＋sustain 100、依 note-off 釋放、+12 dB，每拍一個掃刷互相交疊。另外兩個鍵（24/25）交替使用，避免同鍵重疊時前一個 note-off 把下一刷切掉。
- 渲染器：`jazz_render.py` 新增每軌 `eq`（RBJ high/low shelf、peak）。所有軌加 `--use-eot`（第一次渲染時，尾端延音踏板沒放，Salamander 分軌跑到 1 GB 仍在寫，已中止重來；MIDI 也補了結尾放踏板）。
- 編曲程式在寫測試時抓到一個 bug：`chord_at` 用整首的小節編號去索引段落內的小節清單，伴奏拿到了錯的和弦。已修正。

## 第 1 輪（iter1）

- 速度 58.0 BPM（目標 55–61 內）；full-band swing 1.75（相位 0.636，IQR 0.037，可靠），但因為拍點間隔變異係數 0.169 ≥ 0.10，**swing 被判為不採用**。估計每小節拍數 2.24（應為 3）。
- 小號分軌 F1 0.99（參考 249 音、轉出 254 音，漏 0、錯 0、多 5），輪廓相似度 1.0，起音偏差中位數 4.6 ms。
- CLAP 目標 0.467，反例最高 0.161（margin +0.31）；PQ 8.10；Discogs 前五含 Jazz—Hard Bop。
- 分軌 RMS：小號 −38.9、鋼琴 −45.5、低音 −42.9、刷子 −55.8、hi-hat **−76.1**（比小號低 37 dB，幾乎聽不到）。小號亮度 −13.8 dB、2 kHz 以上占 4.0%（不再過悶）。沒有「太前面」警告，沒有爆音（TP −1.14 dBTP）。
- LLM 盲描述：慢、ambient jazz、鋼琴＋柔和小號、平靜。是非題：小號有、鋼琴有、低音提琴**沒有**、鼓／刷子**沒有**（Essentia 鼓 0.34、低音 0.26，兩者意見不一）。
- **修改**：前奏全程加很輕的掃刷，尾聲掃刷延到 R88，讓拍點追蹤不在沒有鼓的地方飄；每小節第一刷加重（1.08→1.15）強調三拍子的強拍；hi-hat 腳踩第 3 拍出現機率 0.45→0.6；刷子 +5 dB、hi-hat +14 dB、低音 +2 dB。

## 第 2 輪（iter2）

- 速度追蹤變成 115.8（以半速解讀為 58，仍算在範圍內），但拍點 CV 升到 **0.399**，局部速度 p10–p90 57.7–120，swing 仍不採用。
- 逐段拆解（自寫腳本、同一個 beat_this 模型）：iter1 各段都是 58；iter2 在 head_a2、link、return 變成倍速（111–115）。
- 其餘：F1 0.99、CLAP margin +0.285、PQ 8.09。刷子 −50.7、hi-hat −61.8（都比小號低 11 dB 以上，沒有「太前面」）。
- **修改**：刷子反拍 ghost 機率 0.35→0.2、力度 24→20；鋼琴反拍伴奏不再加重；hi-hat −5 dB；尾聲最後的延長和弦底下刷子繼續慢慢畫圈、漸弱（讓延長的那 10 秒也有拍點，否則一個約 9 秒的拍間隔就會讓整體 CV 多出約 0.45）。

## 第 3 輪（iter3）

- 仍然倍速（115.8，CV 0.353）。沒有改善。
- **離線對照實驗**（同一區段 60–118 s）：乾分軌混合 → 57.7；premix → 57.7；**只把 premix 拉大 4 dB（浮點、沒有削波）就會變成 58.8／CV 0.25**，壓縮＋限幅也一樣。結論：beat_this 對輸入音量敏感；混音拉到 −16 LUFS 後，較小聲的反拍內容（刷子掃刷紋理、搖擺伴奏、殘響）變得顯著。混音必須維持 −16 LUFS，所以改從各軌平衡下手。
- 在實際響度下做分軌增益網格：刷子 +4 dB → 全曲倍速；**刷子 −3 dB → 全曲 58、CV 0.069**；低音 +4 dB 也有幫助。推測原因：stir 樣本本身帶有錄音時畫圈的節奏，跟曲速無關（未證實）。
- **修改**：刷子 5→2 dB、低音 −3→0 dB、hi-hat 9→11 dB。

## 第 4 輪（iter4）

- 速度 58.0，但整體 CV 0.144，swing（full-band 1.75，可靠）仍被否決。
- 照 listen.py 的路徑（22.05 kHz 單聲道）重跑：head_a2 的 R32–R35（約 94–103 s，小號連續 swing 八分音爬到 G5）、return 的一處，以及尾聲漸慢處，追蹤器插入了剛好半拍的拍點。
- 低頻（60–250 Hz）占 46%（未超過 60% 的門檻）。
- **修改**：小號 swing 反拍八分音力度 −9（Chet 式 back-phrasing），鋼琴 fill 的反拍 −6。

## 第 5 輪（iter5）

- 沒有改善（CV 0.164，n_beats 305）。把「分軌增益 → 真實 bus 鏈（acompressor＋volume＋alimiter）→ listen 的 22.05 kHz 路徑」整條重現後做消融：刷子 +2 dB → 121 個半拍；**刷子 −3 dB → 只剩 1 個（在尾聲漸慢）**；鋼琴 +3 dB 同樣有效；低音 −3 dB 則變差。組合「刷子 −3、鋼琴 +1.5、低音 +1.5」→ CV 0.069。
- 反拍放輕保留（聽感上合理，但對節拍追蹤沒有可量到的幫助）。
- **修改**：刷子 2→−1 dB、鋼琴 −2→−0.5 dB、低音 0→1.5 dB。

## 第 6 輪（iter6，定稿）

- **全部達標**：速度 58.0 BPM（CV 0.057，「穩」）、**swing 1.75**（相位 0.636，IQR 0.042，可靠，89 拍）、小號分軌 F1 0.99（漏 0、錯 0、多 5，輪廓 1.0）、CLAP 目標 0.479 對反例最高 0.150（margin +0.33）、PQ 8.12、CE 7.69、Discogs 前五含 Jazz—Contemporary Jazz，Essentia 情緒前 8 名含 relaxing／melodic／romantic／emotional／ballad。沒有「太前面」警告，也沒有任何「不符之處」。
- 分軌 RMS：小號 −39.0、鋼琴 −44.3、低音 −36.4、刷子 −56.7、hi-hat −65.0。小號亮度 −13.8 dB、2 kHz 以上占 4.0%。
- 混音：−16.0 LUFS、true peak −1.15 dBTP、削波 0、LRA 9.5 LU、長 312.7 s（5:13）。
- 仍存疑：LLM 是非題在第一個 30 秒窗（只有前奏：鋼琴＋很輕的掃刷，還沒有低音與小號）回答低音提琴、鼓、刷子「沒有」，這是預期的；Essentia 小號只有 0.07（report.md 已記錄它抓不到小號）。整體低頻 60–250 Hz 占 52%、頻譜重心 388 Hz，沒有超過門檻，但偏暗、偏厚，建議人耳確認。

→ 定稿：`_render/music/final/`（mix.wav、stems/、final_review.json、review.md、render_report.json、當次 MIDI 與混音設定）。`arrangement/sections.json` 已用 `jazz_arrange.py finalize` 校正（總長＝實際混音長度；量到的小號第一個音 24.946 s，段落起點 24.828 s，差距就是刻意的 lay-back）。
