"""台灣讀音同音字替換：送進 TTS 的文字依表替換，字幕文字不變。

CosyVoice2 是大陸語料訓練的，兩岸讀音不同的字幾乎都唸成大陸音（remaster v2 讀音檢測，F0 聲調實測：
究竟 jiū、期間 qī、褐 hè、檔 dàng、突 tū、微 wēi、跡 jì…）。改送同音、而且兩岸讀音一致的字
（究→救、檔→黨），模型就唸成台灣音。

- 表格來源：docs/remaster_v2/tw_cn_diff.json 的 tts_sub（只取 SELECT 列出的字），加上 MANUAL 手動條目
  （模型單純唸錯、不是兩岸差異的：刁才弟 → diū、忽然 → gù）
- 一律一字換一字，長度不變：字幕與音檔的字數比例、讀音檢測的字位對齊都不受影響
- 刻意不收：夕（前夕；台灣口語普遍唸 ㄒㄧ，改 ㄒㄧˋ 反而怪）、識（實測已是台灣音）、片、汐
- 助詞「著」→「着」不在這裡：要在 OpenCC t2s 之後做（t2s 不轉「著」），見 cosy_tts.tts_text
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DIFF_JSON = Path(__file__).resolve().parents[2] / "docs" / "remaster_v2" / "tw_cn_diff.json"

# 從 tw_cn_diff.json 取用的字（皆為 conf high/mid、本作品實測唸成大陸音的）
SELECT = ("期", "究", "檔", "褐", "跡", "蹟", "微", "突")
# 手動條目（詞優先於字）；專名與個別誤讀
MANUAL = {"刁才弟": "雕才弟", "忽然": "呼然"}
# whisper 回聽多半吐簡體：CER 比對時簡體字形也要照表換
SIMPLIFIED = {"檔": "档", "跡": "迹", "蹟": "迹"}


@lru_cache(maxsize=1)
def table() -> dict[str, str]:
    """{原文字詞: 送 TTS 字詞}；長度一定相等。tw_cn_diff.json 不在時只用 MANUAL。"""
    subs: dict[str, str] = {}
    if DIFF_JSON.exists():
        diff = json.loads(DIFF_JSON.read_text(encoding="utf-8"))
        for k in SELECT:
            sub = (diff.get(k) or {}).get("tts_sub")
            if sub:
                subs[k] = sub
    subs.update(MANUAL)
    for k, v in subs.items():
        assert len(k) == len(v), f"替換必須一字對一字：{k}→{v}"
    return subs


def to_tts(text: str, subs: dict[str, str] | None = None) -> str:
    """原文 → 送 TTS 的文字（繁體，之後才 t2s）。長詞先換，已換過的位置不重複換。"""
    subs = table() if subs is None else subs
    out = list(text)
    done = [False] * len(text)
    for k in sorted(subs, key=len, reverse=True):
        start = text.find(k)
        while start >= 0:
            span = range(start, start + len(k))
            if not any(done[i] for i in span):
                for i, ch in zip(span, subs[k]):
                    out[i], done[i] = ch, True
            start = text.find(k, start + 1)
    return "".join(out)


def for_cer(text: str) -> str:
    """CER 比對用的正規化：參考稿與 whisper 轉寫都過一次，台灣音的替代字才不會被當成唸錯。
    whisper 聽到正確的「究竟」「档案」也會換成「救竟」「黨案」，跟參考稿一致。"""
    subs = dict(table())
    for k, v in list(subs.items()):
        simp = "".join(SIMPLIFIED.get(c, c) for c in k)
        subs.setdefault(simp, v)
    return to_tts(text, subs).replace("著", "着")
