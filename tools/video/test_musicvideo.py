import numpy as np
import pytest

import musicvideo as mv
from remaster import FPS, SPF, SR


def _sections():
    # 3/4、每小節 3 秒：intro 4 小節、interlude 2 小節（無 clip）、theme 8 小節、link 2 小節（無 clip，最後）
    spec = [("intro", 4), ("interlude", 2), ("theme", 8), ("link", 2)]
    secs, bars, t, b = [], [], 0.0, 1
    for name, nb in spec:
        secs.append({"name": name, "start_s": t, "end_s": t + nb * 3.0})
        for _ in range(nb):
            bars.append({"bar": b, "section": name, "start_s": t})
            b += 1
            t += 3.0
    return secs, bars, t


def test_groups_merge_sections_without_clips():
    secs, bars, total = _sections()
    pools = {"intro": ["i1", "i2"], "theme": ["t1", "t2", "t3"]}
    gs = mv.build_groups(secs, bars, pools, mv.to_frame(total))
    assert [g.name for g in gs] == ["intro", "theme"]
    assert gs[1].sections == ["interlude", "theme", "link"]      # 前面的併入下一組、尾巴併入最後一組
    assert gs[0].f0 == 0 and gs[-1].f1 == mv.to_frame(total) and gs[0].f1 == gs[1].f0
    # 候選切點都在小節線上，段落起點懲罰 0
    bar_frames = {mv.to_frame(b["start_s"]) for b in bars}
    assert all(f in bar_frames for g in gs for f, _ in g.cands)
    assert (mv.to_frame(18.0), 0.0) in gs[1].cands                 # theme 起點（第 7 小節）


def test_shot_sequence_never_repeats_adjacent():
    seq = mv.shot_sequence(["a", "b", "c"], 7)
    assert [c for c, _ in seq] == ["a", "b", "c", "a", "b", "c", "a"]
    assert all(p[0] != q[0] for p, q in zip(seq, seq[1:]))
    assert seq[3] == ("a", 1)


def test_plan_respects_caps_bars_and_reuses_when_short():
    secs, bars, total = _sections()
    pools = {"intro": ["i1", "i2"], "theme": ["t1", "t2", "t3"]}
    tf = mv.to_frame(total)
    gs = mv.build_groups(secs, bars, pools, tf)
    cap = {c: int(1.3 * 8 * FPS) for c in ["i1", "i2", "t1", "t2", "t3"]}   # 每個 clip 可用 8 秒
    shots = mv.plan_timeline(gs, pools, cap)
    mv.check_shots(shots, tf)
    bar_frames = {mv.to_frame(b["start_s"]) for b in bars} | {0, tf}
    for s in shots:
        assert s.c0 in bar_frames and s.c1 in bar_frames
        assert s.n <= cap[s.clip]
        assert s.c1 - s.c0 >= mv.to_frame(mv.MIN_SLOT_S)
    theme = [s for s in shots if s.group == "theme"]
    # theme 組 36 秒、3 個 clip 各最多 10.4 秒 → 必須重用，而且重用的是 use=1
    assert len(theme) > 3 and any(s.use == 1 for s in theme)
    assert shots[0].xl == 0 and shots[-1].xr == 0
    assert any(s.xl == mv.XF_GROUP for s in shots)                  # 組間慢溶接 1.5 秒


def test_plan_raises_when_impossible():
    secs, bars, total = _sections()
    pools = {"intro": ["i1"], "theme": ["t1"]}
    gs = mv.build_groups(secs, bars, pools, mv.to_frame(total))
    with pytest.raises(ValueError):
        mv.plan_timeline(gs, pools, {"i1": 50, "t1": 50})


def test_source_window_head_and_reuse_tail():
    s = mv.Shot("g", "c", 0, 0, 200, 0, 24)
    assert mv.source_window(s, 60, 311) == (60, 60 + s.n)
    s2 = mv.Shot("g", "c", 1, 0, 200, 24, 24)
    assert mv.source_window(s2, 60, 311) == (311 - s2.n, 311)
    long = mv.Shot("g", "c", 0, 0, 300, 24, 24)                   # 比可用段長 → 全用，交給 RIFE
    assert mv.source_window(long, 60, 311) == (60, 311)


def test_grade_desaturates_and_split_tones():
    rng = np.random.default_rng(0)
    img = rng.uniform(0, 255, (32, 32, 3)).astype(np.float32)
    def chroma(x):
        return np.abs(x - x.mean(axis=2, keepdims=True)).mean()
    neutral = mv.grade(img, 0.0, dict(mv.LOOK, amber=0, cool=0, lift=0))
    assert chroma(neutral) < chroma(img) * 0.7
    bright = np.full((8, 8, 3), 220, np.float32)
    dark = np.full((8, 8, 3), 30, np.float32)
    warm_hi = mv.grade(bright, 1.0)
    assert warm_hi[..., 2].mean() > warm_hi[..., 0].mean()       # 亮部偏琥珀（R > B）
    cool_lo = mv.grade(dark, 0.0)
    assert cool_lo[..., 0].mean() > cool_lo[..., 2].mean()       # 暗部偏藍（B > R）
    cold = mv.grade(bright, -1.0)
    assert cold[..., 0].mean() > cold[..., 2].mean()             # 冷段連亮部也偏藍
    assert mv.grade(img, 0.5).min() >= 0 and mv.grade(img, 0.5).max() <= 255


def test_defocus_only_touches_box():
    rng = np.random.default_rng(1)
    img = rng.uniform(0, 255, (120, 200, 3)).astype(np.float32)
    out = mv.defocus(img, [(80, 40, 120, 80)])
    assert np.allclose(out[:10, :10], img[:10, :10], atol=1e-3)
    assert out[55:65, 95:105].std() < img[55:65, 95:105].std() * 0.6


def test_dim_curve_and_expo_gamma():
    assert mv.dim_at(0.0, 300) == 0.0
    assert mv.dim_at(150, 300) == 1.0
    assert mv.dim_at(300, 300) == 0.0
    assert 0.3 < mv.dim_at(300 - 15, 300) < 0.4
    assert mv.expo_gamma(100, 100) == pytest.approx(1.0)
    assert mv.expo_gamma(40, 80) > 1.0                            # 太暗 → gamma > 1（變亮）
    assert mv.expo_gamma(1, 250) == mv.LOOK["expo_clamp"][1]


def test_pad_to_frames_exact():
    x = np.ones((SPF * 10 + 7, 2))
    y, nf = mv.pad_to_frames(x)
    assert nf == 11 and len(y) == 11 * SPF and y[-1].sum() == 0


def test_build_audio_levels():
    t = np.arange(SR * 12) / SR
    music = 0.3 * np.stack([np.sin(2 * np.pi * 220 * t)] * 2, 1)
    rng = np.random.default_rng(2)
    amb = rng.normal(0, 0.1, music.shape)
    mix, info = mv.build_audio(music, amb, amb_lufs=-40.0, target=-16.0, ceiling=-1.2)
    assert len(mix) == len(music)
    assert info["amb_lufs"] == pytest.approx(-40.0, abs=0.1)
    assert info["lufs"] == pytest.approx(-16.0, abs=0.3)
    assert info["true_peak_dbtp"] <= -1.0


def test_credits_cover_all_required_attributions():
    txt = mv.card_text()
    for s in mv.REQUIRED_CREDITS:
        assert s in txt, s
    names = [c[0] for c in mv.CARDS]
    assert names[0] == "title" and "credits1" in names and "credits2" in names
    ct = mv.card_times(312.0)
    assert ct[0][1] < ct[0][2] <= 30 and ct[-1][2] <= 312.0
    assert all(e - s > 2 * mv.CARD_FADE for _, s, e, _ in ct)


def test_render_card_rgba():
    pytest.importorskip("PIL")
    im = mv.render_card([("Romanze", "i", 80, 1.0, 10), ("測試", "zh", 30, 0.7, 0)], size=(640, 360))
    a = np.asarray(im)
    assert im.mode == "RGBA" and a.shape == (360, 640, 4)
    assert a[..., 3].max() > 200 and a[0, 0, 3] == 0


def test_real_project_plan():
    if not (mv.P / "visual" / "clips.json").exists():
        pytest.skip("無專案資料")
    plan = mv.make_plan()
    shots = plan["shots"]
    mv.check_shots(shots, plan["total_f"])
    bars = {mv.to_frame(b["start_s"]) for b in mv.load_inputs()[1]["bars"]} | {0, plan["total_f"]}
    assert all(s.c0 in bars for s in shots)
    for s in shots:
        a, b = mv.source_window(s, plan["head_of"][s.clip], plan["frames_of"][s.clip])
        assert s.n / (b - a) <= mv.MAX_SPEED + 1e-9
        assert a >= plan["head_of"][s.clip]
