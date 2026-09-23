"""narr_fix 純函式單元測試（不需 GPU、模型、ComfyUI）：python -m pytest tools/video/test_narr_fix.py -q"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import narr_fix as F  # noqa: E402

SR = 24000


def test_fixes_follow_decisions():
    keys = {(k, c) for k, c, _ in F.FIXES}
    assert len(keys) == len(F.FIXES) == 20
    assert not any(k == "第一章_03_01" for k, _ in keys)          # 前夕不修
    issues = ",".join(i for *_, i in F.FIXES)
    for p in ("P01", "P02", "P03", "P04", "P05", "P06", "P10", "P11", "P12", "P14", "P15", "P16", "P17",
              "P18", "P20", "P21", "P22", "P23", "P25", "P26", "P27", "P28", "P29"):
        assert p in issues
    assert "P08" not in issues


def test_fixes_match_pronunciation_report():
    rep = F.ROOT / "docs" / "remaster_v2" / "pronunciation.json"
    if not rep.exists():
        pytest.skip("沒有讀音檢測報告")
    rs = {(r["block"], r["chunk_index"]) for r in json.loads(rep.read_text(encoding="utf-8"))["resynth_sentences"]}
    assert {(k, c) for k, c, _ in F.FIXES} == rs - {("第一章_03_01", 0)}


def test_find_targets():
    zh = F.zh_only("有時我會忘記自己究竟是誰。徐尋尋。廖啟祥。")
    t = F.find_targets(zh)
    assert [(x["char"], x["tw"], x["method"]) for x in t] == [("究", "jiu4", "tone"), ("尋", "xun2", "ctc")]
    assert zh[t[1]["i"]] == "尋" and zh[t[1]["i"] - 1] == "尋"      # 第二個「尋」
    t = F.find_targets(F.zh_only("對面的刁才弟忽然問我："))
    assert [(x["char"], x["method"]) for x in t] == [("刁", "ctc"), ("忽", "both")]
    assert F.find_targets("沒有要檢查的字") == []


def test_verdicts():
    assert F.tone_verdict(0.9) == "pass" and F.tone_verdict(0.1) == "fail" and F.tone_verdict(0.5) == "unsure"
    assert F.ctc_verdict(3.0) == "pass" and F.ctc_verdict(-3.0) == "fail" and F.ctc_verdict(0.2) == "unsure"
    assert F.check_ok({"tone_verdict": "pass", "ctc_verdict": "pass"})
    assert not F.check_ok({"tone_verdict": "pass", "ctc_verdict": "unsure"})
    assert not F.check_ok({})


def test_stretch_plan():
    tempo, out, clamped = F.stretch_plan(11.0, 10.0)
    assert tempo == pytest.approx(1.1) and out == pytest.approx(10.0) and not clamped
    tempo, out, clamped = F.stretch_plan(13.0, 10.0)                  # 太長：只加速到 1.18
    assert tempo == 1.18 and out == pytest.approx(13.0 / 1.18) and clamped
    tempo, out, clamped = F.stretch_plan(8.0, 10.0)                   # 太短：只放慢到 0.85
    assert tempo == 0.85 and out == pytest.approx(8.0 / 0.85) and clamped


def cand(sec, cer=0.0, ok=True, rate_ok=True, margin=0.0):
    chk = [{"tone_verdict": "pass" if ok else "fail"}]
    return {"sec": sec, "cer": cer, "rate_ok": rate_ok, "checks": chk, "margin_sum": margin}


def test_pick_best_priorities():
    orig = 10.0
    # 驗證失敗的輸給通過的，即使長度更準
    assert F.pick_best([cand(10.0, ok=False), cand(11.0)], orig) == 1
    # 漏字（CER 高）的比讀音失敗的更糟
    assert F.pick_best([cand(10.0, cer=0.3), cand(10.0, ok=False)], orig) == 1
    # 語速異常最先淘汰
    assert F.pick_best([cand(10.0, rate_ok=False), cand(10.0, ok=False, cer=0.3)], orig) == 1
    # 長度拉不回原長的排後面
    assert F.pick_best([cand(14.0), cand(10.5, cer=0.05)], orig) == 1
    # 都過驗證時，變速少的贏過聲學邊際大的
    assert F.pick_best([cand(11.2, margin=9.0), cand(10.1, margin=1.0)], orig) == 1
    # 全部都沒過驗證時，挑最接近台灣音的（邊際大），不管長度
    assert F.pick_best([cand(10.0, ok=False, margin=-6.0), cand(9.2, ok=False, margin=-0.4)], orig) == 1
    # 都一樣時聲學邊際大的贏
    assert F.pick_best([cand(10.0, margin=1.0), cand(10.0, margin=5.0)], orig) == 1


def fake_raw(lengths, sr=SR, gap=F.SENT_GAP):
    rng = np.random.default_rng(0)
    parts = []
    for i, n in enumerate(lengths):
        parts.append((rng.uniform(0.05, 0.3, int(n * sr)) * rng.choice([-1, 1], int(n * sr))).astype(np.float32))
        if i < len(lengths) - 1:
            parts.append(np.zeros(int(gap * sr), np.float32))
    return np.concatenate(parts)


def test_chunk_spans_and_splice_keep_timeline():
    x = fake_raw([2.0, 1.5, 3.0])
    spans = F.chunk_spans(x, SR, 3)
    assert [round((e - s) / SR, 2) for s, e in spans] == [2.0, 1.5, 3.0]
    with pytest.raises(ValueError):
        F.chunk_spans(x, SR, 2)
    s, e = spans[1]
    new = np.full(e - s, 0.5, np.float32)
    y = F.splice(x, [(s, e, new)])
    assert len(y) == len(x)
    assert np.array_equal(y[:s], x[:s]) and np.array_equal(y[e:], x[e:])
    n = int(F.FADE * SR)
    assert 0 < y[s] < 0.01 and 0 < y[e - 1] < 0.01 and y[s + n] == pytest.approx(0.5)   # 10 ms 淡入淡出
    assert F.chunk_spans(y, SR, 3) == spans                            # 句間 0.35 s 全 0 仍在


def test_splice_multiple_with_length_change():
    x = fake_raw([1.0, 1.0, 1.0])
    spans = F.chunk_spans(x, SR, 3)
    (s0, e0), (s2, e2) = spans[0], spans[2]
    y = F.splice(x, [(s0, e0, np.ones(e0 - s0 + 2400, np.float32)), (s2, e2, np.ones(e2 - s2, np.float32))])
    assert len(y) == len(x) + 2400
    assert np.array_equal(y[e0 + 2400: s2 + 2400], x[e0:s2])          # 中間那句原封不動、整體後移


def test_fit_length_and_post_span():
    y = np.ones(100, np.float32)
    assert len(F.fit_length(y, 90)) == 90
    z = F.fit_length(y, 110)
    assert len(z) == 110 and z[-1] == 0
    assert F.post_span((1.1, 2.2), 0.1, 1.1) == pytest.approx((1 / 1.1, 2.1 / 1.1))
    x = np.zeros(SR, np.float32)
    x[SR // 2:] = 0.1
    assert F.lead_trim(x, SR) == pytest.approx(0.5)


def test_clip_tags_reproduce_v1_cache():
    """v1 分鏡算出的快取檔名必須全部在 video_out/clips/：證明 clip_tags 跟 render.generate 的命名一致。"""
    import render
    backup = F.BACKUP if (F.BACKUP / "narration.json").exists() else F.NARR
    if not (backup / "narration.json").exists() or not F.CLIPS.exists():
        pytest.skip("沒有旁白或 clip 快取")
    saved = render.NARR_DIR
    render.NARR_DIR = backup
    try:
        planned = render.plan([1, 2, 3], None, render.load_narration())
    finally:
        render.NARR_DIR = saved
    tags = F.clip_tags(planned)
    assert len(tags) == sum(len(p.clips) for p in planned)
    assert [t for t in tags if not (F.CLIPS / f"{t}.mp4").exists()] == []


def test_rebuild_keeps_v1_head_tail_silence():
    v1 = np.concatenate([np.full(2400, 1e-4), np.full(4800, 0.3), np.full(1200, 2e-4)]).astype(np.float32)
    assert F.voiced_bounds(v1) == (2400, 7200)
    assert F.voiced_bounds(np.zeros(10, np.float32)) == (0, 10)
    # 開頭 0.1 s 的喀聲（短於 0.15 s）不算有聲，跟 narr_post 的 silenceremove 一樣會被修掉
    click = np.concatenate([np.full(2400, 0.3), np.zeros(4800), np.full(12000, 0.3), np.zeros(2400)]).astype(np.float32)
    assert F.voiced_bounds(click) == (7200, 19200)
    new = F.rebuild(v1, np.full(4800, 0.5, np.float32))
    assert len(new) == len(v1)
    assert np.array_equal(new[:2400], v1[:2400]) and np.array_equal(new[-1200:], v1[-1200:])
    a, b = F.voiced_bounds(new)                                       # 後製修剪量不變（淡入誤差 < 1 ms）
    assert abs(a - 2400) <= 24 and abs(b - 7200) <= 24
    assert len(F.rebuild(v1, np.full(6000, 0.5, np.float32))) == len(v1) + 1200


def test_calib_residuals():
    choice = {"A:0": {"intended_delta_sec": 0.0}, "A:2": {"intended_delta_sec": 0.0},
              "B:0": {"intended_delta_sec": -0.33}}
    r = F.calib_residuals({"A": 10.0, "B": 5.0}, {"A": 9.9, "B": 4.5}, choice, {"A": 1.1, "B": 1.1})
    assert set(r) == {"A:2", "B:0"}                                   # 記在該段最後一句
    assert r["A:2"] == pytest.approx((0.1 + F.CALIB_BIAS) * 1.1)
    assert r["B:0"] == pytest.approx((5.0 - 0.3 + F.CALIB_BIAS - 4.5) * 1.1)


def test_match_level():
    ref = np.full(1000, 0.2, np.float32)
    y = F.match_level(np.full(500, 0.05, np.float32), ref)
    assert np.sqrt(np.mean(y ** 2)) == pytest.approx(0.2, rel=1e-5)
    y = F.match_level(np.array([0.01, 0.5], np.float32), np.full(10, 0.9, np.float32))   # 軟限幅：不破 1
    assert np.abs(y).max() < 1.0
    z = F.soft_limit(np.array([0.5, -0.7, 0.9, -3.0], np.float32))
    assert z[0] == 0.5 and z[1] == pytest.approx(-0.7) and 0.8 < z[2] < 0.9 and -0.99 <= z[3] < -0.8
    assert np.array_equal(F.match_level(np.zeros(5, np.float32), ref), np.zeros(5))
