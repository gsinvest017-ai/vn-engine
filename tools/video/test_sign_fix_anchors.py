"""sign_fix_anchors 與 sign_fix.fill_background 回歸測試（純 CPU、合成影像）：python -m pytest tools/video/test_sign_fix_anchors.py -q"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import sign_fix as S  # noqa: E402
import sign_fix_anchors as A  # noqa: E402

W, H = 320, 240


def texture(seed=0):
    rng = np.random.default_rng(seed)
    t = np.zeros((H * 2, W * 2), np.float32)
    for s in (1.5, 4, 10):
        t += cv2.GaussianBlur(rng.standard_normal((H * 2, W * 2)).astype(np.float32), (0, 0), s) * s
    return ((t - t.min()) / (t.max() - t.min()) * 200 + 25).astype(np.uint8)


def true_h(i):
    """已知運動：逐幀推近 1.5%＋平移（大牆面上的連續推鏡）。"""
    s = 1 + 0.015 * i
    return np.array([[s, 0, -W / 2 - 1.0 * i], [0, s, -H / 2 + 0.5 * i], [0, 0, 1]], float)


def frames(n):
    tex = texture()
    return [cv2.warpPerspective(tex, true_h(i), (W, H), flags=cv2.INTER_LINEAR) for i in range(n)]


QUAD = [[140, 100], [180, 100], [180, 150], [140, 150]]


def expect(k0, k, quad=QUAD):
    M = true_h(k) @ np.linalg.inv(true_h(k0))
    return cv2.perspectiveTransform(np.float32(quad)[None], M)[0]


def test_chain_homographies_follow_zoom():
    g = frames(40)
    k0, tg = 30, [0, 6, 12, 18, 24, 36, 39]
    Hs, inl = A.chain_homographies(g, k0, tg, [[20, 20], [300, 20], [300, 220], [20, 220]], step=6)
    assert set(tg) <= set(Hs) and min(inl.values()) >= 20
    for k in tg:
        got = np.float32(A.map_quads(Hs[k], [QUAD])[0])
        assert np.abs(got - expect(k0, k)).max() < 1.5, k      # 0→30 幀縮放差 1.45 倍仍貼合


def test_template_track_translation_scale():
    g = frames(31)
    out = A.template_track(g, 30, QUAD, [30, 26, 22, 18], pad_x=10)
    for k in (26, 22, 18):
        q, score = out[k]
        assert score > 0.8 and np.abs(np.float32(q) - expect(30, k)).max() < 2.5, k


def test_times_parsing():
    assert A._times("0:1:0.25", 24, 100) == [0, 6, 12, 18, 24]
    assert A._times("12.2,99", 24, 294) == [293]


def test_fill_background_hole_covers_canvas():
    """洞蓋滿整個 canvas（門檻壓很低時）distanceTransform 回 FLT_MAX，不可讓 GaussianBlur 核溢位而中斷。"""
    patch = np.full((400, 60, 3), 90, np.float32)
    hole = np.ones((400, 60), bool)
    out = S.fill_background(patch, hole, 4)
    assert out.shape == patch.shape and np.isfinite(out).all()
