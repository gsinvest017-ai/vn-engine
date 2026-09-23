"""sign_fix 單元測試（純 CPU、不需影片與網路）：python -m pytest tools/video/test_sign_fix.py -q"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import sign_fix as S  # noqa: E402

W, H = 320, 240
QUAD = np.array([[120, 100], [200, 100], [200, 140], [120, 140]], float)
HAS_KAIU = Path(S.FONTS["kaiu"]).exists()


def texture(seed=0):
    """多尺度隨機紋理（有足夠梯度讓 ECC 追）。"""
    rng = np.random.default_rng(seed)
    t = np.zeros((H * 2, W * 2), np.float32)
    for s in (2, 5, 12):
        t += cv2.GaussianBlur(rng.standard_normal((H * 2, W * 2)).astype(np.float32), (0, 0), s) * s
    t = (t - t.min()) / (t.max() - t.min()) * 200 + 25
    return t


def true_h(i):
    """已知運動：緩推（放大）＋平移＋一點透視，並帶一點逐幀抖動。"""
    s = 1 + 0.004 * i
    tx, ty = 1.3 * i + 0.4 * np.sin(i), -0.6 * i + 0.3 * np.cos(1.7 * i)
    A = np.array([[s, 0.01 * i / 10, tx], [0, s, ty], [2e-5 * i, 0, 1]])
    c = np.array([[1, 0, -W / 2], [0, 1, -H / 2], [0, 0, 1]])
    return np.linalg.inv(c) @ A @ c


def synth_frames(n=24, fade=True):
    """把平面紋理依已知 homography 投影成 n 幀（含淡出），回傳 BGR 幀與每幀真值 H（第 0 幀座標→第 i 幀）。"""
    tex = texture()
    off = np.array([[1, 0, W / 2], [0, 1, H / 2], [0, 0, 1]], float)   # 紋理中央對齊畫面
    frames, Hs = [], []
    M0 = true_h(0) @ off
    for i in range(n):
        Mi = true_h(i) @ off                                   # frame_i(x) = tex(Mi x)
        g = cv2.warpPerspective(tex, Mi, (W, H), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_LINEAR)
        g = g * (1 - 0.3 * i / n if fade else 1)
        frames.append(np.clip(np.dstack([g * 0.8, g * 0.9, g]), 0, 255).astype(np.uint8))
        Hs.append(np.linalg.inv(Mi) @ M0)                      # 第 0 幀座標 → 第 i 幀座標
    return frames, Hs


def spec(**kw):
    o = {"id": "T1", "mode": "replace", "text": "神恩", "anchors": [{"frame": 0, "quad": QUAD.tolist()}],
         "track": {"pad": 20, "smooth": 5}}
    o.update(kw)
    return {"clip": "x.mp4", "objects": [o]}


def test_parse_spec_defaults_and_order():
    s = S.parse_spec(spec(anchors=[{"t": 2.0, "quad": QUAD.tolist()}, {"t": 0.5, "quad": QUAD.tolist()}],
                          base_anchor=0))
    o = s["objects"][0]
    assert o["font"] == "kaiu" and o["blend"] == "strokes" and o["track"]["min_cc"] == 0.6
    assert [a["t"] for a in o["anchors"]] == [0.5, 2.0]
    assert o["base_anchor"] == 1                         # 排序後仍指向原本的 t=2.0
    assert S.anchor_frame(o["anchors"][1], 24, 100) == 48
    assert S.frame_range(o, 24, 100) == (0, 99)
    assert S.frame_range({**o, "range": [1, 99]}, 24, 100) == (24, 99)


@pytest.mark.parametrize("bad", [
    {"mode": "blur"}, {"text": ""}, {"anchors": []}, {"direction": "x"},
    {"anchors": [{"t": 0, "quad": [[0, 0], [1, 1], [2, 2]]}]},
    {"anchors": [{"t": 0, "quad": [[0, 0], [1, 1], [2, 2], [3, 3]]}]},
    {"anchors": [{"quad": QUAD.tolist()}]}, {"text_box": [0.5, 0, 0.4, 1]},
])
def test_parse_spec_rejects(bad):
    with pytest.raises(ValueError):
        S.parse_spec(spec(**bad))


def test_track_plane_error_under_1_5px():
    frames, Hs = synth_frames()
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    est, cc = S.track_plane(grays, 0, QUAD, 0, len(frames) - 1, pad=30)
    errs = [np.linalg.norm(S._persp(est[i], QUAD) - S._persp(Hs[i], QUAD), axis=1).max()
            for i in range(len(frames))]
    assert max(errs) < 1.5, errs
    assert min(cc.values()) > 0.9


def test_track_from_middle_keyframe_and_two_anchors():
    frames, Hs = synth_frames()
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    k1, k2 = 8, 20
    q1, q2 = S._persp(Hs[k1], QUAD), S._persp(Hs[k2], QUAD)
    o = S.parse_spec(spec(anchors=[{"frame": k1, "quad": q1.tolist()}, {"frame": k2, "quad": q2.tolist()}],
                          track={"pad": 30, "smooth": 5}))["objects"][0]
    tk = S.track_object(o, grays, 24)
    truth = np.array([S._persp(Hs[i], QUAD) for i in tk["frames"]])
    assert np.linalg.norm(tk["corners"] - truth, axis=-1).max() < 1.5
    assert tk["stats"]["anchor_disagree_px"][0] < 1.0
    assert tk["stats"]["low_conf_frames"] == []


def test_static_track_is_constant():
    frames, _ = synth_frames(6)
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    o = S.parse_spec(spec(track={"static": True}))["objects"][0]
    tk = S.track_object(o, grays, 24)
    assert np.allclose(tk["corners"], QUAD)


def test_stroke_mask_and_fill():
    patch = np.full((80, 200, 3), (40, 30, 150), np.float32)
    patch[30:50, 20:180] = (60, 180, 220)                      # 一條金色「筆畫」
    m, thr = S.stroke_mask(patch)
    assert m[40, 100] and not m[5, 5] and thr >= 12
    filled = S.fill_background(patch, cv2.dilate(m.astype(np.uint8), np.ones((5, 5))) > 0, 4)
    assert np.abs(filled[40, 100] - (40, 30, 150)).max() < 10


@pytest.mark.skipif(not HAS_KAIU, reason="沒有標楷體")
def test_render_glyphs_layout():
    a = S.render_glyphs("神恩浩蕩", 400, 100, "kaiu")
    assert a.shape == (100, 400) and a.max() > 0.9
    cols = a.max(0) > 0.5
    for k in range(4):                                         # 四個字格都有墨
        assert cols[k * 100:(k + 1) * 100].any()
    v = S.render_glyphs("翰溪壇", 60, 240, "kaiu", direction="v")
    assert all((v[k * 80:(k + 1) * 80].max() > 0.5) for k in range(3))
    r = S.render_glyphs("一二", 200, 100, "kaiu", order="rtl")
    l = S.render_glyphs("一二", 200, 100, "kaiu", order="ltr")
    assert np.allclose(r[:, :100], l[:, 100:]) and not np.allclose(r, l)   # rtl 把字序反過來


@pytest.mark.skipif(not HAS_KAIU, reason="沒有標楷體")
@pytest.mark.parametrize("mode", ["replace", "erase", "defocus"])
def test_apply_object_no_nan_same_shape(mode):
    frames, Hs = synth_frames(10)
    o = S.parse_spec(spec(mode=mode, protect_luma=240 if mode == "replace" else None))["objects"][0]
    out, tk, stats = S.apply_object(frames, o, 24)
    assert len(out) == len(frames)
    for a, b in zip(out, frames):
        assert a.shape == b.shape and a.dtype == np.uint8
        assert np.isfinite(a.astype(np.float32)).all()
    changed = np.abs(out[5].astype(int) - frames[5].astype(int)).max(-1) > 0
    assert changed.any()
    ys, xs = np.nonzero(changed)
    corners = S._persp(Hs[5], QUAD)
    assert xs.min() >= corners[:, 0].min() - 15 and xs.max() <= corners[:, 0].max() + 15  # 只動物件附近
    assert stats["cc_min"] > 0.9


def test_feather_and_canvas():
    cw, ch = S.canvas_size(QUAD, 4)
    assert (cw, ch) == (320, 160)
    e = S._feather_edges(cw, ch, 8)
    assert e[ch // 2, cw // 2] == 1 and e[0, 0] < 0.1


def test_init_from_hanzi(tmp_path):
    import json
    rep = {"items": [{"id": "H999", "clip": "c.mp4", "object_type": "匾額", "seen_text": "x", "object_motion": "固定",
                      "fix": "a", "suggested_text": "翰溪壇", "src_sec": [2.5, 12.0], "bbox_first": [1, 2, 30, 12],
                      "bbox_traj_sampled": [[2.5, 0, 1, 2, 30, 12], [5.0, 0, 3, 2, 32, 12], [12.0, 0, 5, 4, 36, 16]]}]}
    p = tmp_path / "h.json"
    p.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    o = S.init_from_hanzi("H999", p, n_anchors=2)
    assert o["text"] == "翰溪壇" and o["font"] == "kaiu" and o["mode"] == "replace"
    assert [a["t"] for a in o["anchors"]] == [2.5, 12.0]
    assert o["anchors"][1]["quad"] == [[5, 4], [36, 4], [36, 16], [5, 16]]
    S.parse_spec({"clip": "c.mp4", "objects": [o]})             # 草稿本身要能通過解析


def sign_frame(gain_bg=1.0, gain_txt=1.0):
    """紅底金字的合成招牌（字＝兩條橫筆），可分別調底與字的亮度。"""
    f = np.full((H, W, 3), (30, 30, 140), np.float32) * gain_bg
    f[112:118, 128:192] = np.float32((60, 180, 220)) * gain_txt
    f[124:130, 128:192] = np.float32((60, 180, 220)) * gain_txt
    rng = np.random.default_rng(0)
    return np.clip(f + rng.normal(0, 2, f.shape), 0, 255).astype(np.uint8)


@pytest.mark.skipif(not HAS_KAIU, reason="沒有標楷體")
def test_frame_gain_separates_text_and_background():
    o = S.parse_spec(spec())["objects"][0]
    P = S.build_patch(o, sign_frame(), QUAD)
    g = S.frame_gain(sign_frame(0.5, 0.8), QUAD, P, o["upscale"]) / S.frame_gain(sign_frame(), QUAD, P, o["upscale"])
    assert g.shape == (2, 3)
    assert np.allclose(g[0], 0.5, atol=0.06) and np.allclose(g[1], 0.8, atol=0.08)
    assert P.info["mask_thresh"] >= 12 and P.ta is not None and P.ta.max() > 0.5


def test_stroke_width():
    m = np.zeros((60, 60), np.float32)
    m[20:28, 5:55] = 1                                         # 8px 粗的橫筆
    assert 6 <= S.stroke_width(m) <= 9
    assert S.stroke_width(np.zeros((10, 10))) == 0.0
