"""《暗渠之書》影片版組裝器 v2（remaster）：不重新生成 clip，只用快取 clip 重新組裝，修掉 v1 的銜接問題並混入配樂。

用法（在 vn-engine 根目錄）：
    python tools/video/remaster.py --chapters 1 --max-seconds 100 --name anqu_v2_test   # 試片
    python tools/video/remaster.py --name anqu_v2                                       # 全片

對應 docs/remaster_v2/transitions.md 的修正：
- T01/T02/T10/T11：音訊全程在 numpy/PCM 組裝（環境音逐段取原始 clip、rubberband 對齊、段間等功率交叉淡化；
  旁白依 line_times 取樣點精確擺位；配樂 bgm_synth 同一時間軸），最後只編一次 AAC，音軌長度 = 影像長度。
- T03：i2v 接續段的前一段用到生成檔尾（尾幀＝接續段首幀），接續段丟掉重複的第 1 幀，接點不溶接。
- T04：慢動作與長度微調一律用 rife-ncnn-vulkan 補到精確幀數 round(秒數*24)，不再用 minterpolate blend。
- T05：依報告 exposure_match（半強度）做曝光／飽和度匹配。
- T06：生成檔內部硬切 → 切點兩側拆開溶接（一側太短就直接丟掉那一側）。
- T07：近乎靜止的段加極慢推鏡。  T08：第三章與過暗的段先抬暗部，統一調色後不再壓成全黑。
- T09：段落開頭的曝光收斂閃白 → 往後跳過收斂中的幾幀。
- 同一 shot 內的段落邊界改 0.4–0.6 秒溶接（亮度落差越大越長），溶接吃掉的長度由 RIFE 多補幀補回；
  每個 shot 的總幀數＝v1 時間軸（render.plan）四捨五入到幀，字幕與旁白不偏。shot 之間維持淡出淡入。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage, signal

sys.path.insert(0, str(Path(__file__).parent))
import bgm_synth  # noqa: E402
import render  # noqa: E402

FPS = 24
SR = 48000
SPF = SR // FPS                     # 每幀 2000 個取樣點：影音長度可以用整數精確對齊
WORK_RES = (1056, 608)              # 生成解析度；中間檔維持原生解析度，最後一次放大到 1080p
OUT_DIR = render.ROOT / "video_out" / "remaster_v2"
CLIP_DIR = render.ROOT / "video_out" / "clips"
FIXED_DIR = OUT_DIR / "clips_fixed"
RIFE_DIR = OUT_DIR / "tools_survey" / "bin" / "rife-ncnn-vulkan-20221029-windows"
REPORT_JSON = render.ROOT / "docs" / "remaster_v2" / "transitions.json"
REPORT_SEGS = OUT_DIR / "transitions" / "segments.json"

FADE_F = round(render.FADE_SEC * FPS)   # shot 淡入淡出幀數（同 v1）
INNER_XF = 10                           # 生成檔內部硬切改溶接的幀數
JOIN_AUDIO = 0.08                       # 不溶接的接點（i2v 接續）音訊仍做 80 ms 交叉淡化
MIN_SIDE = 30                           # 內部硬切的一側短於 1.25 秒就直接丟掉
CUT_NCC = 0.5                           # 內部硬切：前後幀結構相關 < 0.5 且隔 4 幀仍 < 0.5（閃電/閃爍不算）
STILL_MAD = 0.35                        # 近乎靜止：相鄰幀差（96x54 灰階）小於此值
DARK_Y, DARK_STRENGTH = 40.0, 0.7       # 逐幀：平滑後亮度（0–255）低於 40 就往 40 抬 70%（log 域；越暗抬越多、順序不變）
DARK_SMOOTH = 25                        # 亮度平滑視窗（幀），避免抬亮忽大忽小
CH3_LIFT = 1.2                          # 第三章夜景：抵銷 GRADE 的 gamma 0.82（淨值約 0.98，報告建議 0.95–1.0）
RAMP_F = 48                             # 接續段調色漸變幀數（2 秒）
ZOOM_RATE, ZOOM_MAX = 0.0005, 1.07      # 推鏡：每幀 +0.05%，最多 1.07 倍
LEVELS = dict(narr=-18.0, amb=-30.0, bgm=-29.0, target=-17.0, ceiling=-2.0)   # LUFS / dBTP
DUCK = dict(amb=9.0, bgm=6.0)           # 旁白出聲時壓低的 dB（配樂本身已先壓 5 dB）


def xfade_frames(dy: float) -> int:
    """shot 內段落邊界的溶接幀數：亮度落差越大越長（0.42 / 0.5 / 0.58 秒）。"""
    dy = abs(dy)
    return 14 if dy >= 20 else 12 if dy >= 8 else 10


# ───────────────────────── 分段計畫 ─────────────────────────

@dataclass
class Piece:
    seg: int                  # 對應 render.clip_specs 的第幾段
    shot: int
    tag: str
    src: str
    a: int                    # 取用原始幀 [a, b)
    b: int
    n: int                    # 輸出幀數（含溶接重疊）
    t0: int = 0               # 在成片時間軸上的起始幀
    xl: int = 0               # 與前一片的影像重疊幀數（0 = 硬接或 shot 開頭）
    xr: int = 0
    join_l: bool = False      # 與前一片是 i2v 接續（影像硬接、音訊 80 ms 交叉淡化）
    join_r: bool = False
    fade_in: bool = False
    fade_out: bool = False
    gamma: float = 1.0
    sat: float = 1.0
    zoom: bool = False
    ramp_from: tuple[float, float] | None = None   # i2v 接續：調色參數從前一片的值漸變過來（避免接點跳亮度）
    luma: list[float] | None = None     # 暗段：[a, b) 每個原始幀的平滑亮度，逐幀決定抬暗部的 gamma
    notes: list[str] = field(default_factory=list)

    @property
    def m(self) -> int:
        return self.b - self.a


def frame_bounds(times: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """時間軸秒數 → 幀邊界（各自四捨五入），相鄰段首尾相接、總長不累積誤差。"""
    return [(round(t0 * FPS), round(t1 * FPS)) for t0, t1 in times]


def ncc(p: np.ndarray, q: np.ndarray) -> float:
    p = p - p.mean()
    q = q - q.mean()
    return float((p * q).sum() / math.sqrt((p * p).sum() * (q * q).sum() + 1e-6))


def cut_scores(fr: np.ndarray) -> np.ndarray:
    """cs[c] = max(ncc(c-1, c), ncc(c-2, c+2))：兩者都低才是真的換構圖（亮度閃爍、閃電的結構相關仍高）。"""
    n = len(fr)
    cs = np.ones(n)
    for c in range(2, n - 2):
        cs[c] = max(ncc(fr[c - 1], fr[c]), ncc(fr[c - 2], fr[c + 2]))
    return cs


def find_inner_cuts(cs: np.ndarray, a: int, b: int) -> list[int]:
    """[a, b) 內的硬切（第 c 幀起換構圖）；頭尾 2 幀不算，連續命中只取第一幀。"""
    out = []
    for c in range(a + 2, b - 2):
        if cs[c] < CUT_NCC and not (out and c - out[-1] <= 2):
            out.append(c)
    return out


def flash_skip(y: np.ndarray, a: int, max_skip: int = 8, thr: float = 10.0) -> int:
    """段落開頭的曝光收斂閃白：前 3 幀比 8–14 幀亮 thr 以上 → 跳到亮度收斂的那一幀（最多 max_skip 幀）。"""
    if len(y) < a + 15:
        return 0
    settle = float(np.mean(y[a + 8:a + 14]))
    if float(np.mean(y[a:a + 3])) - settle < thr:
        return 0
    for k in range(1, max_skip + 1):
        if y[a + k] <= settle + 3.0:
            return k
    return max_skip


def is_still(mad: np.ndarray, a: int, b: int) -> bool:
    """近乎靜止：一半以上的幀差 < STILL_MAD，且最長靜止段 ≥ 2 秒。"""
    d = mad[a + 1:b]
    if len(d) < 2 * FPS:
        return False
    still = d < STILL_MAD
    run = best = 0
    for v in still:
        run = run + 1 if v else 0
        best = max(best, run)
    return bool(still.mean() >= 0.5 and best >= 2 * FPS)


def dark_lift(y: float, floor: float = DARK_Y, strength: float = DARK_STRENGTH) -> float:
    """平均亮度 y < floor 時的 gamma（>1 變亮）：把 y 往 floor 拉 strength（log 域），y ≥ floor 回 1。"""
    if y >= floor:
        return 1.0
    y = max(y, 1.0)
    return (math.log(y / 255) / math.log(floor / 255)) ** strength


def load_exposure(report: Path = REPORT_JSON, segs: Path = REPORT_SEGS) -> dict[str, tuple[float, float]]:
    """transitions 報告的 exposure_match（半強度）→ {tag: (gamma, saturation)}。"""
    try:
        rep = json.loads(report.read_text(encoding="utf-8"))
        tags = [s["tag"] for s in json.loads(segs.read_text(encoding="utf-8"))]
    except (OSError, ValueError, KeyError):
        return {}
    em = next((f["metrics"].get("exposure_match", {}) for f in rep.get("findings", []) if f.get("id") == "T05"), {})
    out = {}
    for k, v in em.items():
        m = re.search(r"gamma=([\d.]+):saturation=([\d.]+)", v.get("eq_half", ""))
        if m and int(k) < len(tags):
            out[tags[int(k)]] = (float(m.group(1)), float(m.group(2)))
    return out


def build_pieces(specs: list[dict], times: list[tuple[float, float]], chapters: list[int], probe, n_frames,
                 exposure: dict[str, tuple[float, float]] | None = None, src_of=None) -> list[Piece]:
    """把 render.clip_specs 的分段換成實際要算的片段（Piece）。
    probe(tag) -> (y 全幅亮度逐幀, mad 相鄰幀差, cs 硬切分數)；n_frames(tag) -> 生成檔總幀數；chapters[i] = 第 i 段的章號。"""
    exposure = exposure or {}
    src_of = src_of or (lambda tag: tag)
    fb = frame_bounds(times)
    out: list[Piece] = []
    i = 0
    while i < len(specs):
        j = i
        while j + 1 < len(specs) and specs[j + 1]["shot"] == specs[i]["shot"]:
            j += 1
        idx = list(range(i, j + 1))
        # 1) 邊界型態：接續段硬接；其他溶接，長度依前後段亮度落差（用原計畫取用區間估）
        bounds = []
        for k in idx[:-1]:
            nxt = specs[k + 1]
            if nxt["kind"] == "cont":
                bounds.append(0)
                continue
            y0 = probe(specs[k]["tag"])[0]
            y1 = probe(nxt["tag"])[0]
            a0 = round(specs[k]["head"] * FPS)
            e0 = min(len(y0), a0 + max(6, round(specs[k]["secs"] * FPS)))
            a1 = round(nxt["head"] * FPS)
            dy = float(np.mean(y1[a1:a1 + 6]) - np.mean(y0[e0 - 6:e0]))
            bounds.append(xfade_frames(dy))
        for pos, k in enumerate(idx):
            sp = specs[k]
            tag = sp["tag"]
            y, mad, cs = probe(tag)
            total = n_frames(tag)
            f0, f1 = fb[k]
            dl = bounds[pos - 1] if pos > 0 else 0
            dr = bounds[pos] if pos < len(bounds) else 0
            ext_l, ext_r = dl // 2, dr - dr // 2
            n = f1 - f0 + ext_l + ext_r
            t0 = f0 - ext_l
            join_l = pos > 0 and dl == 0
            join_r = pos < len(bounds) and dr == 0
            notes = []
            a = round(sp["head"] * FPS)
            if sp["kind"] == "cont":
                a += 1                                   # 首幀＝上一段尾幀（重複），丟掉
                notes.append("drop-dup-first")
            else:
                sk = flash_skip(y, a)
                if sk:
                    a += sk
                    notes.append(f"flash-skip-{sk}")
            if join_r:
                # 下一段是 i2v 接續：一定要用到檔尾，尾幀才會等於下一段首幀
                a = max(a, total - n)
                b = total
                notes.append("anchor-end")
            else:
                b = min(total, a + n)
            # 2) 生成檔內部硬切
            cuts = find_inner_cuts(cs, a, b)
            sub = [(a, b)]
            for c in cuts[:2]:
                sa, sb = sub[-1]
                if not sa < c < sb:
                    continue
                if c - sa < MIN_SIDE:
                    sub[-1] = (c, sb if join_r else min(total, c + (sb - sa)))
                    notes.append(f"inner-cut@{c}:drop-head")
                elif sb - c < MIN_SIDE and not join_r:
                    sub[-1] = (sa, c)
                    notes.append(f"inner-cut@{c}:drop-tail")
                else:
                    sub[-1] = (sa, c)
                    sub.append((c, sb))
                    notes.append(f"inner-cut@{c}:xfade")
            ch = chapters[k]
            gam, sat = exposure.get(tag, (1.0, 1.0))
            ysm = np.convolve(np.pad(y, DARK_SMOOTH // 2, mode="edge"), np.ones(DARK_SMOOTH) / DARK_SMOOTH, "valid")
            if ch == 3:
                gam *= CH3_LIFT
            # 3) 各子片段分配幀數：內部切點再多吃 INNER_XF 幀，一起由補幀補回
            lens = [sb - sa for sa, sb in sub]
            want = n + INNER_XF * (len(sub) - 1)
            ns, left = [], want
            for q, ln in enumerate(lens):
                nq = left if q == len(lens) - 1 else max(1, round(want * ln / sum(lens)))
                ns.append(nq)
                left -= nq
            t = t0
            for q, ((sa, sb), nq) in enumerate(zip(sub, ns)):
                pc = Piece(seg=k, shot=sp["shot"], tag=tag, src=src_of(tag), a=sa, b=sb, n=nq, t0=t,
                           xl=dl if q == 0 else INNER_XF, xr=dr if q == len(sub) - 1 else INNER_XF,
                           join_l=join_l and q == 0, join_r=join_r and q == len(sub) - 1,
                           fade_in=sp["first"] and q == 0, fade_out=sp["last"] and q == len(sub) - 1,
                           gamma=round(gam, 4), sat=sat, zoom=is_still(mad, sa, sb), notes=list(notes))
                lum = ysm[sa:sb]
                if len(lum) and float(lum.min()) < DARK_Y:
                    pc.luma = [round(float(v), 2) for v in lum]
                    pc.notes.append(f"dark-lift(minY={lum.min():.0f},x{dark_lift(float(lum.min())):.2f})")
                if pc.zoom:
                    pc.notes.append("still→push-in")
                out.append(pc)
                t += nq - pc.xr
        i = j + 1
    for p, q in zip(out, out[1:]):
        if q.join_l and (p.gamma, p.sat) != (q.gamma, q.sat):
            q.ramp_from = (p.gamma, p.sat)
            q.notes.append(f"grade-ramp-from({p.gamma:.2f},{p.sat:.2f})")
    return out


def grade_at(pc: Piece, k: int) -> tuple[float, float]:
    """第 k 幀的 (gamma, saturation)：接續段前 RAMP_F 幀從前一片的值線性漸變；暗幀再乘上逐幀抬暗部。"""
    g, s = pc.gamma, pc.sat
    if pc.ramp_from is not None and k < RAMP_F:
        w = k / RAMP_F
        g, s = pc.ramp_from[0] + (g - pc.ramp_from[0]) * w, pc.ramp_from[1] + (s - pc.ramp_from[1]) * w
    if pc.luma:
        g *= dark_lift(pc.luma[min(len(pc.luma) - 1, k * len(pc.luma) // max(pc.n, 1))])
    return g, s


def check_timeline(pieces: list[Piece], times: list[tuple[float, float]]) -> None:
    """每個 shot 的首幀／尾幀要落在 v1 時間軸上，片段之間只能在宣告的溶接幀數內重疊。"""
    fb = frame_bounds(times)
    for p, q in zip(pieces, pieces[1:]):
        if p.shot == q.shot:
            assert q.t0 == p.t0 + p.n - p.xr and p.xr == q.xl, (p, q)
        else:
            assert q.t0 == p.t0 + p.n, (p, q)
    shots: dict[int, list[Piece]] = {}
    for p in pieces:
        shots.setdefault(p.shot, []).append(p)
    for ps in shots.values():
        first, last = ps[0], ps[-1]
        assert first.t0 == fb[first.seg][0] and last.t0 + last.n == fb[last.seg][1], (first, last)


# ───────────────────────── 影像 ─────────────────────────

def ffrun(*args: str, capture: bool = False):
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True,
                          capture_output=capture)


def probe_clip(src: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """96x54 灰階逐幀（ffmpeg gray 已是全幅 0–255）：(亮度, 相鄰幀差, 硬切分數)。"""
    w, h = 96, 54
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps={FPS},scale={w}:{h}:flags=area,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, check=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, h, w).astype(np.float32)
    y = fr.reshape(len(fr), -1).mean(1)
    mad = np.r_[0.0, np.abs(np.diff(fr, axis=0)).reshape(len(fr) - 1, -1).mean(1)] if len(fr) > 1 else np.zeros(len(fr))
    return y, mad, cut_scores(fr)


def extract(src: Path, a: int, b: int, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    vf = (f"fps={FPS},trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,"
          f"scale={WORK_RES[0]}:{WORK_RES[1]}:flags=lanczos:in_color_matrix=bt709:in_range=tv,format=rgb24")
    ffrun("-i", str(src), "-vf", vf, "-fps_mode", "passthrough", "-compression_level", "1", str(dest / "%08d.png"))
    return len(list(dest.glob("*.png")))


def rife(src_dir: Path, dest: Path, n: int, log: list[str]) -> list[Path]:
    """rife-ncnn-vulkan 補到正好 n 幀；GPU 失敗依序降級（小 tile/單執行緒 → CPU），最多 3 次。"""
    exe = RIFE_DIR / "rife-ncnn-vulkan.exe"
    tries = [[], ["-j", "1:1:1", "-t", "256"], ["-g", "-1", "-j", "1:2:2"]]
    for extra in tries:
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        r = subprocess.run([str(exe), "-i", str(src_dir), "-o", str(dest), "-n", str(n), "-m", str(RIFE_DIR / "rife-v4.6"),
                            "-f", "%08d.png", *extra], capture_output=True, text=True, errors="replace")
        files = sorted(dest.glob("*.png"))
        if r.returncode == 0 and len(files) == n:
            if extra:
                log.append(f"rife-fallback{extra}")
            return files
        log.append(f"rife-fail rc={r.returncode} got={len(files)} {extra}")
    return []


def linear_resample(files: list[Path], n: int) -> list[np.ndarray]:
    """RIFE 完全失敗時的保底：相鄰原始幀線性混合（會有殘影，notes 會記下）。"""
    import cv2
    src = [cv2.imread(str(f)) for f in files]
    out = []
    for j in range(n):
        p = j * len(src) / n
        i0 = min(int(p), len(src) - 1)
        i1 = min(i0 + 1, len(src) - 1)
        w = p - int(p)
        out.append(cv2.addWeighted(src[i0], 1 - w, src[i1], w, 0))
    return out


def prepare(pc: Piece, work: Path) -> list:
    """抽出 [a, b) 原始幀；幀數不等於 n 就用 RIFE 補到 n。回傳 n 個檔案路徑（或保底的 ndarray）。"""
    d = work / f"p{pc.seg:03d}_{pc.a:04d}"
    raw = d / "raw"
    m = extract(Path(pc.src), pc.a, pc.b, raw)
    files = sorted(raw.glob("*.png"))
    if m != pc.m:
        pc.notes.append(f"extract-got-{m}")
    if m == pc.n:
        return files
    if m > pc.n:     # 不該發生（取用區間已限制在 n 幀內），保險：均勻抽掉
        pc.notes.append(f"decimate-{m}->{pc.n}")
        return [files[round(j * (m - 1) / max(1, pc.n - 1))] for j in range(pc.n)]
    got = rife(raw, d / "rife", pc.n, pc.notes)
    if got:
        return got
    pc.notes.append("rife-failed→linear-blend")
    return linear_resample(files, pc.n)


def eq_lut(gamma: float) -> np.ndarray:
    x = np.arange(256) / 255.0
    return np.clip(np.round(255.0 * np.power(x, 1.0 / gamma)), 0, 255).astype(np.uint8)


def apply_eq(bgr: np.ndarray, gamma: float, sat: float) -> np.ndarray:
    """同 ffmpeg eq：gamma 作用在亮度、saturation 以 128 為中心縮放色度。"""
    import cv2
    if abs(gamma - 1) < 1e-3 and abs(sat - 1) < 1e-3:
        return bgr
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    if abs(gamma - 1) >= 1e-3:
        ycc[..., 0] = cv2.LUT(ycc[..., 0], eq_lut(gamma))
    if abs(sat - 1) >= 1e-3:
        c = ycc[..., 1:].astype(np.float32)
        ycc[..., 1:] = np.clip((c - 128.0) * sat + 128.0 + 0.5, 0, 255).astype(np.uint8)
    return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)


def zoom_frame(bgr: np.ndarray, z: float) -> np.ndarray:
    """以畫面中心放大 z 倍（次像素、無抖動）。"""
    import cv2
    if z <= 1.0 + 1e-6:
        return bgr
    h, w = bgr.shape[:2]
    mat = np.array([[z, 0, (1 - z) * w / 2], [0, z, (1 - z) * h / 2]], np.float32)
    return cv2.warpAffine(bgr, mat, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def blend_weight(k: int, d: int) -> float:
    """溶接第 k 幀（0..d-1）裡「下一片」的權重。"""
    return (k + 0.5) / d


def fade_gain(i: int, n: int, fade_in: bool, fade_out: bool, f: int = FADE_F) -> float:
    g = 1.0
    if fade_in and i < f:
        g = min(g, i / f)
    if fade_out and i >= n - f:
        g = min(g, (n - 1 - i) / f)
    return g


def render_video(pieces: list[Piece], dest: Path, work: Path, workers: int = 2) -> int:
    """逐片補幀、調色、溶接、淡入淡出，raw 幀直接灌進一個只有影像的 x264 crf 10 中間檔。回傳總幀數。"""
    import cv2
    w, h = WORK_RES
    enc = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
                            "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                            "-c:v", "libx264", "-crf", "10", "-preset", "fast",
                            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                            "-color_range", "tv", str(dest)], stdin=subprocess.PIPE)
    total = 0
    held: list[np.ndarray] = []            # 上一片尾端要跟下一片溶接的幀

    def emit(fr: np.ndarray):
        nonlocal total
        enc.stdin.write(np.ascontiguousarray(fr, dtype=np.uint8).tobytes())
        total += 1

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(prepare, pc, work) for pc in pieces[:workers + 1]]
        for i, pc in enumerate(pieces):
            frames = futs[i].result()
            if i + workers + 1 < len(pieces):
                futs.append(pool.submit(prepare, pieces[i + workers + 1], work))
            nxt_held: list[np.ndarray] = []
            for k in range(pc.n):
                fr = frames[k] if isinstance(frames[k], np.ndarray) else cv2.imread(str(frames[k]))
                if fr.shape[1] != w or fr.shape[0] != h:
                    fr = cv2.resize(fr, (w, h), interpolation=cv2.INTER_LANCZOS4)
                if pc.zoom:
                    fr = zoom_frame(fr, min(ZOOM_MAX, 1.0 + ZOOM_RATE * k))
                fr = apply_eq(fr, *grade_at(pc, k)).astype(np.float32)
                g = fade_gain(k, pc.n, pc.fade_in, pc.fade_out)
                if g < 1.0:
                    fr *= g
                if k < pc.xl and k < len(held):
                    wgt = blend_weight(k, pc.xl)
                    fr = held[k] * (1 - wgt) + fr * wgt
                if k >= pc.n - pc.xr:
                    nxt_held.append(fr)          # 留給下一片溶接
                    continue
                emit(np.clip(fr + 0.5, 0, 255))
            held = nxt_held
            shutil.rmtree(work / f"p{pc.seg:03d}_{pc.a:04d}", ignore_errors=True)
    for fr in held:                            # 理論上不會有（最後一片 xr=0）
        emit(np.clip(fr + 0.5, 0, 255))
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("中間檔編碼失敗")
    return total


# ───────────────────────── 音訊 ─────────────────────────

def decode_audio(src: Path, mono: bool = False) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1" if mono else "2", "-ar", str(SR),
                        "-f", "f32le", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return np.zeros((0,) if mono else (0, 2), np.float32)
    x = np.frombuffer(r.stdout, np.float32)
    return x if mono else x.reshape(-1, 2)


def fit_len(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    pad = np.zeros((n - len(x),) + x.shape[1:], x.dtype)
    return np.concatenate([x, pad])


def stretch(x: np.ndarray, n: int, tmp: Path) -> np.ndarray:
    """rubberband 把 x 伸縮成正好 n 個取樣點（音高不變）。"""
    if len(x) == 0:
        return np.zeros((n, 2), np.float32)
    tempo = len(x) / n
    if abs(tempo - 1) < 1e-3:
        return fit_len(x, n)
    x.astype(np.float32).tofile(tmp)
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(tmp),
                        "-af", f"rubberband=tempo={tempo:.6f}", "-f", "f32le", "-"], capture_output=True, check=True)
    return fit_len(np.frombuffer(r.stdout, np.float32).reshape(-1, 2), n)


def xfade_curves(n: int) -> tuple[np.ndarray, np.ndarray]:
    """等功率交叉淡化：(淡入, 淡出)，sin² + cos² = 1。"""
    x = (np.arange(n) + 0.5) / max(n, 1)
    return np.sin(0.5 * np.pi * x), np.cos(0.5 * np.pi * x)


def ambient_track(pieces: list[Piece], n_total: int, tmp: Path) -> np.ndarray:
    """環境音：每片取原始 clip 對應區間 → 伸縮到片長 → 片間等功率交叉淡化；shot 頭尾 0.5 秒線性淡入淡出（同畫面）。"""
    out = np.zeros((n_total, 2), np.float64)
    cache: dict[str, np.ndarray] = {}
    ej = int(JOIN_AUDIO * SR / 2)
    for pc in pieces:
        if pc.src not in cache:
            cache[pc.src] = decode_audio(Path(pc.src))
        src = cache[pc.src]
        el = ej if pc.join_l else 0
        er = ej if pc.join_r else 0
        s0 = pc.t0 * SPF - el
        n = pc.n * SPF + el + er
        x = stretch(src[pc.a * SPF:pc.b * SPF], n, tmp).astype(np.float64)
        ov_l = pc.xl * SPF + 2 * el
        ov_r = pc.xr * SPF + 2 * er
        if ov_l:
            x[:ov_l] *= xfade_curves(ov_l)[0][:, None]
        if ov_r:
            x[n - ov_r:] *= xfade_curves(ov_r)[1][:, None]
        f = FADE_F * SPF
        if pc.fade_in:
            x[:f] *= np.linspace(0, 1, f, endpoint=False)[:, None]
        if pc.fade_out:
            x[n - f:] *= np.linspace(1, 0, f, endpoint=False)[:, None]
        lo, hi = max(0, s0), min(n_total, s0 + n)
        out[lo:hi] += x[lo - s0:hi - s0]
    return out


def narration_track(events: list[tuple[Path, float]], n_total: int) -> np.ndarray:
    out = np.zeros((n_total, 2), np.float64)
    for wav, start in events:
        x = decode_audio(wav, mono=True).astype(np.float64)
        i0 = int(round(start * SR))
        m = min(len(x), n_total - i0)
        if m > 0:
            out[i0:i0 + m] += x[:m, None]
    return out


def sidechain_gain(key: np.ndarray, depth_db: float, thr_db: float = -42.0, knee_db: float = 12.0,
                   attack: float = 0.03, release: float = 0.6, sr: int = SR) -> np.ndarray:
    """旁白（key）出聲時的壓低增益（線性、逐取樣點）：20 ms RMS 過門檻就往下壓到 -depth_db，軟膝、attack/release 平滑。"""
    mono = key.mean(1) if key.ndim == 2 else key
    hop = sr // 100
    n = len(mono) // hop + 1
    pad = np.zeros(n * hop)
    pad[:len(mono)] = mono
    lvl = 10 * np.log10(np.mean(pad.reshape(n, hop) ** 2, axis=1) + 1e-12)
    lvl = ndimage.maximum_filter1d(lvl, 2)      # 20 ms 視窗
    frac = np.clip((lvl - (thr_db - knee_db / 2)) / knee_db, 0, 1)
    a_up = 1 - math.exp(-1 / (attack * 100))
    a_dn = 1 - math.exp(-1 / (release * 100))
    sm = np.empty(n)
    v = 0.0
    for i, f in enumerate(frac):
        v += (a_up if f > v else a_dn) * (f - v)
        sm[i] = v
    g = 10 ** (-depth_db * sm / 20)
    return np.interp(np.arange(len(mono)) / hop, np.arange(n), g)


def tp_peak_env(x: np.ndarray, os: int = 4, chunk: int = SR * 10) -> np.ndarray:
    """逐取樣點的 true peak（4 倍超取樣、兩聲道取大），分塊計算省記憶體。"""
    out = np.empty(len(x))
    pad = 64
    for s in range(0, len(x), chunk):
        lo, hi = max(0, s - pad), min(len(x), s + chunk + pad)
        up = signal.resample_poly(x[lo:hi], os, 1, axis=0)
        pk = np.abs(up).max(axis=1).reshape(-1, os).max(axis=1)
        out[s:min(len(x), s + chunk)] = pk[s - lo:s - lo + min(chunk, len(x) - s)]
    return out


def tp_limit(x: np.ndarray, ceiling_db: float, look: float = 0.005, sr: int = SR) -> np.ndarray:
    """前瞻峰值限制器：需要的增益取 min 濾波（前後 look 秒）再平滑，true peak 壓到 ceiling 以下。"""
    c = 10 ** (ceiling_db / 20)
    y = x
    for _ in range(3):
        pk = tp_peak_env(y)
        req = np.minimum(1.0, c / np.maximum(pk, 1e-12))
        if req.min() >= 1.0:
            break
        L = max(1, int(look * sr))
        g = ndimage.minimum_filter1d(req, 2 * L + 1)
        g = ndimage.uniform_filter1d(g, L + 1)
        y = y * np.minimum(g, 1.0)[:, None]
        c *= 0.995
    return y


def lufs(x: np.ndarray) -> float:
    return bgm_synth.integrated_lufs(x)


def gain_to(x: np.ndarray, target: float) -> tuple[np.ndarray, float]:
    lv = lufs(x)
    if not np.isfinite(lv):
        return x, 0.0
    return x * 10 ** ((target - lv) / 20), target - lv


def mix_audio(nar: np.ndarray, amb: np.ndarray, bgm: np.ndarray | None, levels: dict = LEVELS,
              duck: dict = DUCK) -> tuple[np.ndarray, dict]:
    info = {}
    nar, info["narr_gain_db"] = gain_to(nar, levels["narr"])
    amb, info["amb_gain_db"] = gain_to(amb, levels["amb"])
    mix = nar + amb * sidechain_gain(nar, duck["amb"])[:, None]
    if bgm is not None:
        bgm, info["bgm_gain_db"] = gain_to(bgm, levels["bgm"])
        mix = mix + bgm * sidechain_gain(nar, duck["bgm"])[:, None]
    info["pre_lufs"] = lufs(mix)
    mix, info["makeup_db"] = gain_to(mix, levels["target"])
    mix = tp_limit(mix, levels["ceiling"])
    info["lufs"] = lufs(mix)
    info["true_peak_dbtp"] = float(20 * np.log10(tp_peak_env(mix).max() + 1e-12))
    info["narr_lufs_in_mix"] = lufs(nar * 10 ** (info["makeup_db"] / 20))
    return mix, info


def write_wav(path: Path, x: np.ndarray) -> None:
    from scipy.io import wavfile
    wavfile.write(str(path), SR, np.clip(x, -1, 1).astype(np.float32))


# ───────────────────────── 主流程 ─────────────────────────

def resolve(tag: str, fixed: Path | None) -> Path:
    if fixed is not None and (fixed / f"{tag}.mp4").exists():
        return fixed / f"{tag}.mp4"
    p = CLIP_DIR / f"{tag}.mp4"
    if not p.exists():
        raise SystemExit(f"缺 clip：{p}（remaster 不生成 clip，先用 render.py 生成）")
    return p


def shot_dicts(planned) -> list[dict]:
    """同 render.main 寫出的 shots.json（bgm_synth 用）。"""
    return [{**p.shot.to_dict(), "title": p.title, "use_clips": [round(c, 2) for c in p.clips],
             "start": round(p.start, 2), "speeds": [round(x, 3) for x in p.speeds], "n_base": p.n_base}
            for p in planned]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapters", default="1,2,3")
    ap.add_argument("--max-seconds", type=float)
    ap.add_argument("--name", default="anqu_v2_test")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--clips-fixed", type=Path, default=FIXED_DIR, help="覆寫目錄：有同檔名 clip 就用它（假字修補版）")
    ap.add_argument("--no-clips-fixed", action="store_true")
    ap.add_argument("--narration-dir", type=Path, default=None, help="旁白目錄（預設 video_out/narration）")
    ap.add_argument("--no-bgm", action="store_true")
    ap.add_argument("--bgm-seed", type=int, default=7)
    ap.add_argument("--bgm-max-silence", type=float, default=10.0)
    ap.add_argument("--bgm-title-vel3", type=float, default=0.4, help="第三章標題鐘力度")
    ap.add_argument("--font", default="Microsoft JhengHei")
    ap.add_argument("--workers", type=int, default=2, help="同時準備（抽幀＋RIFE）的片段數")
    ap.add_argument("--keep-work", action="store_true")
    a = ap.parse_args(argv)

    t_all = time.time()
    if a.narration_dir:
        render.NARR_DIR = a.narration_dir
    narration = render.load_narration()
    if narration is None:
        raise SystemExit(f"找不到 {render.NARR_DIR / 'narration.json'}")
    chapters = [int(x) for x in a.chapters.split(",")]
    planned = render.plan(chapters, a.max_seconds, narration)
    specs = render.clip_specs(planned)
    fixed = None if a.no_clips_fixed else a.clips_fixed
    srcs = {sp["tag"]: resolve(sp["tag"], fixed) for sp in specs}
    times, ch_of = [], []
    for p in planned:
        t = p.start
        for c in p.clips:
            times.append((t, t + c))
            ch_of.append(bgm_synth._chapter_no(p.shot.chapter, 1))
            t += c
    a.out.mkdir(parents=True, exist_ok=True)
    work = a.out / f"{a.name}_work"
    work.mkdir(exist_ok=True)

    print(f"{len(planned)} shots / {len(specs)} 段 / {times[-1][1]:.2f}s；覆寫 clip："
          f"{sum(1 for p in srcs.values() if fixed and p.parent == fixed)} 段", flush=True)
    t0 = time.time()
    probes = {tag: probe_clip(p) for tag, p in srcs.items()}
    pieces = build_pieces(specs, times, ch_of, lambda tag: probes[tag], lambda tag: len(probes[tag][0]),
                          load_exposure(), src_of=lambda tag: str(srcs[tag]))
    check_timeline(pieces, times)
    n_total = pieces[-1].t0 + pieces[-1].n
    print(f"分析 {time.time() - t0:.0f}s：{len(pieces)} 片、{n_total} 幀（{n_total / FPS:.3f}s）", flush=True)

    ass = a.out / f"{a.name}.ass"
    ass.write_text(render.build_ass(planned, render.speaker_names(), a.font), encoding="utf-8")

    # 音訊（numpy/PCM，最後只編一次 AAC）
    t0 = time.time()
    n_samp = n_total * SPF
    amb = ambient_track(pieces, n_samp, work / "stretch.f32")
    (work / "stretch.f32").unlink(missing_ok=True)
    nar = narration_track(render.narration_events(planned), n_samp)
    bgm = None
    if not a.no_bgm:
        tl = bgm_synth.load_timeline(shot_dicts(planned), n_total / FPS)
        vel = dict(bgm_synth.TITLE_BELL_VEL)
        vel[3] = a.bgm_title_vel3
        bgm32, _, _ = bgm_synth.render(tl, a.bgm_seed, max_silence=a.bgm_max_silence, title_bell_vel=vel)
        bgm = fit_len(bgm32.astype(np.float64), n_samp)
    mix, ainfo = mix_audio(nar, amb, bgm)
    write_wav(work / "mix.wav", mix)
    write_wav(work / "amb.wav", amb * 10 ** (ainfo["amb_gain_db"] / 20))
    write_wav(work / "nar.wav", nar * 10 ** (ainfo["narr_gain_db"] / 20))
    print(f"音訊 {time.time() - t0:.0f}s：{json.dumps({k: round(v, 2) for k, v in ainfo.items()})}", flush=True)

    # 影像
    t0 = time.time()
    inter = work / "video.mkv"
    got = render_video(pieces, inter, work, a.workers)
    if got != n_total:
        raise RuntimeError(f"中間檔幀數 {got} ≠ 計畫 {n_total}")
    t_video = time.time() - t0
    print(f"影像 {t_video:.0f}s：{got} 幀", flush=True)

    # 成片：放大 → 統一調色 → 燒字幕（同 v1），音訊一次 AAC；影音都從 0 開始、長度相同
    t0 = time.time()
    final = a.out / f"{a.name}.mp4"
    ass_arg = ass.as_posix().replace(":", r"\:")
    vf = f"scale=1920:1080:flags=lanczos,setsar=1,{render.GRADE},subtitles='{ass_arg}'"
    ffrun("-i", str(inter), "-i", str(work / "mix.wav"), "-map", "0:v", "-map", "1:a", "-vf", vf,
          "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "192k", "-t", f"{n_total / FPS:.6f}",
          "-movflags", "+faststart", str(final))
    t_final = time.time() - t0
    meta = {"name": a.name, "chapters": chapters, "max_seconds": a.max_seconds, "frames": n_total,
            "seconds": n_total / FPS, "audio": ainfo, "bgm": None if a.no_bgm else
            {"seed": a.bgm_seed, "max_silence": a.bgm_max_silence, "title_vel3": a.bgm_title_vel3},
            "timing_s": {"total": round(time.time() - t_all, 1), "video": round(t_video, 1), "final_encode": round(t_final, 1)},
            "segments": [{**sp, "t0": times[i][0], "t1": times[i][1], "src": str(srcs[sp["tag"]])} for i, sp in enumerate(specs)],
            "pieces": [asdict(p) for p in pieces]}
    (a.out / f"{a.name}.pieces.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.keep_work:
        for p in work.glob("p*_*"):
            shutil.rmtree(p, ignore_errors=True)
        inter.unlink(missing_ok=True)
    print(f"完成：{final}（總耗時 {time.time() - t_all:.0f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
