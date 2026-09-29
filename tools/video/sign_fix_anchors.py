"""sign_fix 的密集錨點產生器：推近／搖鏡幅度大、ECC 追小字追不穩時，先算每 0.25s 的 quad 當錨點，
規格再用 track.static（錨點間線性內插＋SG 平滑）。第 4 批（第一章_03_*）的規格都是用這裡的兩種方法產生的。

  chain：在平面（牆、書頁、封面）多邊形內做 SIFT+RANSAC，每一小步（預設 0.25s）與下一幀配對、串接 homography，
         把基準幀的 quad 映到各時間。每步只跨幾幀，尺度差小，推近 2–3 倍也追得住；平面要選對（只圈同一平面）。
  tmatch：背景失焦、特徵點太少時，拿基準幀 quad 外擴區當樣板做多尺度模板比對（平移＋等比縮放），逐步往回追。
          只適合近乎正面、只有推近／平移的鏡頭；重複圖樣（對聯字）在垂直方向可能錯位，要看圖確認。

指令（輸出 {"秒數": [quad, ...]} JSON 到 stdout）：
  python tools/video/sign_fix_anchors.py chain <clip> <t0> --times 2.25:12.25:0.25 --poly '[[x,y],...]' --quads '[[[x,y]x4],...]'
  python tools/video/sign_fix_anchors.py tmatch <clip> <t0> --times 10:12.2:0.25 --quads '...'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def _sift_h(a: np.ndarray, b: np.ndarray, mask: np.ndarray, sift, bf) -> tuple[np.ndarray | None, int]:
    """a（mask 內）→ b 的 homography 與 inlier 數；配對不足回傳 (None, 0)。"""
    ka, da = sift.detectAndCompute(a, mask)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 4 or len(kb) < 4:
        return None, 0
    good = [m[0] for m in bf.knnMatch(da, db, k=2) if len(m) == 2 and m[0].distance < 0.75 * m[1].distance]
    if len(good) < 4:
        return None, 0
    pa = np.float32([ka[m.queryIdx].pt for m in good])
    pb = np.float32([kb[m.trainIdx].pt for m in good])
    H, inl = cv2.findHomography(pa, pb, cv2.RANSAC, 1.5)
    return (H, int(inl.sum())) if H is not None else (None, 0)


def chain_homographies(grays: list[np.ndarray], k0: int, targets: list[int], poly, step: int = 6
                       ) -> tuple[dict[int, np.ndarray], dict[int, int]]:
    """從基準幀 k0 往前、往後各自每 step 幀串接 SIFT homography（多邊形隨之變換），回傳 {幀: H(k0→幀)} 與每步 inlier 數。
    某一步配對失敗就沿用上一個 H（該步 inlier 記 0），呼叫端要看 inlier 決定能不能用。"""
    poly = np.float32(poly)
    sift, bf = cv2.SIFT_create(3000), cv2.BFMatcher()
    Hs, inl = {k0: np.eye(3)}, {}
    for side in (sorted([t for t in targets if t < k0], reverse=True), sorted([t for t in targets if t > k0])):
        H, cur, P = np.eye(3), k0, poly.copy()
        for tgt in side:
            while cur != tgt:
                nxt = max(cur - step, tgt) if tgt < cur else min(cur + step, tgt)
                m = np.zeros_like(grays[cur])
                cv2.fillPoly(m, [np.int32(np.round(P))], 255)
                h, n = _sift_h(grays[cur], grays[nxt], m, sift, bf)
                if h is not None:
                    H = h @ H
                    P = cv2.perspectiveTransform(poly[None], H)[0]
                inl[nxt] = n
                cur = nxt
            Hs[tgt] = H.copy()
    return Hs, inl


def map_quads(H: np.ndarray, quads) -> list[list[list[float]]]:
    return [[[round(float(v), 1) for v in p] for p in cv2.perspectiveTransform(np.float32(q)[None], H)[0]]
            for q in quads]


def template_track(grays: list[np.ndarray], k0: int, quad, targets: list[int], pad_x: int = 14,
                   scale_range: float = 0.08, blur: float = 1.5) -> dict[int, tuple[list, float]]:
    """以 k0 幀 quad 外接框（左右外擴 pad_x）為樣板，由近到遠逐幀做多尺度比對；回傳 {幀: (quad, 相關係數)}。
    每一步的尺度只在上一步 ±scale_range 內找，所以 targets 間距要小（約 0.25s）。"""
    q = np.float32(quad)
    g = [cv2.GaussianBlur(x, (0, 0), blur).astype(np.float32) for x in grays]
    x0, y0 = np.maximum(q.min(0) - [pad_x, 0], 0).astype(int)
    x1, y1 = (q.max(0) + [pad_x, 0]).astype(int)
    tmpl, org = g[k0][y0:y1, x0:x1], np.float32([x0, y0])
    out = {k0: ([[round(float(v), 1) for v in p] for p in q], 1.0)}
    for side in (sorted([t for t in targets if t < k0], reverse=True), sorted([t for t in targets if t > k0])):
        s_prev = 1.0
        for t in side:
            best = (-2.0, 1.0, (0, 0))
            for s in np.arange(s_prev - scale_range, s_prev + scale_range + 1e-6, 0.01):
                tm = cv2.resize(tmpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                if tm.shape[0] >= g[t].shape[0] or tm.shape[1] >= g[t].shape[1] or min(tm.shape) < 4:
                    continue
                _, mv, _, ml = cv2.minMaxLoc(cv2.matchTemplate(g[t], tm, cv2.TM_CCOEFF_NORMED))
                if mv > best[0]:
                    best = (mv, s, ml)
            mv, s_prev, ml = best
            nq = (q - org) * s_prev + np.float32(ml)
            out[t] = ([[round(float(v), 1) for v in p] for p in nq], round(float(mv), 3))
    return out


def _times(spec: str, fps: float, n: int) -> list[int]:
    """'a:b:step' 或 'a,b,c'（秒）→ 幀號（夾在 0..n-1）。"""
    if ":" in spec:
        a, b, st = (float(x) for x in spec.split(":"))
        ts = list(np.arange(a, b + 1e-6, st))
    else:
        ts = [float(x) for x in spec.split(",")]
    return sorted({int(min(max(round(t * fps), 0), n - 1)) for t in ts})


def main(argv=None):
    sys.path.insert(0, str(Path(__file__).parent))
    import sign_fix as S
    ap = argparse.ArgumentParser(description="sign_fix 密集錨點產生器")
    ap.add_argument("method", choices=("chain", "tmatch"))
    ap.add_argument("clip")
    ap.add_argument("t0", type=float)
    ap.add_argument("--times", required=True)
    ap.add_argument("--quads", required=True)
    ap.add_argument("--poly")
    ap.add_argument("--step", type=float, default=0.25)
    a = ap.parse_args(argv)
    frames, fps = S.read_frames(S.CLIPS / a.clip)
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    k0 = int(min(max(round(a.t0 * fps), 0), len(frames) - 1))
    tg = _times(a.times, fps, len(frames))
    quads = json.loads(a.quads)
    res = {}
    if a.method == "chain":
        Hs, inl = chain_homographies(grays, k0, tg, json.loads(a.poly), max(1, int(round(a.step * fps))))
        res = {round(k / fps, 3): map_quads(H, quads) for k, H in sorted(Hs.items())}
        print("最少 inlier", min(inl.values()) if inl else None, file=sys.stderr)
    else:
        per = [template_track(grays, k0, q, tg) for q in quads]
        res = {round(k / fps, 3): [p[k][0] for p in per] for k in sorted(per[0])}
        print("相關係數", {round(k / fps, 3): [p[k][1] for p in per] for k in sorted(per[0])}, file=sys.stderr)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
