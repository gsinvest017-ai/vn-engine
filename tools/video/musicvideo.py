"""音樂驅動的 MV 組裝器（Kalliwoda Romanze → jazz ballad）：依編曲段落與小節線把 H3 clip 排上時間軸。

用法（在工作樹根目錄）：
    python tools/video/musicvideo.py plan                  # 只排時間軸，印出／寫 schedule.json
    python tools/video/musicvideo.py build                 # 全片：P/_render/final/kalliwoda_jazz_v1.mp4
    python tools/video/musicvideo.py build --max-seconds 40 --name test40   # 試片

輸入：P/arrangement/sections.json、P/arrangement/leadsheet.json（每小節秒數）、P/visual/clips.json
     （＋review_notes.json 的 head／verdict）、P/_render/music/final/mix.wav。

時間軸規則
- 沒有 clip 的段落（interlude、link）併入下一個有 clip 的段落，成為一個「畫面組」。
- 組內切點只放在小節線上，優先樂句開頭（段落內每 4 小節）與段落起點；溶接以切點為中心。
  組內溶接 1.0 秒、組與組之間 1.5 秒（慵懶的慢溶接）。
- 每個 clip 從 head（H3 開頭的全景）之後取用；長度不夠就用 RIFE 慢放（≤1.3 倍），
  再不夠就多排一個鏡頭，重複用同組其他 clip（不連續重複；重用時取 clip 後段）。
影像：remaster.render_video（抽幀、RIFE、溶接）＋ frame_fx 做曝光匹配、低飽和分段調色（暖暗／冷藍）、
     局部失焦（假 logo）、片頭片尾壓暗；成片時放大 1080p、加膠片顆粒與暗角，再疊 PIL 畫的標題卡／署名卡。
音訊：mix.wav 為主；H3 clip 環境音（remaster.ambient_track）壓到 -44 LUFS 當酒吧底噪（-40 時節拍追蹤的拍點變異係數會升高，見 build 報告）；總響度 -16 LUFS、
     true peak ≤ -1 dBTP；音訊補零到整數幀，影音長度一致。
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import remaster as rm  # noqa: E402
from remaster import FPS, SPF, SR, Piece  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "projects" / "kalliwoda-jazz"
OUT_DIR = P / "_render" / "final"
RIFE_CANDIDATES = [
    rm.RIFE_DIR,
    ROOT / "_assets" / "rife-ncnn-vulkan-20221029-windows",
    Path(r"C:\Users\User\vn-engine-remaster\video_out\remaster_v2\tools_survey\bin\rife-ncnn-vulkan-20221029-windows"),
]

XF_INNER = 24          # 組內溶接 1.0 秒
XF_GROUP = 36          # 組間溶接 1.5 秒
MAX_SPEED = 1.3        # RIFE 慢放上限
MIN_SLOT_S = 5.0       # 一個鏡頭在時間軸上至少 5 秒
PHRASE = 4             # 樂句長度（小節）

# 可調的整體風格參數
LOOK = dict(
    sat=0.55,          # 整體飽和度
    amber=20.0,        # 亮部琥珀色偏（0–255 單位，乘上暖度）
    cool=15.0,         # 暗部冷藍色偏
    lift=6.0,          # 黑位微抬（膠片感）
    expo_strength=0.5, # 曝光匹配強度（往全片中位數拉的比例）
    expo_clamp=(0.85, 1.2),
    grain=5,           # ffmpeg noise 強度（亮度、時間性）
    vignette="PI/5",
)
# 每個畫面組的暖度（-1 冷藍 … +1 暖琥珀）
WARMTH = {"intro": 0.4, "head_ab": 0.5, "head_a2": 0.3, "piano_solo": 0.6, "theme2": -0.8,
          "return": 0.5, "coda": -0.2}
# 局部失焦（work 解析度 1056x608 座標）：review_notes 判 fix 的假 logo
BLUR_REGIONS = {"head_a2_02": [(835, 350, 955, 425), (835, 495, 960, 560)]}   # 鼓皮假 logo＋下方小壓印

# 片頭尾明暗（時間→亮度倍率）：(秒, 倍率) 線性內插；負秒數＝從片尾倒數
DIM_KEYS = [(0.0, 0.0), (3.0, 0.6), (10.5, 0.6), (13.5, 1.0),
            (-26.5, 1.0), (-22.5, 0.35), (-12.5, 0.35), (-7.5, 0.0)]

TITLE_FONT = "C:/Windows/Fonts/pala.ttf"
TITLE_FONT_I = "C:/Windows/Fonts/palai.ttf"
ZH_FONT = "C:/Windows/Fonts/msjhl.ttc"

# 標題卡／署名卡：(開始秒, 結束秒；負值＝從片尾倒數, 行)；行＝(文字, 字型, 字級, 透明度, 行後空白)
TITLE_CARD = [
    ("Romanze", "i", 112, 1.0, 24),
    ("after Johann Wenzel Kalliwoda · Concertino for Oboe, Op. 110", "r", 38, 0.92, 14),
    ("in the style of Chet Baker & Bill Evans", "i", 34, 0.85, 30),
    ("浪漫曲 — 改編自卡利沃達《雙簧管小協奏曲》作品 110", "zh", 28, 0.75, 0),
]
CREDIT_CARD_1 = [
    ("MUSIC", "r", 26, 0.6, 18),
    ("Johann Wenzel Kalliwoda — Concertino for Oboe, Op. 110 · II. Romanze (public domain)", "r", 32, 0.95, 10),
    ("Arranged as a jazz-trio waltz ballad in the style of Chet Baker & Bill Evans", "i", 30, 0.9, 6),
    ("A style homage only — not their performance; no real voice or likeness is used", "i", 26, 0.7, 30),
    ("SCORE", "r", 26, 0.6, 18),
    ("Transcription after IMSLP, engraving by Alex'Not (CC BY-SA 4.0)", "r", 30, 0.9, 6),
    ("and the Schott first edition (public domain)", "r", 30, 0.9, 30),
    ("原曲：卡利沃達《雙簧管小協奏曲》作品 110 第二樂章（公有領域）· 僅為風格致敬", "zh", 24, 0.7, 0),
]
CREDIT_CARD_2 = [
    ("SAMPLED INSTRUMENTS", "r", 26, 0.6, 18),
    ("Salamander Grand Piano V3 by Alexander Holm (CC-BY 3.0)", "r", 30, 0.92, 8),
    ("VSCO-2-CE (CC0)", "r", 30, 0.92, 8),
    ("Karoryfer Sneakybass · Frankensnare (CC0)", "r", 30, 0.92, 8),
    ("Virtuosity Drums (CC0)", "r", 30, 0.92, 30),
    ("PICTURE", "r", 26, 0.6, 18),
    ("AI-generated footage — no real persons or faces depicted", "i", 28, 0.85, 30),
    ("取樣音源授權如上；畫面為 AI 生成，未使用任何真人肖像或聲音", "zh", 24, 0.7, 0),
]
CARDS = [("title", 1.5, 11.5, TITLE_CARD), ("credits1", -24.5, -13.2, CREDIT_CARD_1),
         ("credits2", -12.4, -0.6, CREDIT_CARD_2)]
CARD_FADE = 1.5

# 署名必備字串（測試用：共同背景列出的每一項都要出現在卡片上）
REQUIRED_CREDITS = ["Kalliwoda", "Op. 110", "public domain", "in the style of Chet Baker & Bill Evans",
                    "IMSLP", "Alex'Not", "CC BY-SA 4.0", "Schott", "Salamander Grand Piano V3",
                    "Alexander Holm", "CC-BY 3.0", "VSCO-2-CE", "Karoryfer", "Virtuosity Drums", "CC0"]


# ───────────────────────── 時間軸 ─────────────────────────

@dataclass
class Group:
    name: str                   # clip 池的段落名
    sections: list[str]
    f0: int                     # 時間軸幀 [f0, f1)
    f1: int
    cands: list[tuple[int, float]] = field(default_factory=list)   # (切點幀, 懲罰)


@dataclass
class Shot:
    group: str
    clip: str
    use: int                    # 同一 clip 第幾次使用（0＝首次）
    c0: int                     # 時間軸槽位 [c0, c1)（溶接中心）
    c1: int
    xl: int
    xr: int

    @property
    def t0(self) -> int:
        return self.c0 - self.xl // 2

    @property
    def n(self) -> int:
        return self.c1 + self.xr // 2 - self.t0


def to_frame(s: float) -> int:
    return int(round(s * FPS))


def load_inputs(p: Path = P) -> tuple[dict, dict, list[dict]]:
    sections = json.loads((p / "arrangement" / "sections.json").read_text(encoding="utf-8"))
    lead = json.loads((p / "arrangement" / "leadsheet.json").read_text(encoding="utf-8"))
    clips = json.loads((p / "visual" / "clips.json").read_text(encoding="utf-8"))["clips"]
    notes_p = p / "visual" / "review_notes.json"
    notes = json.loads(notes_p.read_text(encoding="utf-8")) if notes_p.exists() else {}
    for c in clips:
        nt = notes.get(c["id"], {})
        if "head" in nt:
            c["head"] = nt["head"]
        c["verdict"] = nt.get("verdict", c.get("quality", "ok"))
    return sections, lead, clips


def build_groups(sections: list[dict], bars: list[dict], pools: dict[str, list], total_f: int) -> list[Group]:
    """段落 → 畫面組（沒 clip 的段落併入下一個有 clip 的段落；最後幾段沒有就併入前一組）。"""
    groups: list[Group] = []
    pending: list[dict] = []
    for s in sections:
        pending.append(s)
        if pools.get(s["name"]):
            groups.append(Group(s["name"], [x["name"] for x in pending], to_frame(pending[0]["start_s"]),
                                to_frame(s["end_s"])))
            pending = []
    if pending:
        groups[-1].sections += [x["name"] for x in pending]
        groups[-1].f1 = to_frame(pending[-1]["end_s"])
    groups[0].f0 = 0
    groups[-1].f1 = total_f
    sec_first = {}
    for b in bars:
        sec_first.setdefault(b["section"], b["bar"])
    for g in groups:
        for b in bars:
            f = to_frame(b["start_s"])
            if not (g.f0 < f < g.f1):
                continue
            k = b["bar"] - sec_first.get(b["section"], b["bar"])
            pen = 0.0 if k == 0 else 0.15 if k % PHRASE == 0 else 0.6 if k % 2 == 0 else 1.0
            g.cands.append((f, pen))
    return groups


def shot_sequence(pool: list[str], k: int) -> list[tuple[str, int]]:
    """k 個鏡頭的 clip 順序：先依序用完池子，再循環重用；保證相鄰不重複（池子只有 1 個時例外）。"""
    seq: list[tuple[str, int]] = []
    uses: dict[str, int] = {}
    i = 0
    while len(seq) < k:
        c = pool[i % len(pool)]
        i += 1
        if seq and seq[-1][0] == c and len(pool) > 1:
            continue
        seq.append((c, uses.get(c, 0)))
        uses[c] = uses.get(c, 0) + 1
    return seq


def plan_group(g: Group, pool: list[str], cap: dict[str, int], xl0: int, xr_end: int,
               xf: int = XF_INNER, max_extra: int = 3) -> list[Shot]:
    """組內切點（DP）：切點只在候選小節線；每鏡頭 n ≤ cap、槽位 ≥ MIN_SLOT_S；
    代價＝槽長偏離「依容量分配的理想長度」的相對平方 ×10 ＋ 切點懲罰。鏡頭數不夠就加重用鏡頭。"""
    min_slot = to_frame(MIN_SLOT_S)
    cands = sorted(g.cands)
    k0 = max(1, min(len(pool), (g.f1 - g.f0) // min_slot))      # 組太短（試片截斷）時少排幾個鏡頭
    for kk in list(range(k0, 0, -1)) + list(range(max(k0, len(pool)) + 1, len(pool) + max_extra + 1)):
        seq = shot_sequence(pool, kk)
        k = len(seq)
        caps = [cap[c] for c, _ in seq]
        tot = g.f1 - g.f0
        ideal = [tot * c / sum(caps) for c in caps]
        pts = [(g.f0, 0.0)] + cands + [(g.f1, 0.0)]
        m = len(pts)
        INF = float("inf")
        # best[j][i]: 前 j 個鏡頭、第 j 個鏡頭結束在 pts[i] 的最小代價
        best = [[INF] * m for _ in range(k + 1)]
        back = [[-1] * m for _ in range(k + 1)]
        best[0][0] = 0.0
        for j in range(1, k + 1):
            xl = xl0 if j == 1 else xf
            xr = xr_end if j == k else xf
            for i in range(1, m):
                if (j == k) != (i == m - 1):
                    continue
                for h in range(i):
                    if best[j - 1][h] == INF:
                        continue
                    slot = pts[i][0] - pts[h][0]
                    n = slot + xl // 2 + xr // 2
                    if slot < min_slot or n > caps[j - 1]:
                        continue
                    c = best[j - 1][h] + 10 * ((slot - ideal[j - 1]) / ideal[j - 1]) ** 2 + pts[i][1]
                    if c < best[j][i]:
                        best[j][i], back[j][i] = c, h
        if best[k][m - 1] < INF:
            idx = [m - 1]
            for j in range(k, 0, -1):
                idx.append(back[j][idx[-1]])
            idx.reverse()
            return [Shot(g.name, seq[j][0], seq[j][1], pts[idx[j]][0], pts[idx[j + 1]][0],
                         xl0 if j == 0 else xf, xr_end if j == k - 1 else xf) for j in range(k)]
    raise ValueError(f"{g.name}: clip 容量不足，加 {max_extra} 個重用鏡頭仍排不下")


def plan_timeline(groups: list[Group], pools: dict[str, list[str]], cap: dict[str, int]) -> list[Shot]:
    shots: list[Shot] = []
    for gi, g in enumerate(groups):
        xl0 = 0 if gi == 0 else XF_GROUP
        xr_end = 0 if gi == len(groups) - 1 else XF_GROUP
        shots += plan_group(g, pools[g.name], cap, xl0, xr_end)
    return shots


def check_shots(shots: list[Shot], total_f: int) -> None:
    assert shots[0].t0 == 0 and shots[-1].t0 + shots[-1].n == total_f
    for p, q in zip(shots, shots[1:]):
        assert p.c1 == q.c0 and p.xr == q.xl, (p, q)
        assert q.t0 == p.t0 + p.n - p.xr, (p, q)
        assert p.clip != q.clip, f"連續重複 {p.clip}"


def source_window(shot: Shot, head_f: int, total_src: int) -> tuple[int, int]:
    """原始幀區間 [a, b)：首次用 head 之後的前段；重用取後段；長度不足時用完整可用段（交給 RIFE 慢放）。"""
    usable = total_src - head_f
    m = min(shot.n, usable)
    if shot.use == 0:
        return head_f, head_f + m
    return total_src - m, total_src


# ───────────────────────── 調色與逐幀效果 ─────────────────────────

def grade(bgr: np.ndarray, warmth: float, look: dict = LOOK) -> np.ndarray:
    """低飽和＋分離色調：暗部偏冷藍、亮部偏琥珀（暖度越高琥珀越多；負值整體偏冷）。輸入輸出 float32 BGR 0–255。"""
    x = bgr.astype(np.float32)
    y = x[..., 0] * 0.114 + x[..., 1] * 0.587 + x[..., 2] * 0.299
    x = y[..., None] + look["sat"] * (x - y[..., None])
    yn = np.clip(y / 255.0, 0, 1)
    ws = (1 - yn) ** 2
    wh = yn ** 2
    w = float(np.clip(warmth, -1, 1))
    amber = look["amber"] * max(0.0, w)
    cool = look["cool"] * (0.6 + 0.4 * max(0.0, -w)) * (1 - 0.3 * max(0.0, w))
    blue_hi = look["cool"] * 0.6 * max(0.0, -w)
    x[..., 2] += wh * amber - ws * cool * 0.6 - wh * blue_hi * 0.5
    x[..., 1] += wh * amber * 0.45 + ws * cool * 0.15
    x[..., 0] += ws * cool - wh * amber * 0.6 + wh * blue_hi
    lift = look["lift"]
    x = x * (1 - lift / 255.0) + lift
    return np.clip(x, 0, 255)


def feather_mask(shape: tuple[int, int], box: tuple[int, int, int, int], feather: int = 18) -> np.ndarray:
    import cv2
    h, w = shape
    m = np.zeros((h, w), np.float32)
    x0, y0, x1, y1 = box
    cv2.ellipse(m, ((x0 + x1) // 2, (y0 + y1) // 2), ((x1 - x0) // 2, (y1 - y0) // 2), 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(m, (0, 0), feather)


def defocus(bgr: np.ndarray, boxes: list, sigma: float = 9.0) -> np.ndarray:
    import cv2
    out = bgr
    for box in boxes:
        m = feather_mask(bgr.shape[:2], box)[..., None]
        bl = cv2.GaussianBlur(out, (0, 0), sigma)
        out = out * (1 - m) + bl * m
    return out


def dim_at(t: float, total: float, keys: list = DIM_KEYS) -> float:
    pts = sorted(((k if k >= 0 else total + k), v) for k, v in keys)
    xs, vs = zip(*pts)
    return float(np.interp(t, xs, vs))


def expo_gamma(mean_y: float, target_y: float, look: dict = LOOK) -> float:
    """曝光匹配：把平均亮度往全片中位數拉 expo_strength，回傳 apply_eq 的 gamma。"""
    m = min(max(mean_y / 255.0, 1e-3), 0.999)
    t = min(max(target_y / 255.0, 1e-3), 0.999)
    g = math.log(m) / math.log(t)
    g = 1 + look["expo_strength"] * (g - 1)
    return float(np.clip(g, *look["expo_clamp"]))


def make_fx(tag_of: dict[int, str], warm_of: dict[int, float], total_f: int, look: dict = LOOK,
            blur: dict = BLUR_REGIONS):
    def fx(pc: Piece, k: int, fr: np.ndarray) -> np.ndarray:
        tag = tag_of[pc.seg]
        if tag in blur:
            fr = defocus(fr, blur[tag])
        fr = grade(fr, warm_of[pc.seg], look)
        d = dim_at((pc.t0 + k + 0.5) / FPS, total_f / FPS)
        return fr * d if d < 0.999 else fr
    return fx


# ───────────────────────── 字卡 ─────────────────────────

def _font(kind: str, size: int):
    from PIL import ImageFont
    path = {"r": TITLE_FONT, "i": TITLE_FONT_I, "zh": ZH_FONT}[kind]
    return ImageFont.truetype(path, size)


def render_card(lines: list, size: tuple[int, int] = (1920, 1080), color=(238, 230, 214)):
    """置中排版的 RGBA 字卡（含柔和陰影），回傳 PIL Image。"""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    fonts = [_font(kind, sz) for _, kind, sz, _, _ in lines]
    heights = [sum(f.getmetrics()) for f in fonts]          # 行高＝字型 ascent＋descent（不隨字母高低跳動）
    total = sum(heights) + sum(ln[4] for ln in lines[:-1])
    y = (h - total) // 2
    text = Image.new("L", size, 0)
    layers = []
    for (t, _, _, alpha, gap), f, hh in zip(lines, fonts, heights):
        lay = Image.new("L", size, 0)
        ImageDraw.Draw(lay).text((w // 2, y), t, font=f, fill=int(255 * alpha), anchor="ma")
        layers.append(lay)
        y += hh + gap
    for lay in layers:
        text = Image.fromarray(np.maximum(np.asarray(text), np.asarray(lay)))
    shadow = text.filter(ImageFilter.GaussianBlur(6))
    sh = np.asarray(shadow, np.float32) * 0.8
    tx = np.asarray(text, np.float32)
    rgba = np.zeros((h, w, 4), np.uint8)
    a = np.clip(tx + sh * (1 - tx / 255.0), 0, 255)
    col = np.array(color, np.float32)
    rgb = col[None, None, :] * (tx / np.maximum(a, 1))[..., None]
    rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    rgba[..., 3] = a.astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def card_times(total_s: float, cards=CARDS) -> list[tuple[str, float, float, list]]:
    return [(n, s if s >= 0 else total_s + s, e if e >= 0 else total_s + e, lines) for n, s, e, lines in cards]


def card_text(cards=CARDS) -> str:
    return "\n".join(t for _, _, _, lines in cards for t, *_ in lines)


# ───────────────────────── 音訊 ─────────────────────────

def pad_to_frames(x: np.ndarray) -> tuple[np.ndarray, int]:
    """補零到整數幀（每幀 SPF 取樣），回傳 (音訊, 幀數)。"""
    nf = -(-len(x) // SPF)
    return rm.fit_len(x, nf * SPF), nf


def build_audio(music: np.ndarray, amb: np.ndarray, amb_lufs: float = -40.0, target: float = -16.0,
                ceiling: float = -1.2) -> tuple[np.ndarray, dict]:
    info: dict = {"music_lufs_in": rm.lufs(music)}
    if np.abs(amb).max() > 0:
        amb, info["amb_gain_db"] = rm.gain_to(amb, amb_lufs)
        info["amb_lufs"] = rm.lufs(amb)
    mix = music + amb
    mix, info["makeup_db"] = rm.gain_to(mix, target)
    mix = rm.tp_limit(mix, ceiling)
    info["lufs"] = rm.lufs(mix)
    info["true_peak_dbtp"] = float(20 * np.log10(rm.tp_peak_env(mix).max() + 1e-12))
    return mix, info


# ───────────────────────── 主流程 ─────────────────────────

def probe_frames(path: Path) -> int:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v", "-show_entries",
                        "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


def find_rife(explicit: Path | None) -> Path:
    for d in ([explicit] if explicit else []) + RIFE_CANDIDATES:
        if d and (Path(d) / "rife-ncnn-vulkan.exe").exists():
            return Path(d)
    raise SystemExit("找不到 rife-ncnn-vulkan（用 --rife-dir 指定）")


def make_plan(p: Path = P, max_seconds: float | None = None):
    sections, lead, clips = load_inputs(p)
    secs = sections["sections"]
    total_s = sections["total_s"]
    if max_seconds:
        total_s = min(total_s, max_seconds)
        secs = [dict(s, end_s=min(s["end_s"], total_s)) for s in secs if s["start_s"] < total_s - 2]
    total_f = to_frame(total_s)
    usable = [c for c in clips if c["verdict"] in ("ok", "fix")]
    pools: dict[str, list[str]] = {}
    for c in usable:
        pools.setdefault(c["section"], []).append(c["id"])
    frames_of = {c["id"]: round(c.get("duration", 12.958) * FPS) for c in usable}
    head_of = {c["id"]: to_frame(c["head"]) for c in usable}
    cap = {cid: int(MAX_SPEED * (frames_of[cid] - head_of[cid])) for cid in frames_of}
    groups = build_groups(secs, lead["bars"], pools, total_f)
    shots = plan_timeline(groups, pools, cap)
    check_shots(shots, total_f)
    info = {c["id"]: c for c in usable}
    return dict(sections=sections, groups=groups, shots=shots, total_f=total_f, info=info,
                head_of=head_of, frames_of=frames_of, p=p)


def schedule_dict(plan: dict) -> dict:
    out = []
    for s in plan["shots"]:
        a, b = source_window(s, plan["head_of"][s.clip], plan["frames_of"][s.clip])
        out.append({**asdict(s), "t0_s": round(s.t0 / FPS, 3), "cut_s": round(s.c0 / FPS, 3),
                    "n": s.n, "src_frames": [a, b], "speed": round(s.n / (b - a), 3)})
    return {"total_frames": plan["total_f"], "total_s": plan["total_f"] / FPS,
            "groups": [{"name": g.name, "sections": g.sections, "f0": g.f0, "f1": g.f1} for g in plan["groups"]],
            "shots": out}


def build(a) -> int:
    t_all = time.time()
    rm.RIFE_DIR = find_rife(a.rife_dir)
    plan = make_plan(a.project, a.max_seconds)
    shots, total_f, p = plan["shots"], plan["total_f"], plan["p"]
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    work = out / f"{a.name}_work"
    work.mkdir(exist_ok=True)
    sched = schedule_dict(plan)
    print(f"{len(plan['groups'])} 組 / {len(shots)} 鏡頭 / {total_f} 幀（{total_f / FPS:.3f}s）", flush=True)

    # 曝光匹配：每個 clip 可用段的平均亮度 → 往中位數拉
    srcs = {cid: p / plan["info"][cid]["file"] for cid in {s.clip for s in shots}}
    mean_y = {}
    for cid, src in srcs.items():
        y, _, _ = rm.probe_clip(src)
        mean_y[cid] = float(np.mean(y[plan["head_of"][cid]:]))
    target_y = float(np.median(list(mean_y.values())))
    pieces, tag_of, warm_of = [], {}, {}
    for i, s in enumerate(shots):
        a0, b0 = source_window(s, plan["head_of"][s.clip], plan["frames_of"][s.clip])
        pc = Piece(seg=i, shot=i, tag=s.clip, src=str(srcs[s.clip]), a=a0, b=b0, n=s.n, t0=s.t0,
                   xl=s.xl, xr=s.xr, gamma=expo_gamma(mean_y[s.clip], target_y))
        pc.notes.append(f"speed {s.n / (b0 - a0):.3f}")
        pieces.append(pc)
        tag_of[i] = s.clip
        warm_of[i] = WARMTH.get(s.group, 0.0)
    n_total = pieces[-1].t0 + pieces[-1].n
    assert n_total == total_f

    # 音訊
    t0 = time.time()
    music = rm.decode_audio(p / "_render" / "music" / "final" / "mix.wav").astype(np.float64)
    if a.max_seconds:
        music = music[:total_f * SPF]
    music, nf = pad_to_frames(music)
    if nf != total_f:
        raise SystemExit(f"音樂 {nf} 幀 ≠ 時間軸 {total_f} 幀")
    amb = rm.ambient_track(pieces, total_f * SPF, work / "stretch.f32")
    (work / "stretch.f32").unlink(missing_ok=True)
    env = np.array([dim_at(i / SR, total_f / FPS, [(0.0, 0.0), (3.0, 1.0), (-12.0, 1.0), (-4.0, 0.0)])
                    for i in range(0, total_f * SPF, SPF)])
    amb = amb * np.repeat(env, SPF)[:, None]
    mix, ainfo = build_audio(music, amb, a.amb_lufs)
    rm.write_wav(work / "mix.wav", mix)
    print(f"音訊 {time.time() - t0:.0f}s：{json.dumps({k: round(v, 2) for k, v in ainfo.items()})}", flush=True)

    # 影像
    t0 = time.time()
    inter = work / "video.mkv"
    if a.reuse_video and inter.exists() and probe_frames(inter) == total_f:
        got = total_f                        # 只重做成片編碼（調字卡／顆粒／碼率時用）
    else:
        got = rm.render_video(pieces, inter, work, a.workers, frame_fx=make_fx(tag_of, warm_of, total_f))
    if got != total_f:
        raise RuntimeError(f"中間檔幀數 {got} ≠ 計畫 {total_f}")
    t_video = time.time() - t0
    print(f"影像 {t_video:.0f}s：{got} 幀", flush=True)

    # 字卡
    total_s = total_f / FPS
    cards = card_times(total_s)
    inputs, chains = [], []
    for j, (name, s0, s1, lines) in enumerate(cards):
        png = work / f"card_{name}.png"
        render_card(lines).save(png)
        d = s1 - s0
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", str(png)]
        chains.append(f"[{j + 2}:v]format=rgba,fade=t=in:st=0:d={CARD_FADE}:alpha=1,"
                      f"fade=t=out:st={d - CARD_FADE:.3f}:d={CARD_FADE}:alpha=1,setpts=PTS+{s0:.3f}/TB[c{j}]")
    fc = [f"[0:v]scale=1920:1080:flags=lanczos,setsar=1,noise=c0s={LOOK['grain']}:c0f=t,"
          f"vignette=angle={LOOK['vignette']}[v0]"] + chains
    last = "v0"
    for j in range(len(cards)):
        fc.append(f"[{last}][c{j}]overlay=eof_action=pass:format=auto[v{j + 1}]")
        last = f"v{j + 1}"
    fc.append(f"[{last}]format=yuv420p[vout]")
    t0 = time.time()
    final = out / f"{a.name}.mp4"
    rm.ffrun("-i", str(inter), "-i", str(work / "mix.wav"), *inputs, "-filter_complex", ";".join(fc),
             "-map", "[vout]", "-map", "1:a", "-c:v", "libx264", "-crf", str(a.crf), "-preset", "slow",
             "-maxrate", a.maxrate, "-bufsize", f"{2 * int(a.maxrate.rstrip('M'))}M",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
             "-c:a", "aac", "-b:a", "320k", "-frames:v", str(total_f), "-movie_timescale", str(SR),
             "-movflags", "+faststart", str(final))
    t_final = time.time() - t0
    meta = {"name": a.name, "frames": total_f, "seconds": total_s, "audio": ainfo, "look": LOOK, "warmth": WARMTH,
            "blur_regions": BLUR_REGIONS, "cards": [[n, round(s, 3), round(e, 3)] for n, s, e, _ in cards],
            "timing_s": {"total": round(time.time() - t_all, 1), "video": round(t_video, 1),
                         "final_encode": round(t_final, 1)},
            "exposure": {"target_y": target_y, "mean_y": mean_y},
            "schedule": sched, "pieces": [asdict(x) for x in pieces]}
    (out / f"{a.name}.timeline.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.keep_work:
        for q in work.glob("p*_*"):
            shutil.rmtree(q, ignore_errors=True)
        inter.unlink(missing_ok=True)
    print(f"完成：{final}（總耗時 {time.time() - t_all:.0f}s）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "build", "cards"])
    ap.add_argument("--project", type=Path, default=P)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--name", default="kalliwoda_jazz_v1")
    ap.add_argument("--max-seconds", type=float)
    ap.add_argument("--amb-lufs", type=float, default=-44.0)
    ap.add_argument("--rife-dir", type=Path)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--reuse-video", action="store_true", help="work/video.mkv 已存在且幀數對就跳過影像渲染")
    ap.add_argument("--crf", type=int, default=21)
    ap.add_argument("--maxrate", default="16M")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        plan = make_plan(a.project, a.max_seconds)
        sd = schedule_dict(plan)
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / f"{a.name}.schedule.json").write_text(json.dumps(sd, ensure_ascii=False, indent=1), encoding="utf-8")
        for s in sd["shots"]:
            print(f"{s['cut_s']:8.3f}s  {s['group']:<11} {s['clip']:<14} use{s['use']}  n={s['n']:4d} "
                  f"xl={s['xl']:2d} xr={s['xr']:2d} speed={s['speed']}")
        return 0
    if a.cmd == "cards":
        a.out.mkdir(parents=True, exist_ok=True)
        for name, _, _, lines in CARDS:
            render_card(lines).save(a.out / f"card_{name}.png")
        return 0
    return build(a)


if __name__ == "__main__":
    sys.exit(main())
