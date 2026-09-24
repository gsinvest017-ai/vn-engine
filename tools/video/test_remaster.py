"""remaster（組裝器 v2）單元測試：純 CPU、不需 GPU/ffmpeg/網路。python -m pytest tools/video/test_remaster.py -q"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import bgm_synth as B  # noqa: E402
import remaster as R  # noqa: E402
import render  # noqa: E402


# ───────── 分段計畫 ─────────

def test_frame_bounds_are_contiguous_and_rounded():
    times = [(0.0, 10.94), (10.94, 21.88), (21.88, 30.0)]
    fb = R.frame_bounds(times)
    assert fb[0][0] == 0 and fb[-1][1] == 720
    assert all(a[1] == b[0] for a, b in zip(fb, fb[1:]))
    assert fb[0][1] == round(10.94 * 24)


def _frames_with_cut(n=40, cut=20, flash=None, seed=0):
    rng = np.random.default_rng(seed)
    a, b = rng.random((54, 96)) * 200, rng.random((54, 96)) * 200
    fr = np.stack([(a if i < cut else b) + rng.normal(0, 2, (54, 96)) for i in range(n)]).astype(np.float32)
    if flash is not None:
        fr[flash] = fr[flash] * 0.5 + 120          # 閃電：整體變亮，結構不變
    return fr


def test_cut_scores_find_real_cut_but_not_flash():
    fr = _frames_with_cut(cut=20, flash=30)
    cs = R.cut_scores(fr)
    assert R.find_inner_cuts(cs, 0, len(fr)) == [20]


def test_find_inner_cuts_ignores_edges_and_merges_neighbours():
    cs = np.ones(50)
    cs[[1, 10, 11, 48]] = 0.1
    assert R.find_inner_cuts(cs, 0, 50) == [10]


def test_flash_skip_detects_exposure_convergence():
    y = np.full(40, 20.0)
    y[10:14] = [55, 50, 40, 30]
    assert R.flash_skip(y, 10) == 4                 # 第 14 幀起回到 settle+3 以內
    assert R.flash_skip(np.full(40, 20.0), 10) == 0


def test_is_still_needs_long_run():
    mad = np.full(200, 2.0)
    assert not R.is_still(mad, 0, 200)
    mad[20:120] = 0.1
    assert R.is_still(mad, 0, 200)
    mad2 = np.full(200, 0.1)
    mad2[::20] = 3.0                                # 每 20 幀動一下：最長靜止 < 2 秒
    assert not R.is_still(mad2, 0, 200)


def test_dark_lift_monotonic_and_keeps_order():
    assert R.dark_lift(R.DARK_Y) == 1.0
    ys = [5, 10, 20, 30]
    lifts = [R.dark_lift(y) for y in ys]
    assert lifts == sorted(lifts, reverse=True) and lifts[-1] > 1.0
    out = [255 * (y / 255) ** (1 / g) for y, g in zip(ys, lifts)]
    assert out == sorted(out), "越暗的段抬完仍然比較暗"


def test_xfade_frames_in_range():
    for dy in (0, 5, 10, 30, -60):
        assert 0.4 <= R.xfade_frames(dy) / 24 <= 0.6
    assert R.xfade_frames(40) > R.xfade_frames(2)


def _spec(tag, head, secs, speed, first, last, kind, shot, part):
    return dict(tag=tag, head=head, secs=secs, speed=speed, out=secs * speed, first=first, last=last,
                kind=kind, shot=shot, part=part)


def _fake_probe(cut_at=None, n=300, y=60.0):
    def probe(tag):
        yy = np.full(n, y)
        mad = np.full(n, 2.0)
        cs = np.ones(n)
        if cut_at and tag in cut_at:
            cs[cut_at[tag]] = 0.1
        return yy, mad, cs
    return probe


def test_build_pieces_timeline_matches_plan_exactly():
    # shot 0：head(226f) → cont → cut(_t, 內部硬切)；shot 1：單段
    specs = [_spec("a", 0, 8.752, 1.25, True, False, "head", 0, 0),
             _spec("b", 0, 8.752, 1.25, False, False, "cont", 0, 1),
             _spec("c", 2.5, 9.7, 1.25, False, True, "cut", 0, 2),
             _spec("d", 0, 7.0, 1.0, True, True, "head", 1, 0)]
    times, t = [], 0.0
    for sp in specs:
        times.append((t, t + sp["out"]))
        t += sp["out"]
    nfr = {"a": 226, "b": 226, "c": 294, "d": 243}
    pcs = R.build_pieces(specs, times, [1, 1, 1, 2], _fake_probe({"c": 160}), lambda tag: nfr[tag])
    R.check_timeline(pcs, times)
    a, b = pcs[0], pcs[1]
    assert a.join_r and a.b == 226 and a.xr == 0             # 接續前一段用到檔尾
    assert b.join_l and b.a == 1 and "drop-dup-first" in b.notes
    cs = [p for p in pcs if p.tag == "c"]
    assert len(cs) == 2 and cs[0].b == cs[1].a == 160 and cs[0].xr == R.INNER_XF
    assert b.xr == cs[0].xl and 10 <= b.xr <= 14
    assert pcs[-1].fade_in and pcs[-1].fade_out and pcs[-1].xl == 0
    fb = R.frame_bounds(times)
    assert pcs[-1].t0 + pcs[-1].n == fb[-1][1]
    assert all(p.m <= p.n for p in pcs), "只會補幀（放慢），不會抽幀"


def test_build_pieces_anchor_end_uses_tail_when_file_is_long():
    # T03 k18：192f 只要 152 幀 → 從 40 開始取到檔尾，尾幀＝下一段首幀
    specs = [_spec("x", 0, 6.34, 1.0, True, False, "head", 0, 0),
             _spec("y", 0, 5.0, 1.0, False, True, "cont", 0, 1)]
    times = [(0.0, 6.34), (6.34, 11.34)]
    pcs = R.build_pieces(specs, times, [1, 1], _fake_probe(), lambda tag: {"x": 192, "y": 124}[tag])
    assert (pcs[0].a, pcs[0].b, pcs[0].n) == (40, 192, 152)


def test_build_pieces_drops_short_side_of_inner_cut():
    specs = [_spec("c", 2.5, 9.0, 1.0, True, True, "cut", 0, 0)]
    pcs = R.build_pieces(specs, [(0.0, 9.0)], [1], _fake_probe({"c": 70}), lambda tag: 294)
    assert len(pcs) == 1 and pcs[0].a == 70 and any("drop-head" in n for n in pcs[0].notes)


def test_clip_specs_match_generate_tags(tmp_path, monkeypatch):
    class FakeClient:
        def upload_image(self, path, name=None):
            return name or path.name

        def run(self, job, dest):
            dest.write_bytes(b"")
            return dest

    monkeypatch.setattr(render, "ff", lambda *a: None)
    planned = render.plan([1], 120)
    segs = render.generate(planned, tmp_path, FakeClient(), (64, 64), 1, True)
    specs = render.clip_specs(planned)
    assert [s["tag"] for s in specs] == [p.stem for p, *_ in segs]
    assert [(round(s["head"], 3), round(s["secs"], 3), s["first"], s["last"]) for s in specs] == \
           [(round(h, 3), round(sec, 3), f, l) for _, h, sec, _, f, l in segs]


# ───────── 影像小工具 ─────────

def test_blend_and_fade_weights():
    w = [R.blend_weight(k, 12) for k in range(12)]
    assert 0 < w[0] < 0.1 and 0.9 < w[-1] < 1 and w == sorted(w)
    assert R.fade_gain(0, 100, True, False) == 0 and R.fade_gain(50, 100, True, True) == 1
    assert R.fade_gain(99, 100, False, True) == 0


def test_apply_eq_identity_and_gamma_brightens():
    pytest.importorskip("cv2")
    img = np.random.default_rng(0).integers(0, 255, (16, 16, 3), dtype=np.uint8)
    assert np.array_equal(R.apply_eq(img, 1.0, 1.0), img)
    dark = np.full((8, 8, 3), 40, np.uint8)
    assert R.apply_eq(dark, 1.3, 1.0).mean() > 45
    assert np.array_equal(R.zoom_frame(img, 1.0), img)


# ───────── 音訊 ─────────

def test_xfade_curves_equal_power():
    fi, fo = R.xfade_curves(480)
    assert np.allclose(fi ** 2 + fo ** 2, 1.0)


def test_ambient_track_length_and_no_dropout(monkeypatch):
    rng = np.random.default_rng(1)
    monkeypatch.setattr(R, "decode_audio", lambda src, mono=False: rng.normal(0, 0.1, (R.SR * 13, 2)).astype(np.float32))
    monkeypatch.setattr(R, "stretch", lambda x, n, tmp: R.fit_len(x, n))
    specs = [_spec("a", 0, 5.0, 1.0, True, False, "head", 0, 0),
             _spec("b", 0, 5.0, 1.0, False, False, "cont", 0, 1),
             _spec("c", 2.5, 5.0, 1.0, False, True, "cut", 0, 2)]
    times = [(0.0, 5.0), (5.0, 10.0), (10.0, 15.0)]
    pcs = R.build_pieces(specs, times, [1] * 3, _fake_probe(), lambda tag: 294)
    n = (pcs[-1].t0 + pcs[-1].n) * R.SPF
    amb = R.ambient_track(pcs, n, Path("unused"))
    assert amb.shape == (15 * R.SR, 2)
    win = R.SR // 200                                        # 5 ms
    rms = np.sqrt((amb[: n // win * win, 0].reshape(-1, win) ** 2).mean(1))
    inner = rms[int(0.6 * 200):int(14.4 * 200)]              # 扣掉 shot 頭尾淡入淡出
    assert inner.min() > 0.05, "段落邊界不能有掉音洞"
    assert rms[0] < 0.02 and rms[-1] < 0.02                  # shot 淡入淡出


def test_sidechain_gain_ducks_only_under_speech():
    sr = R.SR
    key = np.zeros((sr * 4, 2))
    key[sr:2 * sr] = 0.1 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)[:, None]
    g = R.sidechain_gain(key, depth_db=9.0)
    assert len(g) == len(key)
    assert g[: sr // 2].min() > 0.999
    assert 20 * np.log10(g[int(1.8 * sr)]) == pytest.approx(-9.0, abs=0.5)
    assert g[-1] > 0.95                                      # release 後回來


def test_tp_limit_caps_true_peak():
    t = np.arange(R.SR) / R.SR
    x = np.stack([1.4 * np.sin(2 * np.pi * 997 * t)] * 2, axis=1)
    y = R.tp_limit(x, -2.0)
    assert 20 * np.log10(R.tp_peak_env(y).max()) <= -1.9


def test_mix_audio_levels_and_length():
    rng = np.random.default_rng(2)
    n = R.SR * 20
    nar = np.zeros((n, 2))
    for s in range(2, 18, 4):                               # 間歇的「說話」
        nar[s * R.SR:(s + 2) * R.SR] = rng.normal(0, 0.05, (2 * R.SR, 1))
    amb = rng.normal(0, 0.01, (n, 2))
    bgm = rng.normal(0, 0.01, (n, 2))
    mix, info = R.mix_audio(nar, amb, bgm)
    assert mix.shape == (n, 2)
    assert info["lufs"] == pytest.approx(-17.0, abs=0.7)
    assert info["true_peak_dbtp"] <= -1.5


# ───────── 配樂參數 ─────────

def _shots():
    return [{"chapter": "第一章　測試", "title": "第一章　測試", "start": 0.0, "use_clips": [20.0, 20.0], "dim": 0.0,
             "sfx": [], "lines": [{"text": "黃昏落在舊城區。", "pause_before": 3.5, "audio_sec": 4.0, "narr_wav": "a"}]},
            {"chapter": "第三章　夜行", "title": "第三章　夜行", "start": 40.0, "use_clips": [20.0], "dim": 0.0,
             "sfx": [], "lines": [{"text": "雨。", "pause_before": 4.0, "audio_sec": 2.0, "narr_wav": "b"}]}]


def test_bgm_defaults_unchanged_and_params_apply():
    tl = B.load_timeline(_shots(), 60.0)
    a, ea, _ = B.render(tl, seed=5)
    b, eb, _ = B.render(tl, seed=5, max_silence=B.MAX_SILENCE, title_bell_vel=dict(B.TITLE_BELL_VEL))
    assert np.array_equal(a, b), "預設參數要跟原本位元相同（seed 可重現）"
    c, ec, _ = B.render(tl, seed=5, max_silence=10.0, title_bell_vel={3: 0.4})
    t3 = [e for e in ec if e.tag == "title" and e.t >= 40.0]
    assert t3 and t3[0].vel == pytest.approx(0.4)
    on = sorted(e.t for e in ec)
    gaps = np.diff([0.0] + on + [60.0 - 3.0])
    assert gaps.max() <= 10.0 + 1e-6
    d, _, _ = B.render(tl, seed=5, max_silence=10.0, title_bell_vel={3: 0.4})
    assert np.array_equal(c, d)


def test_grade_ramps_across_continuation_join():
    specs = [_spec("a", 0, 8.0, 1.0, True, False, "head", 0, 0),
             _spec("b", 0, 8.0, 1.0, False, True, "cont", 0, 1)]
    times = [(0.0, 8.0), (8.0, 16.0)]
    pcs = R.build_pieces(specs, times, [1, 1], _fake_probe(), lambda tag: 200, exposure={"b": (0.87, 1.02)})
    b = pcs[1]
    assert b.ramp_from == (1.0, 1.0)
    assert R.grade_at(b, 0) == (1.0, 1.0)
    assert R.grade_at(b, R.RAMP_F) == (0.87, 1.02)
    g = [R.grade_at(b, k)[0] for k in range(R.RAMP_F)]
    assert max(abs(x - y) for x, y in zip(g, g[1:])) < 0.01


def test_per_frame_dark_lift_follows_source_luma():
    def probe(tag):
        y = np.r_[np.full(150, 40.0), np.full(150, 7.0)]      # 片中變暗（停電）
        return y, np.full(300, 2.0), np.ones(300)
    pcs = R.build_pieces([_spec("a", 0, 12.0, 1.0, True, True, "head", 0, 0)], [(0.0, 12.0)], [3], probe, lambda t: 300)
    pc = pcs[0]
    assert pc.luma is not None
    g_early, g_late = R.grade_at(pc, 10)[0], R.grade_at(pc, 280)[0]
    assert g_early == pytest.approx(R.CH3_LIFT, rel=1e-3) and g_late > g_early * 1.3
