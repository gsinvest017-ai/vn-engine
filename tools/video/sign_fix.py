"""假漢字「平面追蹤換字」：依規格檔修補 clip 裡的招牌／對聯／匾額等平面文字物件。

流程（每個物件）：
  1. 追蹤：在錨點關鍵幀的 quad 周圍取區域（平面），逐幀用 ECC homography 對齊「關鍵幀樣板」
     （以前一兩幀的等速運動當初值，ECC 失敗時用 SIFT+RANSAC 重抓），不鏈式累積所以不會漂；
     多個錨點時各自追蹤、依時間線性內插角點；低信心幀用鄰幀內插，再做 Savitzky–Golay 平滑。
  2. 底圖：在基準錨點把 quad 拉正（canvas，放大 upscale 倍），偵測原假字筆畫（與底色的 Lab 距離＋Otsu），
     用周圍底色的正規化卷積（或 Telea）補成素面，加回顆粒。
  3. 換字（replace）：PIL 以真字型畫字（每字填滿自己的字格，粗細自動對齊原筆畫墨量），
     顏色取原筆畫的暗／亮兩端做低頻紋理，再模糊一點；erase 只用素面；defocus 直接在追蹤區高斯模糊。
  4. 合成：每幀 homography 把 canvas warp 回畫面，羽化遮罩混合（預設只蓋「原筆畫∪新字」附近），
     用物件本身底色像素算逐幀色彩增益（跟上淡入淡出與變暗），加逐幀顆粒；可用 protect_luma 保留前景亮物。
輸出：x264 crf 10、原 fps、同解析度、音訊 copy → video_out/remaster_v2/clips_fixed/<原檔名>；
      對照圖 sign_fix/contact/<clip>__<id>.jpg；canvas 除錯圖 sign_fix/debug/<clip>__<id>.png；
      量測 sign_fix/reports/<clip>.json（cc、低信心幀、抖動、錨點落差、增益範圍、修補區外平均差）。

規格檔（一個 clip 一檔，JSON；座標皆為原 clip 像素）：
{
  "clip": "第一章_01_3_294f_t.mp4",          # video_out/clips/ 下的檔名
  "objects": [{
    "id": "H024",                            # 對應 hanzi 報告編號
    "mode": "replace",                       # replace 換真字 | erase 抹成素面 | defocus 失焦
    "text": "神恩浩蕩",                      # replace 用
    "direction": "h",                        # h 橫書 | v 直書（上→下）
    "order": "ltr",                          # 橫書方向 ltr 左→右 | rtl 右→左（傳統匾額）
    "range": [0, 12.25],                     # 修補的 clip 秒數區間，省略=整段
    "anchors": [{"t": 3.0, "quad": [[x,y],[x,y],[x,y],[x,y]]}],
                                             # quad 順序＝文字正立時的 左上,右上,右下,左下；可多個錨點校正漂移
                                             # 錨點可帶 "poly"（該錨點幀座標的追蹤多邊形），優先於 track.poly
    "base_anchor": 0,                        # 用哪個錨點做底圖（挑物件最大最清楚的那格）
    "text_box": [0, 0, 1, 1],                # 字排在 quad 內哪一塊（canvas 比例 x0,y0,x1,y1）
    "font": "kaiu",                          # kaiu 標楷體 | msjh / msjhbd 微軟正黑 | mingliu | 或字型檔完整路徑
    "font_index": 0,
    "pad": [0.06, 0.06],                     # 每個字格內留白（比例 x,y）
    "keep_aspect": false,                    # true=字不拉伸
    "weight": "auto",                        # auto=對齊原筆畫墨量；數字=加粗(+)/變細(-)的畫面像素
    "text_color": "auto", "text_color2": "auto",   # [r,g,b]；auto=取原筆畫暗端／亮端
    "outline": null,                         # {"color":[r,g,b], "width":1.0} 描邊（畫面像素）
    "blur": 0.3, "grain": "auto",            # 字的模糊 sigma（畫面像素）、靜態顆粒強度（8bit 單位）
    "temporal_grain": "auto",                # 逐幀變動顆粒強度；auto=量原片相鄰幀雜訊
    "mask_thresh": "auto", "mask_dilate": 1.5,     # 筆畫偵測門檻（Lab 距離）與外擴（畫面像素）
    "mask_mode": "lab",                      # lab=與底色的 Lab 距離 | dark=比局部底色暗的比例（暗處墨字、光影漸層；
                                             # 此時 mask_thresh 是變暗比例 0–1，auto=Otsu）
    "text_rel": null,                        # 例 0.35：字色＝局部素面底色 × 比例（跟著底色明暗走）；auto=原筆畫/底色亮度比
    "fill": "blur",                          # 素面補法 blur（正規化卷積）| telea
    "blend": "strokes",                      # strokes 只蓋筆畫附近 | quad 整塊蓋掉
    "feather": 2.0,                          # 羽化（畫面像素）
    "protect_luma": null,                    # 例 200：畫面上比這亮的像素（燈管等前景）保持原樣
    "protect_color": null,                   # 例 {"rgb":[190,40,40], "dist":45, "open":1}：與此色 Lab 距離內的像素（禁止標誌
                                             # 紅斜槓等）不當字、合成時保持原樣（疊在新字上）；open＝去掉比它細的區域（畫面像素）
    "occlusion": null,                       # 例 {"thresh": 40}：與基準幀原貌差很多處（桿子、前方招牌）保持原樣；
                                             # 可選 blur／open／close／dilate／feather（畫面像素）
    "text_gain": "auto",                     # auto=字的逐幀增益取原筆畫；bg=跟底色（原筆畫會被前景遮住時用）
    "track_on": "current",                   # orig=用原片追蹤（同平面前面物件已抹掉紋理時，例如整頁先 erase 再寫字）
    "gain_smooth": 0,                        # 逐幀增益的 SG 平滑視窗（0=不平滑，閃電／閃光才跟得上）
    "defocus_sigma": 3.0,
    "upscale": 4,
    "track": {"pad": 30, "poly": null, "static": false, "smooth": 9, "min_cc": 0.6}
                                             # pad=quad 外擴多少當追蹤區；poly=自訂追蹤多邊形（基準錨點幀座標，
                                             # 只圈同一平面）；static=不追蹤直接固定 quad；smooth=SG 視窗幀數
  }]
}
指令：
  python tools/video/sign_fix.py init H024 [-o specs/X.json]   # 從 hanzi 報告產生規格草稿＋格線預覽
  python tools/video/sign_fix.py preview specs/X.json         # 把錨點 quad 畫在放大格線圖上檢查
  python tools/video/sign_fix.py run specs/X.json [...]       # 修補、輸出 clip／對照圖／量測
詳見 video_out/remaster_v2/sign_fix/USAGE.md。
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.signal import savgol_filter

ROOT = Path(__file__).resolve().parents[2]
CLIPS = ROOT / "video_out" / "clips"
OUT_CLIPS = ROOT / "video_out" / "remaster_v2" / "clips_fixed"
WORK = ROOT / "video_out" / "remaster_v2" / "sign_fix"
HANZI = ROOT / "docs" / "remaster_v2" / "hanzi.json"
FONTS = {"kaiu": "C:/Windows/Fonts/kaiu.ttf", "msjh": "C:/Windows/Fonts/msjh.ttc",
         "msjhbd": "C:/Windows/Fonts/msjhbd.ttc", "mingliu": "C:/Windows/Fonts/mingliu.ttc"}
LABEL_FONT = "C:/Windows/Fonts/msjh.ttc"
CRF = 10
# 解碼／編碼都指定 bt709 與精確取整：swscale 預設取整會讓重編碼後整體偏暗約 1–3 級
DEC_VF = "scale=in_color_matrix=bt709:flags=accurate_rnd+full_chroma_int+full_chroma_inp"
ENC_VF = "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int"

OBJ_DEFAULTS = {
    "mode": "replace", "text": "", "direction": "h", "order": "ltr", "range": None, "base_anchor": 0,
    "text_box": [0.0, 0.0, 1.0, 1.0], "font": "kaiu", "font_index": 0, "pad": [0.06, 0.06],
    "keep_aspect": False, "weight": "auto", "text_color": "auto", "text_color2": "auto", "outline": None,
    "blur": 0.3, "grain": "auto", "temporal_grain": "auto", "mask_thresh": "auto", "mask_dilate": 1.5, "fill": "blur",
    "blend": "strokes", "feather": 2.0, "protect_luma": None, "gain_smooth": 0, "defocus_sigma": 3.0, "upscale": 4,
    "occlusion": None, "mask_mode": "lab", "text_rel": None, "text_gain": "auto",
    "protect_color": None,
}
OCCL_DEFAULTS = {"thresh": 40.0, "blur": 1.5, "open": 1.0, "dilate": 2.0, "feather": 1.5}
TRACK_DEFAULTS = {"pad": 30, "poly": None, "static": False, "smooth": 9, "min_cc": 0.6}
MODES = ("replace", "erase", "defocus")


# ───────────────────────── 規格 ─────────────────────────

def _quad(q) -> np.ndarray:
    a = np.asarray(q, dtype=np.float64)
    if a.shape != (4, 2) or not np.isfinite(a).all():
        raise ValueError(f"quad 必須是 4 個 [x,y]：{q}")
    if abs(cv2.contourArea(a.astype(np.float32))) < 4:
        raise ValueError(f"quad 面積太小或四點共線：{q}")
    return a


def parse_spec(spec: dict | str | Path) -> dict:
    """讀規格（dict 或 JSON 路徑），補預設值並檢查；錨點依時間排序，quad 轉 ndarray。"""
    if not isinstance(spec, dict):
        spec = json.loads(Path(spec).read_text(encoding="utf-8"))
    spec = copy.deepcopy(spec)
    if not spec.get("clip"):
        raise ValueError("規格缺 clip")
    objs = spec.get("objects") or []
    if not objs:
        raise ValueError("規格沒有 objects")
    out = []
    for i, o in enumerate(objs):
        o = {**OBJ_DEFAULTS, **o}
        o.setdefault("id", f"obj{i}")
        o["track"] = {**TRACK_DEFAULTS, **(o.get("track") or {})}
        if o["mode"] not in MODES:
            raise ValueError(f"{o['id']}: mode 必須是 {MODES}")
        if o["mode"] == "replace" and not o["text"]:
            raise ValueError(f"{o['id']}: replace 模式要給 text")
        if o["direction"] not in ("h", "v") or o["order"] not in ("ltr", "rtl"):
            raise ValueError(f"{o['id']}: direction 只能 h/v、order 只能 ltr/rtl")
        anchors = o.get("anchors") or []
        if not anchors:
            raise ValueError(f"{o['id']}: 至少要一個錨點")
        base = anchors[o["base_anchor"]]
        for a in anchors:
            if "t" not in a and "frame" not in a:
                raise ValueError(f"{o['id']}: 錨點要有 t（秒）或 frame")
            a["quad"] = _quad(a["quad"])
        o["anchors"] = sorted(anchors, key=lambda a: a.get("frame", a.get("t", 0) * 1e3))
        o["base_anchor"] = next(k for k, a in enumerate(o["anchors"]) if a is base)
        tb = o["text_box"]
        if not (len(tb) == 4 and 0 <= tb[0] < tb[2] <= 1 and 0 <= tb[1] < tb[3] <= 1):
            raise ValueError(f"{o['id']}: text_box 要是 0–1 的 [x0,y0,x1,y1]")
        if o["track"]["poly"] is not None:
            o["track"]["poly"] = np.asarray(o["track"]["poly"], dtype=np.float32)
        if o["occlusion"]:
            o["occlusion"] = {**OCCL_DEFAULTS, **(o["occlusion"] if isinstance(o["occlusion"], dict) else {})}
        out.append(o)
    spec["objects"] = out
    return spec


def anchor_frame(a: dict, fps: float, n: int) -> int:
    f = a["frame"] if "frame" in a else int(round(a["t"] * fps))
    return int(min(max(f, 0), n - 1))


def frame_range(o: dict, fps: float, n: int) -> tuple[int, int]:
    if not o["range"]:
        return 0, n - 1
    lo = int(round(o["range"][0] * fps))
    hi = int(round(o["range"][1] * fps))
    return max(0, lo), min(n - 1, hi)


def font_path(name: str) -> str:
    return FONTS.get(name, name)


# ───────────────────────── 影片 IO ─────────────────────────

def probe(path: Path) -> tuple[int, int, float]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(num) / float(den)


def read_frames(path: Path) -> tuple[list[np.ndarray], float]:
    """整段解成 BGR uint8（依 bt709 解色）。"""
    w, h, fps = probe(path)
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", DEC_VF, "-f", "rawvideo",
                        "-pix_fmt", "bgr24", "-"], capture_output=True, check=True)
    buf = np.frombuffer(p.stdout, np.uint8)
    n = buf.size // (w * h * 3)
    return [buf[i * w * h * 3:(i + 1) * w * h * 3].reshape(h, w, 3) for i in range(n)], fps


def write_clip(frames: list[np.ndarray], fps: float, src: Path, dst: Path, crf: int = CRF) -> None:
    """x264 重編碼（bt709 標記、tv range），音訊從原檔 copy。"""
    h, w = frames[0].shape[:2]
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
           "-r", f"{fps:g}", "-i", "-", "-i", str(src), "-map", "0:v", "-map", "1:a?",
           "-vf", ENC_VF, "-c:v", "libx264", "-crf", str(crf),
           "-preset", "slow", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "iec61966-2-1", "-color_range", "tv", "-c:a", "copy", "-movflags", "+faststart",
           str(dst)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg 編碼失敗：{dst}")


# ───────────────────────── 追蹤 ─────────────────────────

def _persp(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float64), H).reshape(-1, 2)


def _roi(quad: np.ndarray, pad: float, shape, poly=None):
    """追蹤區：quad 外擴 pad 的外接矩形（或自訂多邊形），回傳 (x0,y0,x1,y1) 與遮罩。"""
    h, w = shape
    pts = poly if poly is not None else quad
    x0, y0 = np.floor(pts.min(0) - (0 if poly is not None else pad)).astype(int)
    x1, y1 = np.ceil(pts.max(0) + (0 if poly is not None else pad)).astype(int)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    if poly is not None:
        cv2.fillPoly(mask, [np.round(poly - [x0, y0]).astype(np.int32)], 255)
    else:
        mask[:] = 255
    return (x0, y0, x1, y1), mask


def _sift_align(tmpl: np.ndarray, img: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    """SIFT+RANSAC 求 W：img(W x) ≈ tmpl(x)。"""
    sift = cv2.SIFT_create(nfeatures=800)
    k1, d1 = sift.detectAndCompute(tmpl, mask)
    k2, d2 = sift.detectAndCompute(img, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return None
    good = [m for m, n2 in cv2.BFMatcher().knnMatch(d1, d2, k=2) if m.distance < 0.75 * n2.distance]
    if len(good) < 8:
        return None
    p1 = np.float32([k1[m.queryIdx].pt for m in good])
    p2 = np.float32([k2[m.trainIdx].pt for m in good])
    W, inl = cv2.findHomography(p1, p2, cv2.RANSAC, 2.0)
    if W is None or inl.sum() < 8:
        return None
    return W


def _sane_h(H: np.ndarray) -> bool:
    """homography 是否可用：有限值、線性部分行列式在合理範圍（沒有塌縮或翻轉）。"""
    if not np.isfinite(H).all() or abs(H[2, 2]) < 1e-9:
        return False
    d = float(np.linalg.det(H[:2, :2]))
    return 0.05 < d < 20


def _ecc(tmpl, img, mask, W0):
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5)
    try:
        cc, W = cv2.findTransformECC(tmpl, img, W0.astype(np.float32), cv2.MOTION_HOMOGRAPHY, crit, mask, 3)
        return W.astype(np.float64), float(cc)
    except cv2.error:
        return None, None


def track_plane(grays: list[np.ndarray], key: int, quad: np.ndarray, lo: int, hi: int,
                pad: float = 30, poly=None) -> tuple[dict[int, np.ndarray], dict[int, float]]:
    """回傳 {幀: H（關鍵幀座標→該幀）}、{幀: ECC 相關係數}；每幀都直接對齊關鍵幀樣板，不累積漂移。"""
    (x0, y0, x1, y1), mask = _roi(quad, pad, grays[key].shape, poly)
    T = np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1]], np.float64)
    Ti = np.linalg.inv(T)
    tmpl = grays[key][y0:y1, x0:x1].astype(np.float32)
    size = (x1 - x0, y1 - y0)
    Hs, cc = {key: np.eye(3)}, {key: 1.0}
    for step, end in ((1, hi), (-1, lo)):
        prev2, prev = np.eye(3), np.eye(3)
        for i in range(key + step, end + step, step):
            pred = prev @ np.linalg.inv(prev2) @ prev          # 等速預測
            pred = pred / pred[2, 2] if abs(pred[2, 2]) > 1e-9 else pred
            if not _sane_h(pred):
                pred = prev.copy()
            img = cv2.warpPerspective(grays[i].astype(np.float32), pred @ T, size,
                                      flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
            valid = cv2.warpPerspective(np.full(grays[i].shape, 255, np.uint8), pred @ T, size,
                                        flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP)
            m = cv2.bitwise_and(mask, valid)
            W, c = _ecc(tmpl, img, m, np.eye(3))
            if W is None or c < 0.3:                           # ECC 失敗 → SIFT 重抓再 ECC
                Ws = _sift_align(tmpl.astype(np.uint8), img.astype(np.uint8), mask)
                if Ws is not None:
                    W2, c2 = _ecc(tmpl, img, m, Ws)
                    W, c = (W2, c2) if W2 is not None else (Ws, 0.0)
            if W is not None:
                H = pred @ T @ W @ Ti
                H = H / H[2, 2] if abs(H[2, 2]) > 1e-9 else H
            if W is None or not _sane_h(H):                     # 失敗或退化（奇異／翻轉）→ 用預測、標低信心
                H, c = pred, 0.0
            Hs[i], cc[i] = H, c
            prev2, prev = prev, H
    return Hs, cc


def track_object(o: dict, grays: list[np.ndarray], fps: float) -> dict:
    """所有錨點各自追蹤、時間內插、補低信心幀、SG 平滑，回傳角點軌跡與量測。"""
    n = len(grays)
    lo, hi = frame_range(o, fps, n)
    frames = np.arange(lo, hi + 1)
    anchors = [(anchor_frame(a, fps, n), a["quad"]) for a in o["anchors"]]
    tr = o["track"]
    raw = np.zeros((len(frames), 4, 2))
    ccs = np.ones(len(frames))
    per_anchor = []
    for k, (fa, q) in enumerate(anchors):
        a_lo = lo if k == 0 else anchors[k - 1][0]
        a_hi = hi if k == len(anchors) - 1 else anchors[k + 1][0]
        a_lo, a_hi = max(min(a_lo, fa), lo), min(max(a_hi, fa), hi)
        if tr["static"]:
            Hs = {i: np.eye(3) for i in range(a_lo, a_hi + 1)}
            cc = {i: 1.0 for i in Hs}
        else:
            ap = o["anchors"][k].get("poly")                   # 錨點自己的追蹤多邊形（該錨點幀座標）優先
            poly = (np.asarray(ap, dtype=np.float32) if ap is not None
                    else tr["poly"] if (tr["poly"] is not None and k == o["base_anchor"]) else None)
            Hs, cc = track_plane(grays, fa, q, a_lo, a_hi, tr["pad"], poly)
        per_anchor.append((fa, {i: _persp(H, q) for i, H in Hs.items()}, cc))
    # 錨點互相校驗：A 追到 B 那一幀時的角點 vs B 標的 quad（漂移／標註不一致的指標）
    disagree = []
    for k in range(len(per_anchor) - 1):
        fb, qb = anchors[k + 1]
        ca = per_anchor[k][1].get(fb)
        if ca is not None:
            disagree.append(float(np.linalg.norm(ca - qb, axis=1).max()))
    for j, i in enumerate(frames):
        k = int(np.searchsorted([p[0] for p in per_anchor], i, side="right")) - 1
        if k < 0:
            raw[j], ccs[j] = per_anchor[0][1][i], per_anchor[0][2][i]
        elif k == len(per_anchor) - 1 or i == per_anchor[k][0]:
            raw[j], ccs[j] = per_anchor[k][1][i], per_anchor[k][2][i]
        else:
            fa, fb = per_anchor[k][0], per_anchor[k + 1][0]
            w = (i - fa) / (fb - fa)
            raw[j] = (1 - w) * per_anchor[k][1][i] + w * per_anchor[k + 1][1][i]
            ccs[j] = min(per_anchor[k][2][i], per_anchor[k + 1][2][i])
    low = ccs < tr["min_cc"]
    fixed = raw.copy()
    if low.any() and (~low).sum() >= 2:
        for c in range(8):
            flat = fixed.reshape(len(frames), 8)
            flat[low, c] = np.interp(frames[low], frames[~low], flat[~low, c])
    smooth = fixed
    win = int(tr["smooth"]) | 1
    if win >= 3 and len(frames) > 3:
        win = min(win, len(frames) - (1 - len(frames) % 2))
        if win >= 3:
            smooth = savgol_filter(fixed, win, min(2, win - 1), axis=0, mode="interp")
    acc = np.diff(smooth, n=2, axis=0) if len(frames) > 2 else np.zeros((1, 4, 2))
    return {
        "lo": lo, "hi": hi, "frames": frames, "corners": smooth, "raw": raw, "cc": ccs, "low": low,
        "stats": {
            "frames": [int(lo), int(hi)], "cc_mean": round(float(ccs.mean()), 4), "cc_min": round(float(ccs.min()), 4),
            "low_conf_frames": [int(f) for f in frames[low]],
            "raw_vs_smooth_rms_px": round(float(np.sqrt(((raw - smooth) ** 2).sum(-1).mean())), 3),
            "accel_rms_px": round(float(np.sqrt((acc ** 2).sum(-1).mean())), 4),
            "anchor_disagree_px": [round(d, 2) for d in disagree],
            "motion_px": round(float(np.linalg.norm(smooth - smooth[0], axis=-1).max()), 1),
        },
    }


# ───────────────────────── 底圖與字 ─────────────────────────

@dataclass
class Patch:
    rgb: np.ndarray            # canvas BGR float32（素面底圖，已含描邊）
    alpha: np.ndarray          # canvas 混合權重 0–1
    bg: np.ndarray             # canvas 上可用來算增益的底色像素（bool）
    size: tuple[int, int]      # (cw, ch)
    grain: float
    ref_mean: np.ndarray       # 基準幀底色平均（BGR）
    info: dict = field(default_factory=dict)
    tgrain: float = 0.0        # 逐幀顆粒（畫面像素 std）
    debug: dict = field(default_factory=dict)   # canvas 中間產物（src/mask/base/patch），run 時存成除錯圖
    tex: np.ndarray | None = None   # 新字顏色層（BGR）
    ta: np.ndarray | None = None    # 新字 alpha
    core: np.ndarray | None = None  # 原字筆畫核心像素（算「字的增益」：字與底的受光常不同步）
    ref_txt: np.ndarray | None = None
    src: np.ndarray | None = None   # 基準幀拉正的原貌（occlusion 用來判斷前景遮擋）


def canvas_size(quad: np.ndarray, up: int) -> tuple[int, int]:
    w = max(np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[2] - quad[3]))
    h = max(np.linalg.norm(quad[3] - quad[0]), np.linalg.norm(quad[2] - quad[1]))
    return max(8, int(round(w * up))), max(8, int(round(h * up)))


def canvas_pts(cw: int, ch: int) -> np.ndarray:
    return np.float32([[0, 0], [cw, 0], [cw, ch], [0, ch]])


def rectify(frame: np.ndarray, quad: np.ndarray, cw: int, ch: int) -> np.ndarray:
    M = cv2.getPerspectiveTransform(canvas_pts(cw, ch), quad.astype(np.float32))
    return cv2.warpPerspective(frame, M, (cw, ch), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                               borderMode=cv2.BORDER_REPLICATE)


def _box_px(box, cw, ch):
    return int(box[0] * cw), int(box[1] * ch), int(np.ceil(box[2] * cw)), int(np.ceil(box[3] * ch))


def stroke_mask(patch: np.ndarray, box=(0, 0, 1, 1), thresh="auto", exclude=None,
                return_dist: bool = False):
    """原字筆畫遮罩：每像素與底色（box 內 Lab 中位數）的距離，Otsu 或指定門檻。
    exclude（例如燈管等前景亮物）不參與底色與門檻估計，也不算進筆畫。"""
    ch, cw = patch.shape[:2]
    x0, y0, x1, y1 = _box_px(box, cw, ch)
    lab = cv2.cvtColor(np.clip(patch, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    sub = lab[y0:y1, x0:x1]
    ok = np.ones(sub.shape[:2], bool) if exclude is None else ~exclude[y0:y1, x0:x1]
    if ok.sum() < 20:
        ok[:] = True
    ref = np.median(sub[ok], axis=0)
    d = np.linalg.norm(sub - ref, axis=-1)
    if thresh == "auto":
        dmax = max(float(d[ok].max()), 1e-6)
        d8 = np.clip(d[ok] * 255 / dmax, 0, 255).astype(np.uint8)
        t, _ = cv2.threshold(d8.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        thr = float(t) * dmax / 255
        thr = max(thr, 12.0)                                     # 底色太均勻時不要把雜訊當字
    else:
        thr = float(thresh)
    # 局部門檻：沿長邊切成約半個字寬的格子，各自以格內底色中位數重算距離再 Otsu
    # （門檻夾在全域的 0.5–1 倍），陰影裡的暗字才抓得到
    dloc = d.copy()
    tmap = np.full(d.shape, thr, np.float32)
    if thresh == "auto":
        hh, ww = d.shape
        n = max(1, int(round(2 * max(ww, hh) / max(min(ww, hh), 1))))
        for k in range(n):
            sl = (slice(None), slice(k * ww // n, (k + 1) * ww // n)) if ww >= hh else                  (slice(k * hh // n, (k + 1) * hh // n), slice(None))
            okk = ok[sl]
            if okk.sum() < 20:
                continue
            dk = np.linalg.norm(sub[sl] - np.median(sub[sl][okk], axis=0), axis=-1)
            dm = max(float(dk[okk].max()), 1e-6)
            tk_, _ = cv2.threshold(np.clip(dk[okk] * 255 / dm, 0, 255).astype(np.uint8).reshape(-1, 1), 0, 255,
                                   cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            dloc[sl] = dk
            tmap[sl] = max(min(float(tk_) * dm / 255, thr), 0.5 * thr, 12.0)
    m = np.zeros((ch, cw), bool)
    m[y0:y1, x0:x1] = (dloc > tmap) & ok
    k = max(1, min(cw, ch) // 120)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k + 1, k + 1), np.uint8)) > 0
    if return_dist:
        full = np.zeros((ch, cw), np.float32)
        full[y0:y1, x0:x1] = d
        return m, thr, full
    return m, thr


def dark_mask(patch: np.ndarray, box=(0, 0, 1, 1), thresh="auto", exclude=None, return_dist: bool = False):
    """暗字遮罩（mask_mode=dark）：亮度灰階閉運算（抹掉細筆畫）當局部底色，筆畫＝比底色暗的比例 > 門檻。
    對陰影、光影漸層不敏感，適合暗處紅布／匾上的墨字；回傳的 dist 是變暗比例 ×100。"""
    ch, cw = patch.shape[:2]
    x0, y0, x1, y1 = _box_px(box, cw, ch)
    L = cv2.cvtColor(np.clip(patch, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
    k = max(5, min(cw, ch) // 4) | 1
    bgl = cv2.morphologyEx(L, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bgl = cv2.GaussianBlur(bgl, (0, 0), k / 4)
    dark = np.clip((bgl - L) / np.maximum(bgl, 8.0), 0, 1)
    ok = np.ones((ch, cw), bool) if exclude is None else ~exclude
    sel = np.zeros((ch, cw), bool)
    sel[y0:y1, x0:x1] = True
    sel &= ok
    if thresh == "auto":
        v = (dark[sel] * 255).astype(np.uint8).reshape(-1, 1) if sel.sum() >= 20 else np.zeros((1, 1), np.uint8)
        t, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        thr = max(float(t) / 255, 0.12)
    else:
        thr = float(thresh)
    m = (dark > thr) & sel
    kk = max(1, min(cw, ch) // 120)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((kk + 1, kk + 1), np.uint8)) > 0
    return (m, thr, dark * 100) if return_dist else (m, thr)


def fill_background(patch: np.ndarray, hole: np.ndarray, up: int, method: str = "blur") -> np.ndarray:
    """把 hole 區補成素面：blur=底色正規化卷積（保留低頻光影），telea=OpenCV inpaint。"""
    if not hole.any():
        return patch.copy()
    if method == "telea":
        small = cv2.resize(np.clip(patch, 0, 255).astype(np.uint8), None, fx=1 / up, fy=1 / up,
                           interpolation=cv2.INTER_AREA)
        hm = cv2.resize(hole.astype(np.uint8) * 255, (small.shape[1], small.shape[0]),
                        interpolation=cv2.INTER_NEAREST)
        inp = cv2.inpaint(small, (hm > 0).astype(np.uint8), 3, cv2.INPAINT_TELEA)
        fill = cv2.resize(inp, (patch.shape[1], patch.shape[0]), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    else:
        keep = (~hole).astype(np.float32)
        dt = cv2.distanceTransform(hole.astype(np.uint8), cv2.DIST_L2, 3)
        sigma = max(2.0, float(np.percentile(dt[hole], 95)) * 1.5)
        sigma = min(sigma, float(max(hole.shape)))              # 洞幾乎蓋滿 canvas 時 dt 爆大，GaussianBlur 核會溢位
        num = cv2.GaussianBlur(patch * keep[..., None], (0, 0), sigma)
        den = cv2.GaussianBlur(keep, (0, 0), sigma)[..., None]
        fill = num / np.maximum(den, 1e-3)
        big = den[..., 0] < 0.05                                 # 大洞中央：再用更大的核
        if big.any():
            num2 = cv2.GaussianBlur(patch * keep[..., None], (0, 0), sigma * 4)
            den2 = cv2.GaussianBlur(keep, (0, 0), sigma * 4)[..., None]
            fill[big] = (num2 / np.maximum(den2, 1e-4))[big]
    out = patch.copy()
    out[hole] = fill[hole]
    return out


def grain_level(patch: np.ndarray, bg: np.ndarray, up: int) -> float:
    """底色高頻標準差（換算回畫面解析度），當顆粒強度。"""
    small = cv2.resize(patch, None, fx=1 / up, fy=1 / up, interpolation=cv2.INTER_AREA)
    bm = cv2.resize(bg.astype(np.uint8), (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    hp = (small - cv2.GaussianBlur(small, (0, 0), 1.5))[bm]
    if len(hp) < 20:
        return 2.0
    return float(1.4826 * np.median(np.abs(hp - np.median(hp, 0))))    # MAD：不被格線、邊框拉高


def _noise(shape, sigma, rng) -> np.ndarray:
    n = cv2.GaussianBlur(rng.standard_normal(shape).astype(np.float32), (0, 0), max(sigma, 0.5))
    return n / max(float(n.std()), 1e-6)


def render_glyphs(text: str, cw: int, ch: int, font: str, direction: str = "h", order: str = "ltr",
                  box=(0, 0, 1, 1), pad=(0.06, 0.06), keep_aspect: bool = False, font_index: int = 0,
                  em: int = 256) -> np.ndarray:
    """每字畫在 em 方格（保留字與字之間的相對大小），再縮放填滿自己的字格；回傳 canvas alpha 0–1。"""
    alpha = np.zeros((ch, cw), np.float32)
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return alpha
    if direction == "h" and order == "rtl":
        chars = chars[::-1]
    x0, y0, x1, y1 = _box_px(box, cw, ch)
    bw, bh, n = x1 - x0, y1 - y0, len(chars)
    fnt = ImageFont.truetype(font_path(font), int(em * 0.92), index=font_index)
    for k, c in enumerate(chars):
        cx, cy, cwid, chei = ((x0 + k * bw / n, y0, bw / n, bh) if direction == "h"
                              else (x0, y0 + k * bh / n, bw, bh / n))
        im = Image.new("L", (em, em), 0)
        ImageDraw.Draw(im).text((em / 2, em / 2), c, font=fnt, fill=255, anchor="mm")
        tw, th = cwid * (1 - 2 * pad[0]), chei * (1 - 2 * pad[1])
        if keep_aspect:
            tw = th = min(tw, th)
        tw, th = max(1, int(round(tw))), max(1, int(round(th)))
        g = cv2.resize(np.asarray(im, np.float32) / 255, (tw, th), interpolation=cv2.INTER_AREA)
        px, py = int(round(cx + (cwid - tw) / 2)), int(round(cy + (chei - th) / 2))
        sx0, sy0 = max(px, 0), max(py, 0)
        sx1, sy1 = min(px + tw, cw), min(py + th, ch)
        if sx1 > sx0 and sy1 > sy0:
            alpha[sy0:sy1, sx0:sx1] = np.maximum(alpha[sy0:sy1, sx0:sx1], g[sy0 - py:sy1 - py, sx0 - px:sx1 - px])
    return alpha


def adjust_weight(alpha: np.ndarray, k: int) -> np.ndarray:
    if k == 0:
        return alpha
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(k) + 1, 2 * abs(k) + 1))
    return cv2.dilate(alpha, ker) if k > 0 else cv2.erode(alpha, ker)


def stroke_width(mask: np.ndarray) -> float:
    """筆畫寬（像素）：距離變換脊線值的中位數 ×2；對混進來的格線、邊框不敏感。"""
    m = (mask > 0.5).astype(np.uint8)
    if m.sum() < 10:
        return 0.0
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    ridge = (dt >= cv2.dilate(dt, np.ones((3, 3), np.uint8)) - 1e-6) & (m > 0) & (dt >= 1)
    return float(2 * np.median(dt[ridge])) if ridge.any() else float(2 * dt.max())


def match_weight(alpha: np.ndarray, target_width: float, up: int) -> tuple[np.ndarray, int]:
    """在 -1～+2 畫面像素範圍挑一個粗細，讓筆畫寬最接近原字。"""
    best, bk = None, 0
    for k in range(-up, 2 * up + 1):
        w = stroke_width(adjust_weight(alpha, k))
        if w > 0 and (best is None or abs(w - target_width) < best):
            best, bk = abs(w - target_width), k
    return adjust_weight(alpha, bk), bk


def _feather_edges(cw, ch, f):
    """canvas 邊緣向內 f 像素的線性淡出。"""
    if f <= 0:
        return np.ones((ch, cw), np.float32)
    x = np.minimum(np.arange(cw) + 0.5, cw - np.arange(cw) - 0.5) / f
    y = np.minimum(np.arange(ch) + 0.5, ch - np.arange(ch) - 0.5) / f
    return np.clip(np.minimum(y[:, None], x[None, :]), 0, 1).astype(np.float32)


def color_dist(bgr: np.ndarray, rgb) -> np.ndarray:
    """每像素與指定顏色（[r,g,b]）的 Lab 距離。"""
    lab = cv2.cvtColor(np.clip(bgr, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    ref = cv2.cvtColor(np.uint8([[rgb[::-1]]]), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
    return np.linalg.norm(lab - ref, axis=-1)


def protect_color_mask(bgr: np.ndarray, pc: dict, scale: int = 1, pad: float = 0) -> np.ndarray:
    """protect_color 的 0–1 遮罩：與指定色 Lab 距離 < dist（+pad）且（open>0 時）夠粗的區域；
    open（畫面像素）用開運算去掉細邊，避免暗字的反鋸齒邊緣被誤當紅斜槓保留。"""
    d = float(pc.get("dist", 45)) + pad
    m = np.clip((d + 7.5 - color_dist(bgr, pc["rgb"])) / 15, 0, 1).astype(np.float32)
    k = int(round(float(pc.get("open", 0)) * scale))
    if k > 0:
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1,) * 2)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, ker)
    return m


def build_patch(o: dict, frame: np.ndarray, quad: np.ndarray, seed: int = 0) -> Patch:
    """在基準幀建立 canvas：素面底＋（replace 時）新字，並算出混合遮罩與增益取樣區。"""
    up = int(o["upscale"])
    cw, ch = canvas_size(quad, up)
    rng = np.random.default_rng(seed)
    src = rectify(frame, quad, cw, ch).astype(np.float32)
    box = o["text_box"]
    mbox = [max(0, box[0] - 0.03), max(0, box[1] - 0.03), min(1, box[2] + 0.03), min(1, box[3] + 0.03)]
    excl = None
    if o["protect_luma"] is not None:                  # 前景亮物：不當字、不當補底來源（合成時再從原畫面保留）
        lum = src @ np.float32([0.114, 0.587, 0.299])
        excl = cv2.dilate((lum > float(o["protect_luma"]) - 40).astype(np.uint8), np.ones((up + 1, up + 1), np.uint8)) > 0
    if o.get("protect_color"):                         # 指定色前景（紅斜槓等）：同上，不當字、不當補底來源
        pc = protect_color_mask(src, o["protect_color"], up, pad=10) > 0.5
        pc = cv2.dilate(pc.astype(np.uint8), np.ones((up + 1, up + 1), np.uint8)) > 0
        excl = pc if excl is None else (excl | pc)
    masker = dark_mask if o.get("mask_mode") == "dark" else stroke_mask
    raw_mask, thr, dist = masker(src, mbox, o["mask_thresh"], excl, return_dist=True)
    dil = max(1, int(round(o["mask_dilate"] * up)))
    hole = cv2.dilate(raw_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dil + 1,) * 2)) > 0
    if excl is not None:
        hole |= excl
    bg = ~hole
    grain = grain_level(src, bg, up) if o["grain"] == "auto" else float(o["grain"])
    rgb = fill_background(src, hole, up, o["fill"])
    glyph = np.zeros((ch, cw), np.float32)
    tex, ta, core, ref_txt = None, None, None, None
    info = {"canvas": [cw, ch], "mask_thresh": round(thr, 2), "orig_ink": round(float(raw_mask.mean()), 4),
            "grain": round(grain, 2)}
    if o["mode"] == "replace":
        glyph = render_glyphs(o["text"], cw, ch, o["font"], o["direction"], o["order"], box, o["pad"],
                              o["keep_aspect"], o["font_index"])
        target = stroke_width(raw_mask)
        info["orig_stroke_px"] = round(target / up, 2)
        if o["weight"] == "auto":
            glyph, k = match_weight(glyph, target, up)
        else:
            k = int(round(float(o["weight"]) * up))
            glyph = adjust_weight(glyph, k)
        info["weight_px"] = round(k / up, 2)
        # 顏色：原筆畫核心像素的暗端／亮端
        core = cv2.erode(raw_mask.astype(np.uint8), np.ones((up + 1, up + 1), np.uint8)) > 0
        if core.sum() < 30:
            core = raw_mask
        if excl is not None:
            core = core & ~excl
        if core.sum() >= 40:                             # 只取離底色最遠的一半（筆畫中心），門檻壓低時不被底色拉暗
            core = core & (dist >= np.median(dist[core]))
        pix = src[core] if core.sum() >= 10 else src.reshape(-1, 3)
        lum = pix @ np.float32([0.114, 0.587, 0.299])
        srt = pix[np.argsort(lum)]
        n_ = len(srt)                                    # 暗端＝亮度 35–65 百分位、亮端＝前 12%（小字邊緣被模糊拉暗，取偏亮）
        c_lo = srt[int(n_ * 0.35):max(int(n_ * 0.65), int(n_ * 0.35) + 1)].mean(0)
        c_hi = srt[min(int(n_ * 0.88), n_ - 1):].mean(0)
        if o["text_color"] != "auto":
            c_lo = np.float32(o["text_color"][::-1])
        if o["text_color2"] != "auto":
            c_hi = np.float32(o["text_color2"][::-1])
        elif o["text_color"] != "auto":
            c_hi = c_lo
        t = np.clip(0.5 + 0.35 * _noise((ch, cw), min(cw, ch) / 10, rng), 0, 1)[..., None]
        tex = c_lo + (c_hi - c_lo) * t
        info["text_rgb"] = [[int(v) for v in c_lo[::-1]], [int(v) for v in c_hi[::-1]]]
        if o.get("text_rel") is not None:                # 字色＝局部素面底色 × 比例（底色有明暗漸層、暗處墨字時用）
            r = o["text_rel"]
            if r == "auto":
                bl = float(rgb[bg].reshape(-1, 3).mean(0) @ np.float32([0.114, 0.587, 0.299])) if bg.any() else 1.0
                r = float(c_lo @ np.float32([0.114, 0.587, 0.299])) / max(bl, 1.0)
            r = float(np.clip(r, 0.02, 3.0))
            tex = rgb * r * (0.85 + 0.3 * t)
            info["text_rel"] = round(r, 3)
        s = float(o["blur"]) * up
        a = cv2.GaussianBlur(glyph, (0, 0), s) if s > 0 else glyph
        if o["outline"]:
            ow = max(1, int(round(float(o["outline"].get("width", 1.0)) * up)))
            ring = cv2.dilate(glyph, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ow + 1,) * 2))
            ring = cv2.GaussianBlur(ring, (0, 0), s) if s > 0 else ring
            oc = np.float32(o["outline"]["color"][::-1])
            rgb = rgb * (1 - ring[..., None]) + oc * ring[..., None]
        ta = cv2.GaussianBlur(a, (0, 0), 0.35 * up)
        tex = (tex + _noise((ch, cw), up * 0.4, rng)[..., None] * grain).astype(np.float32)
        ref_txt = src[core].mean(0) if core.sum() >= 10 else None
        glyph = np.maximum(glyph, a)
    # 反鋸齒：canvas 是放大 up 倍，warp 回去前先低通；再把補過的區域加回靜態顆粒（紙紋、布紋）
    rgb = cv2.GaussianBlur(rgb, (0, 0), 0.35 * up)
    rgb = rgb + _noise((ch, cw), up * 0.4, rng)[..., None] * grain * hole[..., None]
    f = max(1.0, float(o["feather"]) * up)
    edge = _feather_edges(cw, ch, f)
    if o["blend"] == "quad":
        alpha = edge
    else:
        reg = np.maximum(hole.astype(np.float32), (glyph > 0.05).astype(np.float32))
        reg = cv2.dilate(reg, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * f) + 1,) * 2))
        alpha = np.clip(cv2.GaussianBlur(reg, (0, 0), f * 0.6), 0, 1) * edge
    gain_bg = bg & (glyph < 0.05) & (edge > 0.99)
    if gain_bg.sum() < 50:
        gain_bg = bg
    ref_mean = src[gain_bg].mean(0) if gain_bg.any() else src.reshape(-1, 3).mean(0)
    view = rgb if ta is None else rgb * (1 - ta[..., None]) + tex * ta[..., None]
    dbg = {"src": src, "mask": np.dstack([glyph * 255, hole * 160.0, raw_mask * 255.0]), "patch": view,
           "alpha": alpha * 255}
    return Patch(rgb.astype(np.float32), alpha.astype(np.float32), gain_bg, (cw, ch), grain, ref_mean, info,
                 debug=dbg, tex=tex, ta=None if ta is None else ta.astype(np.float32),
                 core=core if ref_txt is not None else None, ref_txt=ref_txt, src=src)


# ───────────────────────── 合成 ─────────────────────────

def _region_gain(small, m, ref, robust=False):
    cur = np.median(small[m], axis=0) if robust else small[m].mean(0)   # robust：中位數，不被遮擋物帶偏
    w = np.float32([0.114, 0.587, 0.299])
    gl = float(cur @ w) / max(float(ref @ w), 1.0)                 # 亮度增益
    gc = cur / np.maximum(ref, 1.0) / max(gl, 1e-3)                # 各通道相對偏色（暗通道比值不穩，限 ±15%）
    return np.clip(gl * np.clip(gc, 0.85, 1.15), 0.1, 3.0).astype(np.float32)


def frame_gain(frame: np.ndarray, corners: np.ndarray, P: Patch, up: int, robust: bool = False) -> np.ndarray:
    """回傳 (2,3)：[底色增益, 字的增益]，各為此幀平均 ÷ 基準幀平均。字的增益取原假字筆畫核心
    （它們在每一幀都還在畫面上），沒有時同底色。"""
    cw, ch = P.size
    sw, sh = max(4, cw // up), max(4, ch // up)
    M = cv2.getPerspectiveTransform(canvas_pts(sw, sh), corners.astype(np.float32))
    small = cv2.warpPerspective(frame, M, (sw, sh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(-1, -1, -1)).astype(np.float32)
    valid = cv2.warpPerspective(np.ones(frame.shape[:2], np.uint8), M, (sw, sh),
                                flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP) > 0
    bm = cv2.resize(P.bg.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST) > 0
    m = bm & valid
    g_bg = _region_gain(small, m, P.ref_mean, robust) if m.sum() >= 10 else np.ones(3, np.float32)
    g_tx = g_bg
    if P.core is not None:
        cm = cv2.resize(P.core.astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA) > 0.6
        cm &= valid
        if cm.sum() >= 6:
            g_tx = np.clip(_region_gain(small, cm, P.ref_txt, robust), g_bg * 0.5, g_bg * 2.0)
    return np.stack([g_bg, g_tx])


def temporal_noise(frames, tk, P: Patch, up: int, n: int = 8) -> float:
    """物件底色在相鄰幀之間的變動（MAD/√2），當逐幀顆粒強度；靜止畫面的 AI 片通常很小。"""
    cw, ch = P.size
    sw, sh = max(4, cw // up), max(4, ch // up)
    bm = cv2.resize(P.bg.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST) > 0
    vals = []
    js = np.linspace(1, len(tk["frames"]) - 1, min(n, len(tk["frames"]) - 1)).round().astype(int) if len(tk["frames"]) > 1 else []
    for j in js:
        c = []
        for jj in (j - 1, j):
            M = cv2.getPerspectiveTransform(canvas_pts(sw, sh), tk["corners"][j].astype(np.float32))
            c.append(cv2.warpPerspective(frames[tk["frames"][jj]], M, (sw, sh),
                                         flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP).astype(np.float32))
        d = (c[1] - c[0])[bm]
        if len(d) > 20:
            vals.append(1.4826 * np.median(np.abs(d - np.median(d, 0))) / np.sqrt(2))
    return float(np.median(vals)) if vals else 0.0


def _bbox(corners, shape, margin=3):
    h, w = shape[:2]
    x0, y0 = np.floor(corners.min(0) - margin).astype(int)
    x1, y1 = np.ceil(corners.max(0) + margin).astype(int)
    return max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)


def occlusion_mask(roi: np.ndarray, P: Patch, M: np.ndarray, size, gain: np.ndarray, occ: dict) -> np.ndarray:
    """前景遮擋遮罩 0–1：此幀（roi）與基準幀原貌（P.src warp 過來、乘上整體亮度比）的平滑差 > thresh 的地方。
    原假字本身每幀都在、差很小，不會被當遮擋；桿子、前方招牌、行人等差很大。
    亮度比只用與原貌差距不大的像素估（逐通道中位數，夾在 [0.5, 2]）：遮擋物佔一半以上時也不會把原貌壓成遮擋物的亮度。"""
    exp = cv2.warpPerspective(P.src, M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    inside = cv2.warpPerspective(np.ones(P.src.shape[:2], np.uint8), M, size, flags=cv2.INTER_NEAREST) > 0
    s = max(0.3, float(occ["blur"]))
    br, be = cv2.GaussianBlur(roi, (0, 0), s), cv2.GaussianBlur(exp, (0, 0), s)
    ok = inside & (np.abs(br - be).mean(-1) < 2 * float(occ["thresh"]))   # 只用「看起來還是物件本身」的像素估亮度比
    ratio = None
    if ok.sum() >= 20:
        ratio = np.clip(np.median(br[ok] / np.maximum(be[ok], 1.0), axis=0), 0.5, 2.0).astype(np.float32)
        be = be * ratio
    r = np.abs(br - be).mean(-1)
    m = ((r > float(occ["thresh"])) & inside).astype(np.uint8)
    k = int(round(float(occ["open"])))
    if k > 0:
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1,) * 2))
    k = int(round(float(occ.get("close", 0))))            # 閉運算：暗色遮擋物蓋在原暗筆畫上時差很小，補起遮擋區內的筆畫形小洞
    if k > 0:
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1,) * 2))
    k = int(round(float(occ["dilate"])))
    if k > 0:
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1,) * 2))
    m = m.astype(np.float32)
    f = float(occ["feather"])
    m = np.clip(cv2.GaussianBlur(m, (0, 0), f) * 1.5, 0, 1) if f > 0 else m
    return m, ratio


def composite(frame: np.ndarray, P: Patch, corners: np.ndarray, gain: np.ndarray, o: dict,
              rng: np.random.Generator, occ_log: list | None = None) -> np.ndarray:
    x0, y0, x1, y1 = _bbox(corners, frame.shape)
    if x1 <= x0 or y1 <= y0:
        return frame
    cw, ch = P.size
    M = cv2.getPerspectiveTransform(canvas_pts(cw, ch), (corners - [x0, y0]).astype(np.float32))
    size = (x1 - x0, y1 - y0)
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    occ = None
    if o.get("occlusion") and P.src is not None:
        occ, ratio = occlusion_mask(roi, P, M, size, gain, o["occlusion"])
        if ratio is not None:                   # 遮擋物佔大半時 frame_gain 會被帶偏，改用未遮擋像素估的亮度比（底與字同比）
            gain = np.stack([ratio, ratio * np.clip(gain[1] / np.maximum(gain[0], 1e-3), 0.8, 1.25)])
    pw = cv2.warpPerspective(P.rgb, M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) * gain[0]
    if P.ta is not None:
        tw = cv2.warpPerspective(P.tex, M, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        taw = cv2.warpPerspective(P.ta, M, size, flags=cv2.INTER_LINEAR, borderValue=0)[..., None]
        pw = pw * (1 - taw) + tw * gain[1] * taw
    a = cv2.warpPerspective(P.alpha, M, size, flags=cv2.INTER_LINEAR, borderValue=0)[..., None]
    if occ is not None:
        a = a * (1 - occ)[..., None]
        if occ_log is not None:
            occ_log.append(float((occ > 0.5).sum()) / max(1.0, float((a > 0.05).sum() + (occ > 0.5).sum())))
    if o.get("protect_color"):
        a = a * (1 - protect_color_mask(roi, o["protect_color"], 1))[..., None]
    if o["protect_luma"] is not None:
        lum = roi @ np.float32([0.114, 0.587, 0.299])
        thr = float(o["protect_luma"])
        a = a * (1 - np.clip((lum - (thr - 20)) / 30, 0, 1))[..., None]
    pw = pw + (_noise(pw.shape[:2], 0.6, rng) * P.tgrain)[..., None]
    out = frame.copy()
    out[y0:y1, x0:x1] = np.clip(roi * (1 - a) + pw * a, 0, 255).astype(np.uint8)
    return out


def defocus(frame: np.ndarray, corners: np.ndarray, o: dict) -> np.ndarray:
    s = float(o["defocus_sigma"])
    f = max(1.0, float(o["feather"]))
    x0, y0, x1, y1 = _bbox(corners, frame.shape, margin=int(3 * s + 2 * f + 2))
    if x1 <= x0 or y1 <= y0:
        return frame
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    m = np.zeros(roi.shape[:2], np.float32)
    cv2.fillPoly(m, [np.round(corners - [x0, y0]).astype(np.int32)], 1.0)
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * f) + 1,) * 2))
    m = cv2.GaussianBlur(m, (0, 0), f)[..., None]
    blur = cv2.GaussianBlur(roi, (0, 0), s)
    out = frame.copy()
    out[y0:y1, x0:x1] = np.clip(roi * (1 - m) + blur * m, 0, 255).astype(np.uint8)
    return out


def apply_object(frames: list[np.ndarray], o: dict, fps: float, seed: int = 0,
                 track_frames: list[np.ndarray] | None = None) -> tuple[list[np.ndarray], dict, dict]:
    """追蹤＋合成一個物件（回傳新幀列表、軌跡資料、量測）。frames 不會被原地修改。
    track_frames：追蹤改用這組幀（例如原片；前面物件已把同平面的紋理抹掉時用，規格 "track_on": "orig"）。"""
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in (track_frames if track_frames is not None else frames)]
    tk = track_object(o, grays, fps)
    out = list(frames)
    stats = dict(tk["stats"])
    if o["mode"] == "defocus":
        for j, i in enumerate(tk["frames"]):
            out[i] = defocus(frames[i], tk["corners"][j], o)
        return out, tk, stats
    up = int(o["upscale"])
    kb = anchor_frame(o["anchors"][o["base_anchor"]], fps, len(frames))
    kb = int(min(max(kb, tk["lo"]), tk["hi"]))
    jb = kb - tk["lo"]
    P = build_patch(o, frames[kb], tk["corners"][jb], seed)
    P.tgrain = temporal_noise(frames, tk, P, up) if o["temporal_grain"] == "auto" else float(o["temporal_grain"])
    stats["temporal_grain"] = round(P.tgrain, 2)
    robust = bool(o.get("occlusion"))                      # 有遮擋物時增益改用中位數
    gains = np.array([frame_gain(frames[i], tk["corners"][j], P, up, robust) for j, i in enumerate(tk["frames"])])
    gains = gains / gains[jb]                                   # 基準幀增益 = 1
    if o.get("text_gain") == "bg":                              # 原筆畫後段被遮擋時，字的增益改跟底色
        gains[:, 1] = gains[:, 0]
    gs = int(o["gain_smooth"]) | 1                              # 預設不平滑：閃電、閃光要逐幀跟上
    if gs >= 3 and len(gains) > gs:
        gains = savgol_filter(gains, gs, min(2, gs - 1), axis=0, mode="interp")
    rng = np.random.default_rng(seed + 1)
    occ_log = [] if o.get("occlusion") else None
    for j, i in enumerate(tk["frames"]):
        out[i] = composite(frames[i], P, tk["corners"][j], gains[j].astype(np.float32), o, rng, occ_log)
    stats.update(P.info)
    if occ_log:
        stats["occluded_frac_max"] = round(max(occ_log), 3)
    tk["debug"] = P.debug
    stats["base_frame"] = kb
    stats["gain_range"] = [round(float(gains[:, 0].min()), 3), round(float(gains[:, 0].max()), 3)]
    stats["text_gain_range"] = [round(float(gains[:, 1].min()), 3), round(float(gains[:, 1].max()), 3)]
    return out, tk, stats


# ───────────────────────── 對照圖 ─────────────────────────

def _label_font(size):
    try:
        return ImageFont.truetype(LABEL_FONT, size)
    except OSError:
        return ImageFont.load_default()


def contact_sheet(before: list[np.ndarray], after: list[np.ndarray], tk: dict, o: dict, stats: dict,
                  fps: float, dst: Path, n: int = 6) -> None:
    """三列：修補前、修補後、修補後＋追蹤框（綠＝高信心、紅＝低信心）；外加一張修補後全幅縮圖。"""
    frames = tk["frames"]
    picks = list(np.linspace(0, len(frames) - 1, n).round().astype(int))
    picks.append(int(np.argmin(tk["cc"])))
    picks = sorted(set(picks))
    allc = tk["corners"].reshape(-1, 2)
    x0, y0 = allc.min(0)
    x1, y1 = allc.max(0)
    mx, my = max(40, (x1 - x0) * 0.5), max(40, (y1 - y0) * 0.5)
    H, W = before[0].shape[:2]
    bx0, by0 = int(max(0, x0 - mx)), int(max(0, y0 - my))
    bx1, by1 = int(min(W, x1 + mx)), int(min(H, y1 + my))
    th = 220
    sc = th / max(1, by1 - by0)
    tw = max(1, int((bx1 - bx0) * sc))
    rows = [[], [], []]
    for j in picks:
        i = frames[j]
        b = cv2.resize(before[i][by0:by1, bx0:bx1], (tw, th), interpolation=cv2.INTER_CUBIC)
        a = cv2.resize(after[i][by0:by1, bx0:bx1], (tw, th), interpolation=cv2.INTER_CUBIC)
        ov = a.copy()
        col = (0, 0, 255) if tk["low"][j] else (0, 255, 0)
        pts = ((tk["corners"][j] - [bx0, by0]) * sc).round().astype(np.int32)
        cv2.polylines(ov, [pts], True, col, 1, cv2.LINE_AA)
        for r, im in zip(rows, (b, a, ov)):
            r.append(im)
    gap = 6
    lab_h = 22
    sheet_w = len(picks) * (tw + gap) + 90
    full_h = int(H * (sheet_w - 90) / W / 2)
    sheet_h = 44 + 3 * (th + lab_h + gap) + full_h + 10
    img = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 18))
    d = ImageDraw.Draw(img)
    f_big, f_small = _label_font(18), _label_font(13)
    title = (f"{o['id']}  {o['mode']}  「{o.get('text', '')}」  cc 平均 {stats['cc_mean']} / 最低 {stats['cc_min']}  "
             f"低信心 {len(stats['low_conf_frames'])} 幀  抖動(二階差分) {stats['accel_rms_px']}px  "
             f"錨點落差 {stats['anchor_disagree_px']}")
    d.text((8, 10), title, font=f_big, fill=(230, 200, 120))
    for r, (name, ims) in enumerate(zip(("修補前", "修補後", "追蹤框"), rows)):
        y = 44 + r * (th + lab_h + gap)
        d.text((8, y + th // 2), name, font=f_big, fill=(220, 220, 220))
        for k, (j, im) in enumerate(zip(picks, ims)):
            x = 90 + k * (tw + gap)
            img.paste(Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)), (x, y))
            if r == 0:
                i = frames[j]
                d.text((x, y + th + 2), f"f{i}  {i / fps:.2f}s  cc {tk['cc'][j]:.3f}", font=f_small, fill=(170, 170, 170))
    jmid = picks[len(picks) // 2]
    full = cv2.resize(after[frames[jmid]], (int(W * full_h / H), full_h), interpolation=cv2.INTER_AREA)
    img.paste(Image.fromarray(cv2.cvtColor(full, cv2.COLOR_BGR2RGB)), (90, sheet_h - full_h - 10))
    d.text((8, sheet_h - full_h), "全幅\n修補後", font=f_small, fill=(170, 170, 170))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, quality=92)


# ───────────────────────── 主流程 ─────────────────────────

def untouched_diff(before: list[np.ndarray], after: list[np.ndarray], changed: list[np.ndarray]) -> float:
    """修補區以外的平均絕對差（檢查色彩矩陣／重編碼沒造成整體偏色）。"""
    diffs = []
    for i in range(0, len(before), max(1, len(before) // 12)):
        m = ~changed[i]
        if m.any():
            diffs.append(float(np.abs(before[i].astype(np.int16) - after[i].astype(np.int16))[m].mean()))
    return round(float(np.mean(diffs)), 3) if diffs else 0.0


def run_spec(spec_in, clips_dir: Path = CLIPS, out_dir: Path = OUT_CLIPS, work: Path = WORK,
             encode: bool = True, verify: bool = True) -> dict:
    spec = parse_spec(spec_in)
    src = Path(clips_dir) / spec["clip"]
    frames, fps = read_frames(src)
    orig = frames
    stem = Path(spec["clip"]).stem
    report = {"clip": spec["clip"], "fps": fps, "frames": len(frames), "objects": []}
    for k, o in enumerate(spec["objects"]):
        before = frames
        frames, tk, stats = apply_object(frames, o, fps, seed=k,
                                         track_frames=orig if o.get("track_on") == "orig" else None)
        stats = {"id": o["id"], "mode": o["mode"], "text": o.get("text", ""), **stats}
        sheet = Path(work) / "contact" / f"{stem}__{o['id']}.jpg"
        contact_sheet(before, frames, tk, o, stats, fps, sheet)
        stats["contact_sheet"] = str(sheet.relative_to(ROOT)) if sheet.is_relative_to(ROOT) else str(sheet)
        if tk.get("debug"):                     # canvas 除錯圖：原圖｜遮罩(紅=原筆畫、綠=補洞、藍=新字)｜成品｜混合權重
            ims = [np.clip(v, 0, 255).astype(np.uint8) for v in tk["debug"].values()]
            ims = [cv2.cvtColor(v, cv2.COLOR_GRAY2BGR) if v.ndim == 2 else v for v in ims]
            sep = np.full((ims[0].shape[0], 4, 3), 255, np.uint8)
            imwrite(Path(work) / "debug" / f"{stem}__{o['id']}.png",
                    np.hstack(sum([[v, sep] for v in ims], [])[:-1]))
        report["objects"].append(stats)
        print(f"[{o['id']}] cc 平均 {stats['cc_mean']} 最低 {stats['cc_min']}，低信心 {len(stats['low_conf_frames'])} 幀，"
              f"抖動 {stats['accel_rms_px']}px，錨點落差 {stats['anchor_disagree_px']}")
    if encode:
        dst = Path(out_dir) / spec["clip"]
        write_clip(frames, fps, src, dst)
        report["output"] = str(dst.relative_to(ROOT)) if dst.is_relative_to(ROOT) else str(dst)
        if verify:
            enc, _ = read_frames(dst)
            report["output_frames"] = len(enc)
            changed = [np.abs(a.astype(np.int16) - b.astype(np.int16)).max(-1) > 0 for a, b in zip(orig, frames)]
            changed = [cv2.dilate(c.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0 for c in changed]
            report["untouched_mean_abs_diff"] = untouched_diff(orig, enc, changed)
            print(f"輸出 {dst}（{len(enc)} 幀；修補區外平均差 {report['untouched_mean_abs_diff']}）")
    rp = Path(work) / "reports" / f"{stem}.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=1,
                          default=lambda x: x.item() if hasattr(x, "item") else str(x)), encoding="utf-8")
    return report


# ───────────────────────── init / preview ─────────────────────────

def imwrite(path: Path, im: np.ndarray) -> None:
    """cv2.imwrite 在 Windows 遇中文路徑會靜默失敗，改用 imencode。"""
    ok, buf = cv2.imencode(Path(path).suffix or ".png", im)
    if not ok:
        raise RuntimeError(f"影像編碼失敗：{path}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(buf.tobytes())


def grid_zoom(frame: np.ndarray, quads: list[np.ndarray], margin: int = 40, scale: int = 5) -> np.ndarray:
    """放大裁切＋10px 格線（每 50px 標座標），把 quad 畫上去（左上角點標紅），方便讀座標。"""
    H, W = frame.shape[:2]
    pts = np.concatenate(quads) if quads else np.zeros((1, 2))
    x0, y0 = np.maximum(pts.min(0) - margin, 0).astype(int)
    x1, y1 = np.minimum(pts.max(0) + margin, [W, H]).astype(int)
    c = cv2.resize(frame[y0:y1, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    for x in range((x0 // 10 + 1) * 10, x1, 10):
        X = (x - x0) * scale
        cv2.line(c, (X, 0), (X, c.shape[0]), (0, 200, 0) if x % 50 == 0 else (0, 90, 0), 1)
        if x % 50 == 0:
            cv2.putText(c, str(x), (X + 2, 12), 0, 0.4, (0, 255, 255), 1)
    for y in range((y0 // 10 + 1) * 10, y1, 10):
        Y = (y - y0) * scale
        cv2.line(c, (0, Y), (c.shape[1], Y), (0, 200, 0) if y % 50 == 0 else (0, 90, 0), 1)
        if y % 50 == 0:
            cv2.putText(c, str(y), (2, Y - 2), 0, 0.4, (0, 255, 255), 1)
    for q in quads:
        p = ((q - [x0, y0]) * scale).round().astype(np.int32)
        cv2.polylines(c, [p], True, (255, 0, 255), 1, cv2.LINE_AA)
        cv2.circle(c, tuple(int(v) for v in p[0]), 4, (0, 0, 255), -1)
    return c


def grab_frame(path: Path, t: float) -> np.ndarray:
    w, h, _ = probe(path)
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                        "-vf", DEC_VF, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint8)[:w * h * 3].reshape(h, w, 3)


def init_from_hanzi(hid: str, hanzi: Path = HANZI, n_anchors: int = 2) -> dict:
    """從 hanzi 報告的 bbox 軌跡產生規格草稿（quad 先用 bbox 四角，之後要人工修成貼合字的四角）。"""
    rep = json.loads(Path(hanzi).read_text(encoding="utf-8"))
    it = next((x for x in rep["items"] if x["id"] == hid), None)
    if it is None:
        raise KeyError(f"hanzi 報告沒有 {hid}")
    traj = it.get("bbox_traj_sampled") or [[it["src_sec"][0], 0, *it["bbox_first"]]]
    picks = [traj[int(round(k))] for k in np.linspace(0, len(traj) - 1, min(n_anchors, len(traj)))]
    anchors = [{"t": round(p[0], 2), "quad": [[p[2], p[3]], [p[4], p[3]], [p[4], p[5]], [p[2], p[5]]]}
               for p in picks]
    font = "kaiu" if it["object_type"] in ("對聯", "匾額", "桌裙", "地圖標題", "檔案簿", "直匾", "燈籠") else "msjh"
    mode = "replace" if it["fix"] == "a" else "defocus"
    x0, y0, x1, y1 = it["bbox_first"]
    direction = "v" if (y1 - y0) > 1.3 * (x1 - x0) else "h"          # 細高的框多半是直書
    return {"id": hid, "mode": mode, "text": it.get("suggested_text", ""), "direction": direction,
            "_todo": "quad 目前是 OCR 外接框，要改成貼合字的四角（文字正立時 左上,右上,右下,左下）；"
                     "text 要核對字數與格數，一個 quad 只放一行／一條聯，多條請拆成多個物件",
            "range": [max(0.0, it["src_sec"][0] - 0.5), it["src_sec"][1] + 0.5], "anchors": anchors,
            "font": font, "_hanzi": {"object_type": it["object_type"], "seen_text": it["seen_text"],
                                    "object_motion": it["object_motion"], "note": it.get("note", "")}}


def main(argv=None):
    ap = argparse.ArgumentParser(description="假漢字平面追蹤換字")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("init", help="從 hanzi 報告產生規格草稿")
    a.add_argument("hid")
    a.add_argument("-o", "--out", help="規格檔路徑（已存在且同 clip 就附加物件）")
    a.add_argument("--anchors", type=int, default=2)
    b = sub.add_parser("preview", help="把錨點 quad 畫在放大格線圖上")
    b.add_argument("spec")
    b.add_argument("--clips-dir", type=Path, default=None, help="來源 clip 目錄（預設 video_out/clips）")
    c = sub.add_parser("run", help="修補並輸出")
    c.add_argument("spec", nargs="+")
    c.add_argument("--no-encode", action="store_true", help="只做追蹤與對照圖，不輸出 clip")
    c.add_argument("--clips-dir", type=Path, default=None,
                   help="來源 clip 目錄（預設 video_out/clips；修重生候選時指到候選目錄）")
    c.add_argument("--out-dir", type=Path, default=None,
                   help="輸出目錄（預設 remaster_v2/clips_fixed）")
    args = ap.parse_args(argv)
    prev_dir = WORK / "preview"
    prev_dir.mkdir(parents=True, exist_ok=True)
    if args.cmd == "init":
        rep = json.loads(HANZI.read_text(encoding="utf-8"))
        clip = next(x["clip"] for x in rep["items"] if x["id"] == args.hid)
        obj = init_from_hanzi(args.hid, n_anchors=args.anchors)
        out = Path(args.out) if args.out else WORK / "specs" / f"{Path(clip).stem}.json"
        spec = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"clip": clip, "objects": []}
        if spec["clip"] != clip:
            raise SystemExit(f"{out} 是 {spec['clip']} 的規格，{args.hid} 在 {clip}")
        spec["objects"] = [x for x in spec["objects"] if x.get("id") != args.hid] + [obj]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        for an in obj["anchors"]:
            im = grid_zoom(grab_frame(CLIPS / clip, an["t"]), [np.asarray(an["quad"], float)])
            p = prev_dir / f"{Path(clip).stem}__{args.hid}__t{an['t']:.2f}.png"
            imwrite(p, im)
            print("預覽", p)
        print("規格草稿", out)
    elif args.cmd == "preview":
        spec = parse_spec(args.spec)
        for o in spec["objects"]:
            for an in o["anchors"]:
                t = an.get("t", an.get("frame", 0) / 24)
                im = grid_zoom(grab_frame((args.clips_dir or CLIPS) / spec["clip"], t), [an["quad"]])
                p = prev_dir / f"{Path(spec['clip']).stem}__{o['id']}__t{t:.2f}.png"
                imwrite(p, im)
                print("預覽", p)
    else:
        for s in args.spec:
            run_spec(s, clips_dir=args.clips_dir or CLIPS, out_dir=args.out_dir or OUT_CLIPS,
                     encode=not args.no_encode)


if __name__ == "__main__":
    main()
