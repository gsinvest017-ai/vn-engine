"""narr_dang 純函式單元測試（不需 GPU、模型）：python -m pytest tools/video/test_narr_dang.py -q"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import narr_dang as D  # noqa: E402
import narr_fix as F  # noqa: E402


def test_variants_same_syllables():
    # 每種寫法去掉標點後字數與字幕相同（Checker 用字幕對齊，字數不能變）
    n = len(F.zh_only(D.SENT))
    for text in D.VARIANTS.values():
        assert len(F.zh_only(text)) == n
        assert F.zh_only(text)[0] in D.DANG_CHARS
    assert [t["char"] for t in F.find_targets(F.zh_only(D.SENT))] == ["檔", "跡"]


def test_dang_votes():
    pytest.importorskip("pypinyin")
    asr = {"whisper_medium": "火案裏最早的文字寫於乾隆年間字跡斷斷續續",
           "sensevoice_small": "🎼档案里最早的文字写于乾隆年间字迹断断续续",
           "paraformer_zh": "挡案里最早的文字写于乾隆年间"}
    votes, chars = D.dang_votes(asr)
    assert votes == 2
    assert chars == {"whisper_medium": "火", "sensevoice_small": "档", "paraformer_zh": "挡"}


def _cand(votes, tone_pred, p, ji_ok=True, sec=14.0):
    checks = [{"char": "檔", "tone_pred": tone_pred, "p_tw_tone": p, "tone_verdict": F.tone_verdict(p)},
              {"char": "跡", "p_tw_tone": 0.99 if ji_ok else 0.1,
               "tone_verdict": "pass" if ji_ok else "fail"}]
    return {"checks": checks, "all_pass": all(F.check_ok(c) for c in checks), "rate_ok": True, "cer": 0.03,
            "sec": sec, "dang_votes": votes, "margin_sum": 0.0}


def test_tier_and_choose():
    full = _cand(2, 3, 0.95)
    tone4 = _cand(3, 4, 0.1)
    huo = _cand(1, 3, 0.99)
    assert D.tier(full, 0.1, 14.0) == 0
    assert D.tier(tone4, 0.1, 14.0) == 1
    assert D.tier(huo, 0.1, 14.0) == 3
    assert D.tier(_cand(2, 3, 0.95, ji_ok=False), 0.1, 14.0) == 2
    # 優先保 dang：沒有 tier 0 時選 dang 票數夠但聲調是 4 聲的，不選唸成「火」的
    assert D.choose([huo, tone4], 14.0, 0.1) == (1, 1)
    assert D.choose([huo, tone4, full], 14.0, 0.1) == (2, 0)


def test_consensus_errors():
    pytest.importorskip("pypinyin")
    asr = {"whisper_medium": "檔案密最早的文字寫於乾隆年間字跡斷斷續續",
           "sensevoice_small": "档案例最早的文字写于乾隆年间至今断断续续",
           "paraformer_zh": "档案密最早的文字写于乾隆年间字迹断断续续"}
    ref = "檔案裡最早的文字寫於乾隆年間。字跡斷斷續續"
    assert D.consensus_errors(asr, ref) == [2]            # 裡：三套都寫成別的音；跡→今 只有一套，不算


def test_tier_uses_final_checks():
    c = _cand(3, 2, 0.98)                                  # 候選本身判 2 聲
    assert D.tier(c, 0.1, 14.0) == 1
    c["final_checks"] = _cand(3, 3, 0.99)["checks"]        # 拼回後判 3 聲
    assert D.tier(c, 0.1, 14.0) == 0
    c["consensus_errors"] = [2]
    assert D.tier(c, 0.1, 14.0) == 2
