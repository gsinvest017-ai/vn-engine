"""narr_vc 純函式單元測試（不需 GPU、模型）：python -m pytest tools/video/test_narr_vc.py -q"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import narr_fix as F  # noqa: E402
import narr_vc as V  # noqa: E402

SR = 24000


def tone(sec, f=200.0, amp=0.3, sr=SR):
    t = np.arange(int(sec * sr)) / sr
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def test_regions_cover_chong_san():
    zh = F.zh_only(V.SENT)
    assert len(zh) == 26
    for lo, hi in V.REGIONS.values():
        assert "沖散" in zh[lo:hi]
    assert zh[slice(*V.REGIONS["sent2"])] == "它們像被暴雨沖散後重新堆積的河砂"
    assert [t["char"] for t in F.find_targets(zh)] == ["散"]


def test_backup_rel_and_once(tmp_path):
    vo = tmp_path / "video_out"
    v2 = vo / "remaster_v2"
    (v2 / "narration_fix").mkdir(parents=True)
    (vo / "narration").mkdir()
    f1 = v2 / "narration_fix" / "cands.json"
    f1.write_text("old", encoding="utf-8")
    f2 = vo / "narration" / "a.wav"
    f2.write_text("x", encoding="utf-8")
    assert V.backup_rel(f1, v2=v2, video_out=vo) == Path("narration_fix/cands.json")
    assert V.backup_rel(f2, v2=v2, video_out=vo) == Path("narration/a.wav")
    root = v2 / "backup_v2_0"
    d1 = V.backup_once(f1, dst_root=root, v2=v2, video_out=vo)
    assert d1.read_text(encoding="utf-8") == "old"
    f1.write_text("new", encoding="utf-8")
    assert V.backup_once(f1, dst_root=root, v2=v2, video_out=vo) == d1
    assert d1.read_text(encoding="utf-8") == "old"                  # 只備份一次，不覆蓋舊備份
    assert V.backup_once(vo / "narration", dst_root=root, v2=v2, video_out=vo).joinpath("a.wav").exists()
    assert V.backup_once(vo / "nope.wav", dst_root=root, v2=v2, video_out=vo) is None


def test_cut_point_finds_gap():
    y = np.concatenate([tone(0.3), np.zeros(int(0.04 * SR), np.float32), tone(0.3)])
    c = V.cut_point(y, SR, 0.25, 0.4)
    assert 0.30 * SR <= c <= 0.34 * SR
    assert V.cut_point(y, SR, 0.4, 0.25) == c                         # 反向區間也可
    assert 0 <= V.cut_point(y, SR, 0.1, 0.1) <= len(y)                # 太窄：取中點


def test_region_cuts():
    y = np.concatenate([tone(0.2), np.zeros(2400, np.float32), tone(0.2), np.zeros(2400, np.float32), tone(0.2)])
    spans = [(0.0, 0.2, 1.0), (0.3, 0.5, 1.0), (0.6, 0.8, 1.0)]
    a, b = V.region_cuts(y, SR, spans, 1, 2)
    assert 0.2 * SR <= a <= 0.3 * SR and 0.5 * SR <= b <= 0.6 * SR
    a, b = V.region_cuts(y, SR, spans, 0, 3, voiced_end=len(y) - 100)
    assert (a, b) == (0, len(y) - 100)


def test_replace_region_keeps_length_and_fades():
    base = tone(1.0)
    new = np.full(int(0.4 * SR) + 50, 0.5, np.float32)                # 長度差一點：對齊到 b−a
    a, b = int(0.3 * SR), int(0.7 * SR)
    y = V.replace_region(base, a, b, new)
    assert len(y) == len(base)
    assert np.array_equal(y[:a], base[:a]) and np.array_equal(y[b:], base[b:])
    assert abs(y[a]) < 0.01 and abs(y[b - 1]) < 0.01                 # 接點淡入淡出
    assert y[a + int(0.02 * SR)] == pytest.approx(0.5)


def test_voiced_stats_and_seam():
    lo, hi = tone(1.5, 200), tone(1.5, 3000)
    s_lo, s_hi = V.voiced_stats(lo, SR), V.voiced_stats(hi, SR)
    assert s_hi["centroid_hz"] > s_lo["centroid_hz"] + 1000
    assert V.voiced_stats(np.zeros(100, np.float32), SR) is None
    same = np.concatenate([lo, lo, lo])
    m = V.seam_metrics(same, SR, len(lo), 2 * len(lo))
    assert m["left"]["mfcc_dist"] < 1.0 and abs(m["left"]["loud_diff_db"]) < 0.5 and abs(m["jump_a_db"]) < 1.0
    diff = np.concatenate([lo, hi * 0.5, lo])
    m2 = V.seam_metrics(diff, SR, len(lo), 2 * len(lo))
    assert m2["left"]["mfcc_dist"] > m["left"]["mfcc_dist"] + 1
    assert m2["left"]["loud_diff_db"] == pytest.approx(-6.0, abs=0.5)
    assert m2["right"]["centroid_diff_hz"] > 1000
    edge = V.seam_metrics(same, SR, 0, len(lo))                        # 段落開頭：沒有左側上下文
    assert "left" not in edge and "right" in edge and "jump_a_db" not in edge


def test_cosine():
    assert V.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert V.cosine([1, 0], [0, 1]) == pytest.approx(0.0)


def test_vc_rank():
    def c(all_pass, asr, margin, sim, seam):
        return {"all_pass": all_pass, "asr": asr, "checks": [{"char": "散", "ctc_margin": margin}],
                "spk_sim_base": sim, "seam": {"left": {"mfcc_dist": seam}, "right": {"mfcc_dist": seam}}}
    cs = [c(False, "沖散", 9, 0.9, 1), c(True, "沖上", 5, 0.9, 1), c(True, "沖散", 3, 0.7, 1),
          c(True, "沖散", 3, 0.9, 5), c(True, "沖散", 3, 0.9, 1)]
    order = sorted(range(len(cs)), key=lambda i: V.vc_rank(cs[i]))
    assert order == [4, 3, 2, 1, 0]


def test_target_reading():
    pytest.importorskip("pypinyin")
    tg = F.find_targets(F.zh_only(V.SENT))[0]
    assert V.target_reading(V.SENT, "記憶在我腦中並不連續它們像被暴雨沖散後重新堆積的河沙", tg)["verdict"] == "tw"
    r = V.target_reading(V.SENT, "記憶在我腦中並不連續他們像被暴雨沖上後重新堆積的河沙", tg)
    assert r["verdict"] == "alt" and r["hyp_char"] == "上"
    assert V.target_reading(V.SENT, "記憶在我腦中並不連續", tg)["verdict"] == "missing"
    s = "我图然感到一陣寒意"
    sub = "我突然感到一陣寒意"
    tg = F.find_targets(F.zh_only(sub))[0]
    assert V.target_reading(sub, "我突然感到一陣寒意", tg)["verdict"] == "lexical"   # 寫原字：無從判斷
    assert V.target_reading(sub, s, tg)["verdict"] == "tw"                          # 寫成 tu2 的字
    assert V.target_reading(sub, "我禿然感到一陣寒意", tg)["verdict"] == "alt"


def test_cross_table_flags_disagreement():
    pytest.importorskip("pypinyin")
    meta = {"第一章_01_04:0": {"subtitle": V.SENT}}
    good = "記憶在我腦中並不連續它們像被暴雨沖散後重新堆積的河沙"
    bad = "記憶在我腦中並不連續他們像被暴雨沖上後重新堆積的河沙"
    tags = [f"{v}_{k}" for v in ("v1", "v2_0", "v2_1") for k in ("raw", "post")]
    asrs = {"whisper_medium": {"第一章_01_04:0": {t: bad for t in tags}},
            "sensevoice_small": {"第一章_01_04:0": {t: (good if t.startswith("v2_1") else bad) for t in tags}}}
    rows = V.cross_table(meta, asrs)
    assert len(rows) == 6
    dis = [r for r in rows if r["disagree"]]
    assert {(r["version"], r["kind"]) for r in dis} == {("v2_1", "raw"), ("v2_1", "post")}


def test_cand_entry_matches_narr_fix_format():
    checks = [{"char": "散", "ctc_margin": 6.3, "ctc_verdict": "pass"}]
    c = {"asr": "沖散", "cer": 0.0, "checks": checks, "all_pass": True}
    e = V.cand_entry(c, "x.wav", 10 * SR, "rewrite/a.wav")
    assert e["sec"] == 10.0 and e["rate"] == pytest.approx(2.6) and e["rate_ok"]
    assert e["margin_sum"] == pytest.approx(6.3) and e["v2_1_from"] == "rewrite/a.wav"
    bad = {**e, "file": "y.wav", "all_pass": False, "checks": [{**checks[0], "ctc_margin": -0.4, "ctc_verdict": "unsure"}],
           "margin_sum": -0.4}
    assert F.pick_best([bad, e], 10.0) == 1                         # 驗證通過的新候選會被 narr_fix 挑中


def test_family_verdicts_ignore_lexical():
    row = {"whisper_medium": {"verdict": "lexical"}, "sensevoice_small": {"verdict": "tw"},
           "paraformer_zh": {"verdict": "alt"}, "k": "x"}
    assert V.family_verdicts(row) == {"whisper": set(), "funasr": {"tw", "alt"}}


def test_summarize_and_render():
    pytest.importorskip("pypinyin")
    meta = {"第一章_01_04:0": {"subtitle": V.SENT}}
    bad = "記憶在我腦中並不連續他們像被暴雨沖上後重新堆積的河沙"
    good = "記憶在我腦中並不連續它們像被暴雨沖散後重新堆積的河沙"
    tags = [f"{v}_{k}" for v in ("v1", "v2_0", "v2_1") for k in ("raw", "post")]
    asrs = {"whisper_medium": {"第一章_01_04:0": {t: (good if t.startswith("v2_1") else bad) for t in tags}},
            "sensevoice_small": {"第一章_01_04:0": {t: bad for t in tags}}}
    table = V.cross_table(meta, asrs)
    s = V.summarize_cross(table, "raw")
    assert len(s) == 1 and s[0]["v2_1_whisper_medium"]["verdict"] == "tw" and s[0]["v2_1_disagree"]
    rep = {"asr_models": list(asrs), "summary_raw": s, "disagreements": [r for r in table if r["disagree"]],
           "chong_san": {"adopted": "a.wav", "method": "m", "final_checks": "散 ✓"}}
    md = V.render_md21(rep)
    assert "SenseVoiceSmall" in md and "**是**" in md and "沖上" not in md.split("## 兩家族")[0].split("|")[0]


def test_char_verdict_heteronyms():
    pytest.importorskip("pypinyin")
    zhe = {"char": "著", "tw": "zhe5", "alt": "zhu4"}
    assert V.char_verdict("著", zhe) == "lexical"          # 繁體「著」兼 zhe／zhù：無從判斷
    assert V.char_verdict("着", zhe) == "tw"                # 簡體「着」沒有 zhù
    assert V.char_verdict("住", zhe) == "alt" and V.char_verdict("者", zhe) == "tw"
    wei = {"char": "微", "tw": "wei2", "alt": "wei1"}
    assert V.char_verdict("維", wei) == "tw" and V.char_verdict("威", wei) == "alt"
    assert V.char_verdict("微", wei) == "lexical" and V.char_verdict("好", wei) == "other"
