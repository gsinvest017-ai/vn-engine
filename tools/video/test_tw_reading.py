"""tw_reading / cosy_tts.tts_text 單元測試（純文字、不需模型）：python -m pytest tools/video/test_tw_reading.py -q"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import cosy_tts  # noqa: E402
import tw_reading as T  # noqa: E402


def test_table_is_one_to_one_and_from_diff_json():
    tab = T.table()
    assert all(len(k) == len(v) for k, v in tab.items())
    # 從 tw_cn_diff.json 取的
    assert tab["究"] == "救" and tab["檔"] == "黨" and tab["期"] == "其" and tab["褐"] == "合"
    assert tab["突"] == "圖" and tab["微"] == "維" and tab["跡"] == "機"
    # 手動條目
    assert tab["刁才弟"] == "雕才弟" and tab["忽然"] == "呼然"
    # 依決策不收：前夕（台灣口語 ㄒㄧ）、實測已是台灣音的字
    for k in ("夕", "識", "汐", "片"):
        assert k not in tab


def test_to_tts_examples_from_report():
    cases = {
        "有時我會忘記自己究竟是誰。": "有時我會忘記自己救竟是誰。",
        "律川整治工程期間深夜不停運轉的抽水機；某份刑案卷宗裡一張失焦的黑白照片。":
            "律川整治工程其間深夜不停運轉的抽水機；某份刑案卷宗裡一張失焦的黑白照片。",
        "對面的刁才弟忽然問我：": "對面的雕才弟呼然問我：",
        "我從桌下翻出那本舊檔案。紙頁邊緣呈現長久浸水後特有的深褐色。":
            "我從桌下翻出那本舊黨案。紙頁邊緣呈現長久浸水後特有的深合色。",
        "字跡斷斷續續": "字機斷斷續續",
        "只剩遠處便利商店的綠色招牌仍微弱亮著。": "只剩遠處便利商店的綠色招牌仍維弱亮著。",
        "我突然感到一陣難以形容的寒意。": "我圖然感到一陣難以形容的寒意。",
        "特別是颱風前夕": "特別是颱風前夕",
    }
    for src, want in cases.items():
        got = T.to_tts(src)
        assert got == want
        assert len(got) == len(src)


def test_to_tts_longer_entry_wins_and_no_double_replace():
    subs = {"忽然": "呼然", "忽": "X", "ab": "ba"}
    assert T.to_tts("忽然忽", subs) == "呼然X"
    assert T.to_tts("abab", subs) == "baba"


def test_for_cer_normalizes_both_spellings():
    assert T.for_cer("旧档案") == T.for_cer("旧黨案") == "旧黨案"        # whisper 吐簡體「档」
    assert T.for_cer("字迹") == "字機" and T.for_cer("究竟") == "救竟"
    assert T.for_cer("沿著") == T.for_cer("沿着") == "沿着"


def test_for_cer_accepts_correct_whisper_spelling():
    pytest.importorskip("pypinyin")
    ref = "有時我會忘記自己究竟是誰"
    # whisper 聽對了會寫原字或簡體；聽成替代字也一樣算對
    for hyp in ("有时我会忘记自己究竟是谁", "有时我会忘记自己救竟是谁"):
        assert cosy_tts.cer(hyp, ref) == 0.0
    assert cosy_tts.cer("我从桌下翻出那本旧档案", "我從桌下翻出那本舊檔案") == 0.0
    assert cosy_tts.cer("湿气沿着墙角", "濕氣沿著牆角") == 0.0
    # 真的唸錯（刁→丟）還是要算錯
    assert cosy_tts.cer("对面的丢才弟忽然问我", "對面的刁才弟忽然問我") > 0


def test_tts_text_pipeline_order():
    t2s = str.maketrans({"黨": "党", "濕": "湿", "氣": "气", "沿": "沿"})
    out = cosy_tts.tts_text("「濕氣沿著舊檔案……」", lambda s: s.translate(t2s))
    assert out == "湿气沿着舊党案"                         # 去符號 → 替換 → t2s → 著→着
    assert cosy_tts.Narrator.speakable("……庄民掘地") == "庄民掘地"
