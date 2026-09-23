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


@pytest.mark.skipif(not HAS_KAIU, reason="沒有標楷體")
def test_occlusion_keeps_foreground():
    """occlusion 開啟時，後來擋在招牌前的桿子保持原樣；招牌其他地方照常換字。預設（關閉）行為不變。"""
    clean = sign_frame()
    occl = clean.copy()
    occl[95:145, 150:162] = (150, 160, 165)                    # 灰色桿子擋住字的中段
    frames = [clean, clean, occl]
    base = {"anchors": [{"frame": 0, "quad": QUAD.tolist()}], "track": {"static": True}}
    o_on = S.parse_spec(spec(**base, occlusion={"thresh": 40}))["objects"][0]
    o_off = S.parse_spec(spec(**base))["objects"][0]
    assert o_on["occlusion"]["dilate"] == 2.0 and o_off["occlusion"] is None
    on, _, st = S.apply_object(frames, o_on, 24)
    off, _, _ = S.apply_object(frames, o_off, 24)
    bar = (slice(100, 140), slice(152, 160))
    assert np.abs(on[2][bar].astype(int) - occl[bar].astype(int)).max() <= 2      # 桿子沒被蓋
    assert np.abs(off[2][bar].astype(int) - occl[bar].astype(int)).max() > 20     # 關閉時會蓋到桿子
    left = (slice(110, 132), slice(128, 145))
    assert np.abs(on[2][left].astype(int) - occl[left].astype(int)).max() > 20    # 其他筆畫照常修補
    assert st["occluded_frac_max"] > 0


def test_sane_h_rejects_degenerate():
    """ECC／SIFT 偶爾回傳奇異或翻轉的 homography，追蹤要改用預測而不是崩潰。"""
    assert S._sane_h(np.eye(3))
    assert not S._sane_h(np.zeros((3, 3)))
    assert not S._sane_h(np.diag([1.0, -1.0, 1.0]))            # 翻轉
    assert not S._sane_h(np.array([[1, 0, 0], [0, 1, 0], [0, 0, np.nan]]))


@pytest.mark.skipif(not HAS_KAIU, reason="沒有標楷體")
def test_protect_color_keeps_red_slash():
    """protect_color：禁止標誌的紅斜槓不被當成字抹掉，合成後仍在原位。"""
    f = np.full((H, W, 3), 235, np.uint8)
    f[108:132, 150:156] = 20                                   # 黑色假字筆畫
    for k in range(80):                                       # 紅斜槓（BGR）
        cv2.circle(f, (120 + k, 100 + k // 2), 2, (40, 40, 190), -1)
    o = S.parse_spec(spec(text="停", anchors=[{"frame": 0, "quad": QUAD.tolist()}], track={"static": True},
                          protect_color={"rgb": [190, 40, 40], "dist": 45}))["objects"][0]
    out, _, _ = S.apply_object([f, f], o, 24)
    red = (np.abs(f.astype(int) - (40, 40, 190)).max(-1) < 5)
    assert np.abs(out[1][red].astype(int) - f[red].astype(int)).max() <= 3
    assert np.abs(out[1].astype(int) - f.astype(int)).max() > 20              # 其他地方有換字


# ───── 第 5 批新增選項（mask_mode=dark、text_rel、錨點 poly、text_gain=bg、occlusion.close、track_on=orig）─────

def dark_sign(shade=True):
    """暗紅布上的墨字（兩條橫筆），左半有陰影漸層：Lab 距離門檻會把陰影當字，dark 模式不會。"""
    f = np.full((H, W, 3), (25, 25, 110), np.float32)
    if shade:
        f[:, :160] *= np.linspace(0.45, 1.0, 160)[None, :, None]
    f[112:118, 128:192] *= 0.3
    f[124:130, 128:192] *= 0.3
    return np.clip(f, 0, 255).astype(np.uint8)


def test_dark_mask_finds_ink_not_shadow():
    q = QUAD
    cw, ch = S.canvas_size(q, 4)
    src = S.rectify(dark_sign(), q, cw, ch).astype(np.float32)
    m, thr = S.dark_mask(src)
    assert 0.05 < m.mean() < 0.5 and 0 < thr < 1
    rows = m.mean(1)
    ink = rows[int(ch * 12 / 40):int(ch * 18 / 40)].mean()     # 第一條橫筆所在列
    gap = rows[int(ch * 19 / 40):int(ch * 23 / 40)].mean()     # 兩筆之間的底色
    assert ink > 0.7 and gap < 0.1
    m2, _, dist = S.dark_mask(src, return_dist=True)
    assert dist.shape == m2.shape and dist.max() <= 100


@pytest.mark.skipif(not HAS_KAIU, reason="沒有標楷體")
def test_mask_mode_dark_and_text_rel():
    base = {"anchors": [{"frame": 0, "quad": QUAD.tolist()}], "track": {"static": True}}
    o = S.parse_spec(spec(**base, mask_mode="dark", text_rel=0.3))["objects"][0]
    assert S.parse_spec(spec())["objects"][0]["mask_mode"] == "lab"            # 預設不變
    P = S.build_patch(o, dark_sign(), QUAD)
    assert P.info["text_rel"] == 0.3
    lum = lambda c: float(np.asarray(c).reshape(-1, 3).mean(0) @ np.float32([0.114, 0.587, 0.299]))
    assert lum(P.tex) < 0.5 * lum(P.rgb)                        # 字色＝底色 × 0.3 左右
    o2 = S.parse_spec(spec(**base, mask_mode="dark", text_rel="auto"))["objects"][0]
    assert 0.02 <= S.build_patch(o2, dark_sign(), QUAD).info["text_rel"] < 1.0


def test_anchor_poly_overrides_track_poly():
    frames, _ = synth_frames(6, fade=False)
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    far = [[0, 0], [30, 0], [30, 30], [0, 30]]                   # 圈到畫面角落（錯的平面）
    o_bad = S.parse_spec(spec(track={"pad": 20, "smooth": 5, "poly": far}))["objects"][0]
    o_fix = S.parse_spec(spec(anchors=[{"frame": 0, "quad": QUAD.tolist(),
                                        "poly": (QUAD + [[-20, -20], [20, -20], [20, 20], [-20, 20]]).tolist()}],
                              track={"pad": 20, "smooth": 5, "poly": far}))["objects"][0]
    assert S.track_object(o_fix, grays, 24)["stats"]["cc_min"] > S.track_object(o_bad, grays, 24)["stats"]["cc_min"]


@pytest.mark.skipif(not HAS_KAIU, reason="沒有標楷體")
def test_text_gain_bg_and_track_on_orig():
    frames = [sign_frame(), sign_frame(0.6, 1.0)]
    base = {"anchors": [{"frame": 0, "quad": QUAD.tolist()}], "track": {"static": True}}
    o = S.parse_spec(spec(**base, text_gain="bg"))["objects"][0]
    _, _, st = S.apply_object(frames, o, 24)
    assert st["text_gain_range"] == st["gain_range"]
    o_def = S.parse_spec(spec(**base))["objects"][0]
    _, _, st2 = S.apply_object(frames, o_def, 24)
    assert st2["text_gain_range"] != st2["gain_range"]          # 預設仍用原筆畫
    # track_frames：追蹤改用傳入的幀組（run_spec 的 track_on=orig 走這條），合成仍作用在 frames 上
    moving, _ = synth_frames(4, fade=False)
    o3 = S.parse_spec(spec(mode="defocus"))["objects"][0]
    out, tk, _ = S.apply_object(moving, o3, 24, track_frames=moving)
    assert tk["stats"]["cc_min"] > 0.9 and len(out) == 4


def test_occlusion_close_fills_holes():
    P = S.Patch(np.zeros((40, 80, 3), np.float32), np.ones((40, 80), np.float32), np.ones((40, 80), bool),
                (80, 40), 0.0, np.zeros(3, np.float32), src=np.full((40, 80, 3), 100, np.float32))
    roi = np.full((40, 80, 3), 100, np.float32)
    roi[5:35, 20:60] = 20                                       # 大塊暗遮擋
    roi[15:25, 35:45] = 100                                     # 遮擋中間恰好跟原貌一樣的洞
    M = np.eye(3, dtype=np.float32)
    g = np.ones((2, 3), np.float32)
    occ = {**S.OCCL_DEFAULTS, "thresh": 30, "blur": 0.3, "dilate": 0, "feather": 0, "open": 0}
    first = lambda r: r[0] if isinstance(r, tuple) else r
    no = first(S.occlusion_mask(roi, P, M, (80, 40), g, occ))
    yes = first(S.occlusion_mask(roi, P, M, (80, 40), g, {**occ, "close": 6}))
    assert no[20, 40] == 0 and yes[20, 40] == 1
