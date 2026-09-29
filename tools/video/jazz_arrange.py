"""Kalliwoda Op.110 第二樂章 Romanze → Chet Baker／Bill Evans 風爵士圓舞曲 ballad 編曲產生器。

只模仿風格：旋律是 Kalliwoda（公有領域）的 Romanze，和聲依 score/harmony.json 重配；不引用任何錄音。

用法（repo 根目錄）：
    python tools/video/jazz_arrange.py build [--seed 7] [--params params.json] [--out projects/kalliwoda-jazz/arrangement]
    python tools/video/jazz_arrange.py sfz                  # 產生 sound/sfz/trumpet_chet_combo.sfz、brush_jazz.sfz
    python tools/video/jazz_arrange.py finalize --render <render_report.json> [--sections ...]
    python tools/video/jazz_arrange.py events --out events.json   # 記譜用乾淨事件（給 jazz_score.py）

build 輸出（--out）：
    kalliwoda_ballad.mid   多軌 MIDI：conductor / trumpet / piano / bass / brush / hihat
    trumpet_ref.mid        只有小號（+ tempo）的參考 MIDI，給 listen.py review --ref
    sections.json          段落時間表（名稱、起訖秒數、小節範圍、原曲出處、情緒、建議畫面關鍵字）
    leadsheet.json         每小節和弦（重配後）與段落，給畫面／字幕用

設計：
- 時間單位一律是「拍」（四分音符），3/4 拍，第 b 小節（1 起算）從 3*(b-1) 拍開始。
  Romanze 原為 3/8：原曲八分音符 → 這裡的四分音符（時值 ×2），一小節對一小節。
- 移調：A♭ 大調 → E♭ 大調（−5 半音）；f 小調段落 → c 小調。
- 人性化隨機全部來自 random.Random(seed + 聲部編號)，同 seed 同參數 → 位元組相同的 MIDI。
- 調整用參數集中在 DEFAULT_PARAMS，可用 --params JSON 覆寫（AI 試聽迴圈就是改這裡與混音設定）。
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import jazz_render as jr  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PROJ = REPO / "projects" / "kalliwoda-jazz"
PCN = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
TRANSPOSE = -5          # A♭ → E♭
BEATS_PER_BAR = 3

DEFAULT_PARAMS: dict = {
    "bpm": 58.0,
    "swing": 0.63,                  # 反拍八分音在拍內的相位（0.5 直、0.667 三連音）
    "trumpet": {
        "lay_back": [0.06, 0.16],   # 每個樂句整體延後（拍）
        "jitter": 0.025,            # 個別音時間抖動（拍，標準差）
        "p_rhythm_variant": 0.55,   # 「三個四分音符」小節改寫節奏的機率
        "p_anticipate": 0.18,       # 樂句第一個強拍音提前到前一小節反拍
        "p_grace": 0.10,
        "p_passing": 0.30,
        "vel_base": 60, "vel_arch": 8, "vel_min": 42, "vel_max": 76,
        "breath_gap": 0.5,          # 樂句之間至少留幾拍
        "dim_to": 58,               # 長音漸弱終點（CC11）
        "phrase_end_dim_to": 40,
        "range": [55, 79],
        "offbeat_vel_drop": 9,      # 反拍（swing 八分音）放輕：Chet 式 back-phrasing，也讓節拍不被聽成倍速
        "harmon_theme2": True,
    },
    "piano": {"comp_vel": [36, 50], "p_rest": 0.12, "p_inner": 0.35, "p_fill": 0.7,
              "solo_vel": [50, 66], "solo_range": [65, 86], "pedal": True},
    "bass": {"vel_down": 80, "vel_other": 66, "p_approach": 0.55, "p_one": 0.15, "p_slide": 0.10,
             "range": [31, 50]},
    "drums": {"sweep_vel": 62, "tap_vel": 38, "ghost_vel": 20, "p_ghost": 0.2, "hat_vel": 36,
              "ride_vel": 34, "jitter": 0.012},
    "rit": {"start_bar_src": 81, "to_bpm": 50.0, "coda_bpm": 47.0, "last_bpm": 40.0},
}


# ───────────────────────── 基本型別 ─────────────────────────

@dataclass
class Note:
    start: float
    dur: float
    pitch: int
    vel: int = 60
    tag: str = ""           # "grace" / "passing" 等裝飾音標記（測試用）
    # 記譜用的「未人性化」位置（拍）：人性化（lay-back、抖動、琶音滾奏）之前的起點與時值。
    # 只記錄、不消耗亂數，MIDI 位元組不變；None = 沒有另外記錄（記譜端直接量化 start）。
    q_start: float | None = None
    q_dur: float | None = None
    mark: str = ""          # 記譜提示：phrase_end（樂句尾→換氣記號）／ghost／arpeggio_fermata／inner_src

    @property
    def end(self) -> float:
        return self.start + self.dur


@dataclass
class Chord:
    root: int               # pitch class
    qual: str               # maj7 69 maj7#11 dom alt sus m7 m6 m7b5 dim7 aug7
    bass: int               # pitch class（通常 = root；踏板音或轉位時不同）
    start: float = 0.0      # 絕對拍
    dur: float = 3.0

    def name(self) -> str:
        s = PCN[self.root] + QUAL_LABEL[self.qual]
        return s + (f"/{PCN[self.bass]}" if self.bass != self.root else "")


QUAL_LABEL = {"maj7": "maj9", "69": "6/9", "maj7#11": "maj7(#11)", "dom": "13", "alt": "7(b9,b13)",
              "sus": "9sus4", "m7": "m9", "m6": "m6/9", "m7b5": "m7b5", "dim7": "dim7", "aug7": "7(#5)"}
QUAL_TONES = {"maj7": [0, 4, 7, 11], "69": [0, 4, 7, 9], "maj7#11": [0, 4, 7, 11], "dom": [0, 4, 7, 10],
              "alt": [0, 4, 8, 10], "sus": [0, 5, 7, 10], "m7": [0, 3, 7, 10], "m6": [0, 3, 7, 9],
              "m7b5": [0, 3, 6, 10], "dim7": [0, 3, 6, 9], "aug7": [0, 4, 8, 10]}
QUAL_TENSIONS = {"maj7": [2, 9], "69": [2], "maj7#11": [2, 6], "dom": [2, 9], "alt": [1, 3, 8],
                 "sus": [2, 9], "m7": [2, 5], "m6": [2, 5], "m7b5": [5, 8], "dim7": [2, 5, 8, 11],
                 "aug7": [2]}
QUAL_SCALE = {"maj7": [0, 2, 4, 7, 9, 11], "69": [0, 2, 4, 7, 9, 11], "maj7#11": [0, 2, 4, 6, 7, 9, 11],
              "dom": [0, 2, 4, 7, 9, 10], "alt": [0, 1, 3, 4, 6, 8, 10], "sus": [0, 2, 5, 7, 9, 10],
              "m7": [0, 2, 3, 5, 7, 9, 10], "m6": [0, 2, 3, 5, 7, 9, 11], "m7b5": [0, 1, 3, 5, 6, 8, 10],
              "dim7": [0, 2, 3, 5, 6, 8, 9, 11], "aug7": [0, 2, 4, 6, 8, 10]}
# Rootless 左手 voicing（相對根音的半音數）：A 型從 3 度起、B 型從 7 度起；Q = 四度堆疊（So What 型）
VOICINGS = {
    "maj7": {"A": [4, 7, 11, 14], "B": [11, 14, 16, 19]},
    "69": {"A": [4, 7, 9, 14], "B": [9, 14, 16, 19]},
    "maj7#11": {"A": [4, 6, 11, 14], "B": [11, 14, 16, 18]},
    "dom": {"A": [4, 9, 10, 14], "B": [10, 14, 16, 21]},
    "alt": {"A": [4, 8, 10, 13], "B": [10, 13, 16, 20]},
    "sus": {"A": [5, 10, 14, 19], "B": [10, 14, 17, 19]},
    "m7": {"A": [3, 7, 10, 14], "B": [10, 14, 15, 19], "Q": [5, 10, 15, 19]},
    "m6": {"A": [3, 7, 9, 14], "B": [9, 14, 15, 19]},
    "m7b5": {"A": [3, 6, 10, 12], "B": [10, 12, 15, 18]},
    "dim7": {"A": [3, 6, 9, 14], "B": [9, 14, 15, 18]},
    "aug7": {"A": [4, 8, 10, 14], "B": [10, 14, 16, 20]},
}
# 內聲部線條：(從哪個音程, 移到哪個音程)，同一和弦延續時在拍 2–3 只動這一聲部
INNER_MOVES = {"maj7": [(7, 9), (14, 12)], "69": [(9, 7)], "dom": [(21, 20), (14, 13), (9, 8)],
               "m7": [(7, 8), (14, 12)], "m6": [(9, 10)], "sus": [(5, 4), (17, 16)], "maj7#11": [(6, 7)]}


def pc_of(name: str) -> int:
    n = _PC[name[0].upper()]
    for c in name[1:]:
        n += 1 if c == "#" else -1 if c == "b" else 0
    return n % 12


def parse_symbol(sym: str) -> tuple[int, str, int | None]:
    """'Ab7/Gb' → (8, '7', 6)；quality ∈ '', m, 7, maj7, m7, dim, dim7, m7b5, aug。"""
    m = re.match(r"^([A-G][b#]?)(maj7|m7b5|dim7|dim|aug|m7|m|7)?(?:/([A-G][b#]?))?$", sym.strip())
    if not m:
        raise ValueError(f"看不懂的和弦符號：{sym!r}")
    return pc_of(m.group(1)), m.group(2) or "", (pc_of(m.group(3)) if m.group(3) else None)


def note_name(p: int) -> str:
    return f"{PCN[p % 12]}{p // 12 - 1}"


def nearest(pc: int, ref: float, lo: int = 0, hi: int = 127) -> int:
    """pitch class pc 最接近 ref 的實際音高（限制在 [lo, hi]）。"""
    cands = [pc + 12 * k for k in range(11) if lo <= pc + 12 * k <= hi]
    if not cands:
        return int(max(lo, min(hi, round(ref))))
    return min(cands, key=lambda p: (abs(p - ref), p))


def key_scale(tonic: int, minor: bool) -> list[int]:
    steps = [0, 2, 3, 5, 7, 8, 10, 11] if minor else [0, 2, 4, 5, 7, 9, 11]
    return sorted((tonic + s) % 12 for s in steps)


def swing_pos(x: float, swing: float) -> float:
    """把拍內相位 0.5 的八分音反拍移到 swing；0.25/0.75 的十六分音也跟著等比例拉。"""
    b = math.floor(x + 1e-9)
    f = x - b
    if abs(f - 0.5) < 1e-6:
        return b + swing
    if abs(f - 0.25) < 1e-6:
        return b + swing / 2
    if abs(f - 0.75) < 1e-6:
        return b + swing + (1 - swing) / 2
    return x


# ───────────────────────── 原曲資料 ─────────────────────────

def load_source_melody(midi_path: Path) -> dict[int, list[tuple[float, float, int]]]:
    """solo_romanze.mid → {R 小節: [(小節內拍位置, 拍長, 音高)]}，已換成 3/4 拍（×2），未移調。"""
    mf = jr.read_smf(midi_path)
    tpb = mf.tpb
    out: dict[int, list] = {}
    for i in range(len(mf.tracks)):
        on: dict[int, int] = {}
        for t, m in mf.tracks[i]:
            st = m[0] & 0xF0
            if st == 0x90 and m[2] > 0:
                on[m[1]] = t
            elif st in (0x80, 0x90) and m[1] in on:
                t0 = on.pop(m[1])
                q0, qd = t0 / tpb, (t - t0) / tpb
                bar = int(q0 // 1.5 + 1e-9) + 1
                out.setdefault(bar, []).append((round((q0 - (bar - 1) * 1.5) * 2, 4), round(qd * 2, 4), m[1]))
    for v in out.values():
        v.sort()
    return out


def load_source_harmony(path: Path) -> dict[int, dict]:
    """harmony.json → {R 小節: {"key": (tonic_pc, minor), "chords": [(小節內拍, 符號)]}}（未移調）。"""
    h = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for b in h["bars"]:
        if not b["bar"].startswith("R"):
            continue
        k = b.get("key", "Ab major").split()
        out[int(b["bar"][1:])] = {"key": (pc_of(k[0]), k[1].lower() == "minor"),
                                  # 3/8 的第 n 個八分音 → 3/4 的第 n 拍，小節內位置 = n - 1
                                  "chords": [(float(c["beat"] - 1), c["symbol"]) for c in b["chords"]]}
    return out


# ───────────────────────── 段落規劃 ─────────────────────────

INTRO_HARM = [  # (小節內拍, root, qual, bass)
    [(0, "Eb", "69", "Eb")],
    [(0, "Ab", "m6", "Eb")],
    [(0, "Ab", "maj7#11", "Eb")],
    [(0, "Bb", "sus", "Bb")],
    [(0, "G", "m7", "G"), (2, "C", "alt", "C")],
    [(0, "F", "m7", "F")],
    [(0, "Bb", "sus", "Bb")],
    [(0, "Bb", "sus", "Bb"), (2, "Bb", "alt", "Bb")],
]
# 前奏右手：R3–R6 主題動機高八度（拍位置相對前奏起點, 拍長, 音高）
INTRO_RH = [(0.12, 0.9, 79), (1.1, 0.95, 82), (2.08, 0.9, 87),
            (3.1, 1.85, 75), (5.0, 0.55, 77), (5.64, 0.5, 79),
            (6.1, 0.9, 80), (7.08, 0.9, 84), (8.06, 0.9, 77),
            (9.3, 0.65, 79), (10.0, 0.6, 80), (10.63, 2.2, 82),
            (13.0, 1.5, 79), (14.63, 1.3, 76),
            (15.1, 1.6, 75), (17.0, 0.9, 72),
            (18.63, 2.2, 74), (21.0, 0.5, 72), (21.63, 0.3, 73), (22.0, 0.9, 70)]

PLAN: list[dict] = [
    {"name": "intro", "label": "前奏（鋼琴獨奏，主題動機）", "bars": 8, "harm": "intro", "melody": None,
     "trumpet": None, "piano": "intro", "bass": "intro", "drums": "intro",
     "source": "R3–R6 動機＋R84–R89 和聲色彩", "mood": "夜深、獨白、猶豫地開口",
     "visual": ["rain streaks on a dark window at night", "empty jazz club with one warm table lamp",
                "grand piano keys in soft focus, shallow depth of field", "blue-hour city lights bokeh"]},
    {"name": "head_ab", "label": "小號主題 a＋b", "src": list(range(3, 19)), "melody": "trumpet",
     "trumpet": "open", "piano": "comp", "bass": "two", "drums": "brush",
     "source": "R3–R18", "mood": "慵懶、溫柔地陳述",
     "visual": ["backlit trumpet silhouette with drifting haze, face hidden", "wet pavement under a lone street lamp",
                "slow dolly through an empty bar, chairs on tables", "reflections of neon in puddles"]},
    {"name": "head_a2", "label": "主題後半 a′（刪 R22–R28）", "src": [19, 20, 21] + list(range(29, 37)),
     "melody": "trumpet", "trumpet": "open", "piano": "comp", "bass": "two", "drums": "brush",
     "source": "R19–R21＋R29–R36", "mood": "情緒稍稍升起又放下",
     "visual": ["night city seen from a moving car, light streaks", "old photographs scattered on a wooden table",
                "curtain moving in the night breeze", "a half-empty glass catching lamp light"]},
    {"name": "piano_solo", "label": "鋼琴獨奏（主題和聲）", "src_harm": list(range(3, 19)), "melody": None,
     "trumpet": None, "piano": "solo", "bass": "walk", "drums": "ride",
     "source": "R3–R18 和聲進行", "mood": "內省、流動、輕輕搖擺",
     "visual": ["inside a grand piano: hammers and strings in warm light", "reflections gliding on a glossy piano lid",
                "drizzle on a skylight", "slow abstract light patterns"]},
    {"name": "interlude", "label": "間奏（轉 c 小調）", "src_harm": [41, 42, 43, 44], "melody": "piano",
     "trumpet": None, "piano": "melody", "bass": "two", "drums": "light",
     "source": "R41–R44", "mood": "陰影落下",
     "visual": ["clouds sliding over the moon", "an empty chair beside a rain-streaked window",
                "a clock pendulum in dim light"]},
    {"name": "theme2", "label": "小號第二主題（harmon 弱音器）", "src": list(range(49, 61)), "melody": "trumpet",
     "trumpet": "harmon", "skeleton": True, "piano": "comp", "bass": "two", "drums": "brush",
     "source": "R49–R60 骨幹", "mood": "寂寥、低語、帶點苦澀",
     "visual": ["a flickering neon sign in the rain, blue and violet", "fog over a harbour at night",
                "a lone boat light on dark water", "empty train platform at 3 a.m."]},
    {"name": "link", "label": "回主題的過門", "src_harm": [61, 62, 63], "melody": None,
     "trumpet": None, "piano": "comp", "bass": "two", "drums": "light",
     "source": "R61–R63", "mood": "轉身、微光",
     "visual": ["first grey light at the window edge", "steam rising from a cup"]},
    {"name": "return", "label": "回到主題", "src": list(range(64, 77)), "melody": "trumpet",
     "trumpet": "open", "piano": "comp", "bass": "two", "drums": "brush",
     "source": "R64–R76", "mood": "釋懷、更輕",
     "visual": ["the same street, now in pale dawn light", "a record spinning slowly",
                "sunlight crawling across wooden floorboards"]},
    {"name": "coda", "label": "尾聲（漸慢、下屬變格、延長和弦）", "src": list(range(77, 90)), "melody": "trumpet",
     "trumpet": "open", "piano": "coda", "bass": "coda", "drums": "coda",
     "source": "R77–R89", "mood": "告別、漸弱至無聲",
     "visual": ["a lamp switched off, room fading to dark", "last notes over an empty stage",
                "slow fade to black with end credits"]},
]


@dataclass
class BarInfo:
    index: int                   # 編曲小節（1 起算）
    section: str
    src: int | None              # 原曲 R 小節
    key: tuple[int, bool]        # 已移調
    chords: list[Chord] = field(default_factory=list)

    @property
    def start(self) -> float:
        return (self.index - 1) * BEATS_PER_BAR


def plan_bars(harm: dict[int, dict]) -> list[BarInfo]:
    bars: list[BarInfo] = []
    idx = 1
    for sec in PLAN:
        if sec.get("harm") == "intro":
            for spec in INTRO_HARM:
                b = BarInfo(idx, sec["name"], None, (3, False))
                b.chords = [Chord(pc_of(r), q, pc_of(bs), b.start + o) for o, r, q, bs in spec]
                bars.append(b)
                idx += 1
            continue
        for r in sec.get("src") or sec.get("src_harm"):
            h = harm[r]
            key = ((h["key"][0] + TRANSPOSE) % 12, h["key"][1])
            b = BarInfo(idx, sec["name"], r, key)
            bars.append(b)
            idx += 1
    return bars


# ───────────────────────── 重配和聲 ─────────────────────────

def _base_quality(root: int, q: str, key: tuple[int, bool], next_root: int | None, next_minor: bool) -> str:
    tonic, minor = key
    deg = (root - tonic) % 12
    resolves_down5 = next_root is not None and (root - next_root) % 12 == 7
    if q in ("", "maj7"):
        if not minor:
            if deg == 0:
                return "maj7"
            if deg == 5:
                return "maj7#11"
            if deg == 7:
                return "dom"
            if deg in (3, 8, 10):
                return "maj7"
            return "alt" if (resolves_down5 and next_minor) else "dom"
        if deg in (3, 8):
            return "maj7"
        if deg == 7:
            return "alt"
        if deg == 0:
            return "maj7"
        return "dom"
    if q == "7":
        if (resolves_down5 and next_minor) or (minor and deg == 7):
            return "alt"
        return "dom"
    if q in ("m", "m7"):
        if not minor and deg == 5:
            return "m6"      # 借用 iv
        if minor and deg == 0 and q == "m":
            return "m6"
        return "m7"
    if q in ("dim", "dim7"):
        return "dim7"
    if q == "m7b5":
        return "m7b5"
    if q == "aug":
        return "aug7"
    return "dom"


def reharm(bars: list[BarInfo], harm: dict[int, dict], rng: random.Random,
           p_iiv: float = 0.5, p_tritone: float = 0.3) -> None:
    """依 harmony.json 為每個（非前奏）小節填入重配後的 Chord。"""
    raw: list[tuple[BarInfo, float, int, str, int | None]] = []
    for b in bars:
        if b.src is None:
            continue
        for off, sym in harm[b.src]["chords"]:
            r, q, bs = parse_symbol(sym)
            raw.append((b, float(off), (r + TRANSPOSE) % 12, q, None if bs is None else (bs + TRANSPOSE) % 12))
    # 尾聲的下屬變格：R88 改成借用 iv（m6）
    for i, (b, off, r, q, bs) in enumerate(raw):
        if b.src == 88 and off == 0:
            raw[i] = (b, off, (b.key[0] + 5) % 12, "m", b.key[0])
    out: dict[int, list[Chord]] = {}
    for i, (b, off, r, q, bs) in enumerate(raw):
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        nroot = nxt[2] if nxt else None
        nminor = bool(nxt and nxt[3] in ("m", "m7", "m7b5"))
        qual = _base_quality(r, q, b.key, nroot, nminor)
        bass = r
        if bs is not None:
            if nxt and (bs - r) % 12 == 7 and nxt[3] == "7" and nxt[2] == bs:
                r, qual, bass = bs, "sus", bs            # 終止四六 → V7sus4
            elif bs in (b.key[0], (b.key[0] + 7) % 12):
                bass = bs                                  # 主音／屬音踏板
            elif (bs - r) % 12 in (3, 4, 10) and rng.random() < 0.5:
                bass = bs                                  # 轉位保留，讓低音線條走級進
        out.setdefault(b.index, []).append(Chord(r, qual, bass, b.start + off))
    for b in bars:
        if b.index not in out:
            continue
        chords = out[b.index]
        # ii–V：整小節只有一個屬七 → 前兩拍改成它的 ii
        if len(chords) == 1 and chords[0].qual in ("dom", "alt") and chords[0].bass == chords[0].root \
                and b.section not in ("coda",) and rng.random() < p_iiv:
            c = chords[0]
            ii = Chord((c.root + 7) % 12, "m7b5" if c.qual == "alt" else "m7", (c.root + 7) % 12, c.start)
            chords = [ii, Chord(c.root, c.qual, c.bass, c.start + 2)]
        b.chords = chords
    # 三全音代理：第 3 拍上、往下五度解決的屬七
    flat = [c for b in bars for c in b.chords]
    for i, c in enumerate(flat[:-1]):
        n = flat[i + 1]
        if c.qual == "dom" and c.bass == c.root and (c.start % 3) == 2 and (c.root - n.root) % 12 == 7 \
                and rng.random() < p_tritone:
            c.root = c.bass = (c.root + 6) % 12
    # 持續時間
    for i, c in enumerate(flat):
        c.dur = (flat[i + 1].start - c.start) if i + 1 < len(flat) else 6.0


# ───────────────────────── voicing ─────────────────────────

def voicing(ch: Chord, prev: list[int] | None, rng: random.Random, lo: int = 50, hi_top: int = 72,
            allow_q: bool = True) -> list[int]:
    """Rootless 左手 voicing：在 A/B（/Q）型與八度位置中挑與上一個 voicing 聲部移動最少者。"""
    forms = VOICINGS[ch.qual]
    cands = []
    for form, iv in forms.items():
        if form == "Q" and not (allow_q and rng.random() < 0.35):
            continue
        for octv in range(2, 7):
            ps = [ch.root + 12 * octv + x for x in iv]
            if lo <= ps[0] <= lo + 11 and ps[-1] <= hi_top:
                cands.append(ps)
    if not cands:
        ps = [ch.root + 48 + x for x in forms["A"]]
        while ps[0] < lo:
            ps = [p + 12 for p in ps]
        return ps
    if prev:
        def cost(ps):
            return sum(abs(a - b) for a, b in zip(sorted(ps), sorted(prev))) + 0.1 * abs(sum(ps) / 4 - 60)
    else:
        def cost(ps):
            return abs(sum(ps) / 4 - 59)
    best = min(cost(c) for c in cands)
    pool = [c for c in cands if cost(c) <= best + 1.0]
    return sorted(rng.choice(pool))


def chord_at(bars: list[BarInfo], beat: float) -> Chord:
    """beat 當下的和弦；bars 可以是整首或某一段的小節清單（依小節起點搜尋，不用索引）。"""
    idx = int(beat // BEATS_PER_BAR) + 1
    b = next((x for x in bars if x.index == idx), None)
    if b is None:
        b = min(bars, key=lambda x: abs(x.start - beat))
    cur = b.chords[0]
    for c in b.chords:
        if c.start <= beat + 1e-6:
            cur = c
    return cur


# ───────────────────────── 小號 ─────────────────────────

def skeletonize(notes: list[tuple[float, float, int]]) -> list[tuple[float, float, int]]:
    """快速音群（連續 ≥3 個短於半拍的音）只留頭尾：頭音延長到尾音起點。"""
    out, i = [], 0
    while i < len(notes):
        j = i
        while j < len(notes) and notes[j][1] < 0.5:
            j += 1
        if j - i >= 3:
            a, z = notes[i], notes[j - 1]
            out.append((a[0], round(z[0] - a[0], 4), a[2]))
            out.append((z[0], z[1], z[2]))
            i = j
        else:
            out.append(notes[i])
            i += 1
    return out


def base_trumpet_line(bars: list[BarInfo], mel: dict[int, list], sec: dict, rng_range: tuple[int, int]) -> list[Note]:
    notes: list[Note] = []
    for b in bars:
        if b.section != sec["name"] or b.src is None:
            continue
        src = mel.get(b.src, [])
        if sec.get("skeleton"):
            src = skeletonize(src)
        for off, dur, p in src:
            q = p + TRANSPOSE
            while q < rng_range[0]:
                q += 12
            while q > rng_range[1]:
                q -= 12
            notes.append(Note(b.start + off, dur, q))
    # 單音化：不重疊
    notes.sort(key=lambda n: n.start)
    for a, z in zip(notes, notes[1:]):
        if a.end > z.start:
            a.dur = max(0.1, z.start - a.start)
    return notes


def split_phrases(notes: list[Note], gap: float = 0.9) -> list[list[Note]]:
    phrases: list[list[Note]] = []
    for n in notes:
        if phrases:
            last = phrases[-1][-1]
            if n.start - last.end >= gap or last.dur >= 2.0:
                phrases.append([n])
                continue
            phrases[-1].append(n)
        else:
            phrases.append([n])
    return phrases


RHYTHM_VARIANTS = {  # 一小節三個四分音符 → 新的起點（小節內拍），可含前一小節反拍（負值）
    "long_short": [0.0, 1.63, 2.0],
    "drag": [0.33, 1.33, 2.0],
    "late3": [0.0, 1.0, 2.63],
    "push2": [0.0, 0.63, 2.0],
}


def rewrite_rhythm(notes: list[Note], swing: float, rng: random.Random, p_variant: float) -> None:
    """就地改寫：反拍八分音 swing；「三個四分音符」小節以機率套 RHYTHM_VARIANTS。"""
    by_bar: dict[int, list[Note]] = {}
    for n in notes:
        by_bar.setdefault(int(n.start // 3 + 1e-9), []).append(n)
    for bar, ns in by_bar.items():
        b0 = bar * 3
        offs = [round(n.start - b0, 3) for n in ns]
        if offs == [0.0, 1.0, 2.0] and all(abs(n.dur - 1.0) < 1e-6 for n in ns) and rng.random() < p_variant:
            new = RHYTHM_VARIANTS[rng.choice(sorted(RHYTHM_VARIANTS))]
            for n, o in zip(ns, new):
                n.start = b0 + o
            for a, z in zip(ns, ns[1:]):
                a.dur = z.start - a.start
            ns[-1].dur = b0 + 3 - ns[-1].start
            continue
        for n in ns:
            s = b0 + swing_pos(n.start - b0, swing)
            e = b0 + swing_pos(n.end - b0, swing) if n.end - b0 <= 3 + 1e-6 else n.end
            n.start, n.dur = s, max(0.12, e - s)


def ornament(notes: list[Note], key_pcs: list[int], rng: random.Random, p_grace: float,
             p_passing: float) -> list[Note]:
    out: list[Note] = []
    for i, n in enumerate(notes):
        nxt = notes[i + 1] if i + 1 < len(notes) else None
        prev = out[-1] if out else None
        # 倚音：長音前、半音從下方滑入
        if n.dur >= 1.0 and rng.random() < p_grace and (prev is None or n.start - prev.end >= 0.1
                                                          or prev.dur > 0.6):
            g0 = n.start - 0.14
            if prev is not None and prev.end > g0 - 0.02:
                prev.dur = max(0.3, g0 - 0.02 - prev.start)
            if prev is None or prev.end <= g0:
                out.append(Note(g0, 0.13, n.pitch - 1, 0, "grace"))
        out.append(n)
        # 經過音：長音後接三度 → 長音最後 0.37 拍換成中間的調內音
        if nxt and n.dur >= 1.6 and 3 <= abs(nxt.pitch - n.pitch) <= 4 and nxt.start - n.end < 0.3 \
                and rng.random() < p_passing:
            lo_, hi_ = sorted((n.pitch, nxt.pitch))
            mids = [p for p in range(lo_ + 1, hi_) if p % 12 in key_pcs]
            if mids:
                mid = mids[len(mids) // 2]
                cut = 0.37
                n.dur -= cut
                out.append(Note(n.end, cut, mid, 0, "passing"))
    return out


def humanize_trumpet(notes: list[Note], bars: list[BarInfo], rng: random.Random, P: dict, swing: float,
                     section_vel: float = 0.0) -> tuple[list[Note], list[tuple[float, int, int]]]:
    """回傳（音符, CC 事件 [(拍, cc, 值)]）。"""
    T = P["trumpet"]
    if not notes:
        return [], []
    rewrite_rhythm(notes, swing, rng, T["p_rhythm_variant"])
    notes.sort(key=lambda n: n.start)
    key = next((b.key for b in bars if b.index - 1 == int(notes[0].start // 3)), (3, False))
    notes = ornament(notes, key_scale(*key), rng, T["p_grace"], T["p_passing"])
    phrases = split_phrases(notes)
    out: list[Note] = []
    for ph in phrases:
        d = rng.uniform(*T["lay_back"])
        # 樂句頭提前（anticipation）：第一個音落在強拍、且與上一句距離夠
        if ph[0].tag == "" and abs(ph[0].start % 3) < 1e-6 and rng.random() < T["p_anticipate"] and \
                (not out or ph[0].start - out[-1].end > 1.0):
            ph[0].dur += 1 - swing
            ph[0].start -= 1 - swing
            d = 0.02
        n_ = len(ph)
        for k, n in enumerate(ph):
            jit = rng.gauss(0, T["jitter"]) if n.tag == "" else 0.0
            drag = 0.05 if n.dur >= 1.5 else 0.0
            n.q_start, n.q_dur = n.start, n.dur
            n.start += d + jit + drag
            pos = k / (n_ - 1) if n_ > 1 else 0.5
            v = T["vel_base"] + section_vel + T["vel_arch"] * math.sin(math.pi * min(1.0, pos * 1.15))
            v += rng.uniform(-4, 4) - (3 if n.dur >= 1.5 else 0)
            if n.tag:
                v -= 12
            ph_ = (n.start - d - jit - drag) % 1.0
            if 0.45 <= ph_ <= 0.8 and n.dur < 1.0:
                v -= T.get("offbeat_vel_drop", 0)
            n.vel = int(max(T["vel_min"] - (10 if n.tag else 0), min(T["vel_max"], v)))
        ph[-1].mark = "phrase_end"
        out.extend(ph)
    out.sort(key=lambda n: n.start)
    # 時值：連奏但同音要重新吐音；樂句尾留白
    phrase_last = {id(ph[-1]) for ph in phrases}
    for i, n in enumerate(out):
        nxt = out[i + 1] if i + 1 < len(out) else None
        if nxt is None:
            continue
        gap = 0.12 if nxt.pitch == n.pitch else 0.05
        if id(n) in phrase_last and not nxt.tag:
            gap = max(gap, T["breath_gap"]) if n.dur > 1.2 else max(gap, 0.25)
        n.dur = max(0.1, min(n.dur, nxt.start - gap - n.start))
        if n.end > nxt.start - 0.01:          # 很密的音（抖動後）仍要單音
            n.dur = max(0.03, nxt.start - 0.01 - n.start)
    ccs: list[tuple[float, int, int]] = []
    for i, n in enumerate(out):
        if n.tag:
            continue
        ccs.append((max(0.0, n.start - 0.02), 11, 100))
        if n.dur >= 1.4:
            end_v = T["phrase_end_dim_to"] if id(n) in phrase_last else T["dim_to"]
            hold = n.start + 0.35 * n.dur
            steps = 8
            for s in range(1, steps + 1):
                t = hold + (n.end - hold) * s / steps
                ccs.append((t, 11, int(round(100 + (end_v - 100) * s / steps))))
    return out, ccs


# ───────────────────────── 鋼琴 ─────────────────────────

COMP_PATTERNS = [  # (權重, [(小節內拍, 拍長)]) ；None 拍長 = 到下一個和弦前
    (3.0, [(0.0, None)]),
    (2.0, [(0.63, None)]),
    (1.5, [(0.0, 0.9), (1.63, None)]),
    (1.3, [(1.0, None)]),
    (1.0, [(0.0, 1.5), (2.63, None)]),   # 最後一下是下一小節和弦的提前
]


def _wchoice(rng: random.Random, items: list[tuple[float, object]]):
    tot = sum(w for w, _ in items)
    x = rng.random() * tot
    for w, it in items:
        x -= w
        if x <= 0:
            return it
    return items[-1][1]


def piano_comp(bars: list[BarInfo], rng: random.Random, P: dict, swing: float,
               busy: set[int] | None = None) -> tuple[list[Note], list[Chord]]:
    """稀疏伴奏：左手 rootless voicing，偶爾內聲部移動。回傳（音符, 實際有彈到的和弦清單（踏板用））。"""
    Pp = P["piano"]
    notes: list[Note] = []
    prev: list[int] | None = None
    skip_next_down = False
    for bi, b in enumerate(bars):
        nb = bars[bi + 1] if bi + 1 < len(bars) and bars[bi + 1].section == b.section else None
        chords = b.chords
        if len(chords) >= 2:
            pat = [(c.start - b.start + (0.63 if rng.random() < 0.3 and c.start == b.start else 0.0), None)
                   for c in chords]
        else:
            pat = _wchoice(rng, COMP_PATTERNS)
            if rng.random() < Pp["p_rest"] and bi > 0 and not skip_next_down:
                pat = []
        if skip_next_down:
            pat = [(o, d) for o, d in pat if o > 0.2] or ([(1.63, None)] if len(chords) == 1 else pat[1:])
            skip_next_down = False
        lo_v, hi_v = Pp["comp_vel"]
        for k, (o, d) in enumerate(pat):
            t = b.start + o
            antic = o > 2.5 and nb is not None
            ch = nb.chords[0] if antic else chord_at(bars, t)
            v = voicing(ch, prev, rng)
            prev = v
            if d is None:
                if antic:
                    end = nb.start + 2.8
                else:
                    later = [c.start for c in b.chords if c.start > t + 0.3] + \
                            [b.start + oo for oo, _ in pat[k + 1:]] + [b.start + 3.0]
                    end = min(later) - 0.08
                d = max(0.4, end - t)
            vel = rng.randint(lo_v, hi_v)
            roll = 0.0
            for j, p in enumerate(v):
                roll = j * rng.uniform(0.004, 0.018)
                notes.append(Note(t + roll + rng.gauss(0, 0.01), d - roll, p, vel - (3 if j in (1, 2) else 0),
                                  "antic" if antic else "", t, d))
            if antic:
                skip_next_down = True
            # 內聲部線條
            if d >= 2.2 and rng.random() < Pp["p_inner"] and ch.qual in INNER_MOVES:
                moves = [(a, z) for a, z in INNER_MOVES[ch.qual] if (ch.root + a) % 12 in {x % 12 for x in v}]
                if moves:
                    a, z = rng.choice(moves)
                    src = next(p for p in v if p % 12 == (ch.root + a) % 12)
                    tm = t + rng.choice([1.63, 2.0])
                    for nn in notes[-len(v):]:
                        if nn.pitch == src:
                            nn.dur = max(0.3, tm - nn.start - 0.03)
                            nn.q_dur = tm - t
                            nn.mark = "inner_src"      # 記譜：仍屬於這個 voicing，只是在內聲部移動點結束
                    notes.append(Note(tm, t + d - tm, src + (z - a), vel - 6, "inner", tm, t + d - tm))
    return notes, []


def trumpet_gaps(tr: list[Note], lo_beat: float, hi_beat: float, min_len: float = 1.8) -> list[tuple[float, float]]:
    gaps, last = [], lo_beat
    for n in sorted(tr, key=lambda n: n.start):
        if n.start < lo_beat or n.start > hi_beat:
            continue
        if n.start - last >= min_len:
            gaps.append((last, n.start))
        last = max(last, n.end)
    return gaps


def piano_fills(gaps: list[tuple[float, float]], bars: list[BarInfo], rng: random.Random, P: dict,
                swing: float) -> list[Note]:
    """小號換氣空檔裡的右手短句（Bill Evans 式回應），3–5 個音，落在和弦音上。"""
    notes: list[Note] = []
    for a, z in gaps:
        if rng.random() > P["piano"]["p_fill"]:
            continue
        t0 = math.ceil(a + 0.25) + (swing if rng.random() < 0.5 else 0.0)
        cur = rng.randint(74, 80)
        direction = rng.choice([-1, 1])
        t = t0
        k = rng.randint(3, 5)
        for i in range(k):
            if t > z - 0.35:
                break
            ch = chord_at(bars, t)
            scale = [(ch.root + s) % 12 for s in QUAL_SCALE[ch.qual]]
            tones = [(ch.root + s) % 12 for s in QUAL_TONES[ch.qual][1:] + QUAL_TENSIONS[ch.qual]]
            pool = tones if (i == k - 1 or abs(t - round(t)) < 1e-6) else scale
            cands = [p for p in range(cur - 5, cur + 6) if p % 12 in pool and (p - cur) * direction > 0] or \
                    [p for p in range(cur - 5, cur + 6) if p % 12 in pool]
            cur = min(cands, key=lambda p: (abs(p - cur), p))
            cur = max(70, min(86, cur))
            dur = 0.9 if i == k - 1 else (swing if abs(t - math.floor(t)) < 1e-6 else 1 - swing)
            off = 0.45 <= (t % 1.0) <= 0.8
            notes.append(Note(t + rng.gauss(0, 0.01), dur * 0.92, cur, rng.randint(40, 52) - (6 if off else 0),
                              "", t, dur))
            t = t + dur
    return notes


SOLO_BUSY = [[0.63, 1.0, 1.63, 2.0, 2.63], [0.0, 0.63, 1.0, 1.63, 2.0], [0.33, 0.67, 1.0, 1.63, 2.0, 2.63],
             [1.0, 1.63, 2.0, 2.63], [0.0, 1.0, 1.63, 2.0, 2.63]]
SOLO_END = [[(0.0, 0.6), (0.63, 0.35), (1.0, 1.6)], [(0.0, 2.0)], [(0.63, 1.2), (2.0, 0.9)], [(0.0, 0.9), (1.0, 1.8)]]


def piano_solo(bars: list[BarInfo], rng: random.Random, P: dict, swing: float) -> list[Note]:
    """鋼琴獨奏：右手旋律線（2 小節一句：一小節流動、一小節落地），左手 voicing。"""
    Pp = P["piano"]
    lo, hi = Pp["solo_range"]
    notes: list[Note] = []
    cur = 72
    direction = 1
    for bi, b in enumerate(bars):
        # 右手
        if bi == 0:        # 引用主題動機
            cells = [(0.1, 0.9, 67), (1.05, 0.9, 70), (2.0, 0.95, 75)]
            for o, d, p in cells:
                notes.append(Note(b.start + o, d, p, rng.randint(*Pp["solo_vel"])))
            cur = 75
        else:
            ends_phrase = bi % 2 == 1
            if ends_phrase:
                cell = rng.choice(SOLO_END)
            else:
                ons = rng.choice(SOLO_BUSY)
                cell = [(o, (ons[i + 1] - o) if i + 1 < len(ons) else 3.0 - o) for i, o in enumerate(ons)]
            for i, (o, d) in enumerate(cell):
                t = b.start + o
                ch = chord_at(bars, t)
                strong = abs(o - round(o)) < 1e-6
                tones = [(ch.root + s) % 12 for s in QUAL_TONES[ch.qual] + QUAL_TENSIONS[ch.qual]]
                scale = [(ch.root + s) % 12 for s in QUAL_SCALE[ch.qual]]
                pool = tones if strong or d >= 1.0 else scale
                if cur >= hi - 2:
                    direction = -1
                elif cur <= lo + 2:
                    direction = 1
                elif rng.random() < 0.22:
                    direction = -direction
                step = rng.choice([1, 1, 1, 2, 3]) * direction
                tgt = cur + step * 2
                cands = [p for p in range(lo, hi + 1) if p % 12 in pool]
                ahead = [p for p in cands if (p - cur) * direction > 0 and abs(p - cur) <= 5]
                cur = min(ahead or cands, key=lambda p: (abs(p - tgt), p))
                v = rng.randint(*Pp["solo_vel"]) + (3 if not strong else 0)
                notes.append(Note(t + rng.gauss(0, 0.012), max(0.2, d * 0.9), cur, v, "", t, d))
        # 左手
        for c in b.chords:
            o = c.start - b.start
            t = c.start + (0.63 if (o == 0 and rng.random() < 0.35) else 0.0)
            v = voicing(c, None if not notes else None, rng, lo=48, hi_top=66)
            dur = max(0.6, c.start + c.dur - t - 0.1)
            if rng.random() < 0.3 and c.dur >= 3:
                dur = 1.5
            for j, p in enumerate(v):
                notes.append(Note(t + j * 0.008, dur, p, rng.randint(40, 48), "", t, dur))
    # 半音接近：句中跨小節的音，下一個是強拍 → 換成下一音的上下半音
    rh = sorted([n for n in notes if n.pitch >= lo - 1], key=lambda n: n.start)
    for a, z in zip(rh, rh[1:]):
        if abs(z.start % 3) < 0.05 and z.start - a.end < 0.3 and abs(z.pitch - a.pitch) >= 2 and rng.random() < 0.35:
            a.pitch = z.pitch + (1 if a.pitch > z.pitch else -1)
    return notes


def piano_intro(bars: list[BarInfo], rng: random.Random) -> list[Note]:
    t0 = bars[0].start
    notes = [Note(t0 + o, d, p, rng.randint(44, 54)) for o, d, p in INTRO_RH]
    prev = None
    for b in bars:
        for c in b.chords:
            v = voicing(c, prev, rng, lo=48, hi_top=70, allow_q=False)
            prev = v
            t = c.start + (0.0 if c.start == b.start else 0.02)
            bass_pedal = nearest(c.bass, 43, 36, 50)
            if b.index <= 4:     # 前四小節低音還沒進來，鋼琴自己彈踏板低音
                notes.append(Note(t, c.dur - 0.05, bass_pedal, 46, "", c.start, c.dur))
            for j, p in enumerate(v):
                notes.append(Note(t + 0.02 + j * rng.uniform(0.02, 0.05), c.dur - 0.1 - j * 0.03, p, rng.randint(36, 44),
                                  "", c.start, c.dur))
    return notes


def piano_melody_section(bars: list[BarInfo], mel: dict[int, list], rng: random.Random) -> list[Note]:
    """間奏：右手彈原曲該段旋律（快速音群保留成琶音），左手 voicing。"""
    notes = []
    prev = None
    for b in bars:
        for off, dur, p in mel.get(b.src, []):
            q = p + TRANSPOSE
            while q < 62:
                q += 12
            while q > 86:
                q -= 12
            notes.append(Note(b.start + off + 0.03, max(0.12, dur * 0.95), q, rng.randint(44, 54), "",
                              b.start + off, dur))
        for c in b.chords:
            v = voicing(c, prev, rng, lo=48, hi_top=64)
            prev = v
            for j, p in enumerate(v):
                notes.append(Note(c.start + j * 0.01, c.dur - 0.1, p, rng.randint(36, 44), "", c.start, c.dur))
    return notes


def piano_coda(bars: list[BarInfo], rng: random.Random, P: dict, swing: float, final_hold: float) -> list[Note]:
    body, final = bars[:-1], bars[-1]
    notes, _ = piano_comp(body[:-5], rng, P, swing)
    prev = None
    for b in body[-5:]:
        for c in b.chords:
            v = voicing(c, prev, rng, lo=48, hi_top=70, allow_q=False)
            prev = v
            for j, p in enumerate(v):
                notes.append(Note(c.start + j * rng.uniform(0.03, 0.06), c.dur - 0.1, p, rng.randint(34, 42), "",
                                  c.start, c.dur))
    # 最後延長和弦：E♭6/9(maj7)，由低往高琶音
    root = final.chords[0].root
    chord = [root + 36, root + 43, root + 50, root + 55, root + 57, root + 62, root + 67, root + 74]
    for j, p in enumerate(chord):
        notes.append(Note(final.start + j * 0.11, final_hold - j * 0.11, p, 46 - j * 2 if j < 4 else 38, "",
                          final.start, final_hold, "arpeggio_fermata"))
    return notes


# ───────────────────────── 低音提琴 ─────────────────────────

def bass_line(bars: list[BarInfo], mode_of: dict[int, str], rng: random.Random, P: dict, swing: float,
              final_hold: float) -> list[Note]:
    B = P["bass"]
    lo, hi = B["range"]
    notes: list[Note] = []
    cur = 39
    flat = [c for b in bars for c in b.chords]
    nxt_of = {id(c): (flat[i + 1] if i + 1 < len(flat) else None) for i, c in enumerate(flat)}

    def pick(pc, ref=None):
        return nearest(pc, cur if ref is None else ref, lo, hi)

    def add(t, d, p, v, slide=False):
        nonlocal cur
        if slide and rng.random() < B["p_slide"]:
            notes.append(Note(t - 0.09, 0.08, p - 1, max(30, v - 25), "slide", t, 0.0))
        notes.append(Note(t + rng.gauss(0.01, 0.008), d, p, int(max(30, min(110, v + rng.uniform(-5, 5)))), "", t, d))
        cur = p

    for bi, b in enumerate(bars):
        mode = mode_of.get(bi, "two")
        if mode == "none":
            continue
        is_last = bi == len(bars) - 1
        if is_last:
            add(b.start, final_hold, pick(b.chords[0].bass, 34), B["vel_down"])
            continue
        if mode == "intro_long":
            c = b.chords[0]
            add(b.start, 2.9, pick(c.bass), B["vel_down"] - 12)
            continue
        if mode == "pedal":
            add(b.start, 2.8, pick(b.chords[0].bass, 39), B["vel_down"] - 10)
            continue
        if mode == "walk":
            for beat in range(3):
                t = b.start + beat
                c = chord_at(bars, t)
                nx = nxt_of.get(id(c))
                if abs(c.start - t) < 1e-6:
                    p = pick(c.bass)
                elif nx is not None and abs(nx.start - (t + 1)) < 1e-6 and rng.random() < 0.7:
                    tgt = pick(nx.bass)
                    p = tgt + rng.choice([-1, 1])
                else:
                    tones = [(c.root + s) % 12 for s in QUAL_TONES[c.qual][1:]] + \
                            [(c.root + s) % 12 for s in QUAL_SCALE[c.qual]]
                    p = min((pick(pc) for pc in tones if pick(pc) != cur),
                            key=lambda q: abs(q - cur - rng.choice([-3, 2, 4])), default=cur)
                add(t, 0.92, p, B["vel_down"] if beat == 0 else B["vel_other"])
                if beat == 1 and rng.random() < 0.12:      # 三連音 skip note
                    notes.append(Note(t + 0.67, 0.3, p + rng.choice([-2, 2]), 48, "skip", t + 2 / 3, 1 / 3))
            continue
        # two-feel / one-per-bar
        chords = b.chords
        if len(chords) >= 2:
            add(chords[0].start, chords[1].start - chords[0].start - 0.08, pick(chords[0].bass), B["vel_down"], True)
            add(chords[1].start, b.start + 3 - chords[1].start - 0.06, pick(chords[1].bass), B["vel_other"])
            continue
        c = chords[0]
        nx = nxt_of.get(id(c))
        r = pick(c.bass)
        if rng.random() < B["p_one"]:
            add(b.start, 2.85, r, B["vel_down"], True)
            continue
        add(b.start, 1.9, r, B["vel_down"], True)
        if nx is not None and nx.bass != c.bass and rng.random() < B["p_approach"]:
            tgt = nearest(nx.bass, r, lo, hi)
            p = tgt + rng.choice([-1, 1])
            if rng.random() < 0.35:
                add(b.start + 2 + swing, 1 - swing - 0.04, p, B["vel_other"] - 4)
            else:
                add(b.start + 2, 0.92, p, B["vel_other"])
        else:
            fifth = nearest((c.root + 7) % 12 if c.qual not in ("m7b5", "dim7", "alt") else (c.root + 10) % 12,
                            r, lo, hi)
            add(b.start + 2, 0.92, fifth, B["vel_other"])
    return notes


# ───────────────────────── 鼓 ─────────────────────────

KEY_SWEEP, KEY_SWEEP2, KEY_TAP, KEY_HAT_PEDAL, KEY_RIDE = 24, 25, 38, 44, 51  # 掃刷兩個鍵交替，避免同鍵重疊時 note-off 切掉下一刷


def drums(bars: list[BarInfo], mode_of: dict[int, str], rng: random.Random, P: dict, swing: float
          ) -> tuple[list[Note], list[Note]]:
    D = P["drums"]
    brush: list[Note] = []
    hat: list[Note] = []

    def j():
        return rng.gauss(0, D["jitter"])

    for bi, b in enumerate(bars):
        mode = mode_of.get(bi, "brush")
        if mode == "none":
            continue
        if mode == "fermata":        # 延長和弦底下刷子繼續慢慢畫圈、漸弱到無聲
            for k in range(6):
                v = D["sweep_vel"] * 0.7 * (1 - k / 7) + rng.uniform(-3, 3)
                brush.append(Note(b.start + k - 0.04 + j(), 1.15, KEY_SWEEP if k % 2 == 0 else KEY_SWEEP2,
                                  int(max(12, v)), "", b.start + k, 1.0))
            continue
        sweep_scale = {"sweep_soft": 0.7, "light": 0.85, "ride": 0.85}.get(mode, 1.0)
        # 掃刷：每拍一個，互相交疊（拍 1 稍重，形成圓圈的起點）
        for beat in range(3):
            v = D["sweep_vel"] * sweep_scale * (1.15 if beat == 0 else 0.92) + rng.uniform(-4, 4)
            brush.append(Note(b.start + beat - 0.04 + j(), 1.12, KEY_SWEEP if beat % 2 == 0 else KEY_SWEEP2, int(v),
                              "", b.start + beat, 1.0))
        if mode in ("sweep", "sweep_soft"):
            continue
        # 拍 2、3 輕拍
        tap_v = D["tap_vel"] * (0.8 if mode == "light" else 1.0)
        for beat in (1, 2):
            if mode == "ride" and beat == 1 and rng.random() < 0.5:
                continue
            brush.append(Note(b.start + beat + j(), 0.4, KEY_TAP, int(tap_v + rng.uniform(-5, 5)), "", b.start + beat, 1.0))
        if rng.random() < D["p_ghost"]:
            brush.append(Note(b.start + 2 + swing + j(), 0.3, KEY_TAP, int(D["ghost_vel"] + rng.uniform(-3, 3)), "",
                              b.start + 2 + swing, 1 - swing, "ghost"))
        # hi-hat 腳踩
        if mode in ("brush", "ride", "light"):
            hat.append(Note(b.start + 1 + j(), 0.3, KEY_HAT_PEDAL, int(D["hat_vel"] + rng.uniform(-4, 4)), "",
                            b.start + 1, 1.0))
            if mode != "light" and rng.random() < 0.6:
                hat.append(Note(b.start + 2 + j(), 0.3, KEY_HAT_PEDAL, int(D["hat_vel"] - 4 + rng.uniform(-4, 4)), "",
                                b.start + 2, 1.0))
        # ride（只在鋼琴獨奏）：1、2、2&、3
        if mode == "ride":
            for o, acc in ((0.0, 2), (1.0, 0), (1 + swing, -6), (2.0, 0)):
                hat.append(Note(b.start + o + j(), 0.5, KEY_RIDE, int(D["ride_vel"] + acc + rng.uniform(-3, 3)), "",
                                b.start + o, {1.0: swing, 1 + swing: 1 - swing}.get(o, 1.0)))
    return brush, hat


# ───────────────────────── 組裝 ─────────────────────────

def dedupe_overlaps(notes: list[Note], gap: float = 0.01, keys_ok: tuple[int, ...] = ()) -> list[Note]:
    """同一音高的音符若重疊（MIDI 同鍵 note-off 會切掉後一個），把前一個縮短到後一個起點前。"""
    last: dict[int, Note] = {}
    for n in sorted(notes, key=lambda n: n.start):
        if n.pitch in keys_ok:
            continue
        p = last.get(n.pitch)
        if p is not None and p.end > n.start - gap:
            p.dur = max(0.03, n.start - gap - p.start)
        last[n.pitch] = n
    return notes


def tempo_map(bars: list[BarInfo], P: dict) -> list[tuple[float, float]]:
    """[(拍, bpm)]：主體 58，尾聲 R81 起漸慢，R84 後更慢，最後一小節延長。"""
    R = P["rit"]
    bpm = P["bpm"]
    tm = [(0.0, bpm)]
    rit_bars = [b for b in bars if b.section == "coda" and b.src is not None and R["start_bar_src"] <= b.src <= 83]
    for k, b in enumerate(rit_bars):
        for beat in range(3):
            f = (k * 3 + beat + 1) / (len(rit_bars) * 3)
            tm.append((b.start + beat, round(bpm + (R["to_bpm"] - bpm) * f, 2)))
    slow = [b for b in bars if b.section == "coda" and b.src is not None and b.src >= 84]
    for k, b in enumerate(slow):
        last = k == len(slow) - 1
        tm.append((b.start, R["last_bpm"] if last else round(R["coda_bpm"] - k * 1.0, 2)))
    return tm


def merge_params(over: dict | None) -> dict:
    P = copy.deepcopy(DEFAULT_PARAMS)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(P.get(k), dict):
            P[k].update(v)
        else:
            P[k] = v
    return P


def build(seed: int = 7, params: dict | None = None, score_dir: Path | None = None) -> dict:
    """產生整份編曲；回傳 {"builder", "bars", "sections", "parts", "tempo"}（不寫檔）。"""
    P = merge_params(params)
    score_dir = score_dir or PROJ / "score"
    mel = load_source_melody(score_dir / "solo_romanze.mid")
    harm = load_source_harmony(score_dir / "harmony.json")
    bars = plan_bars(harm)
    reharm(bars, harm, random.Random(seed + 1))
    swing = P["swing"]
    sec_bars = {s["name"]: [b for b in bars if b.section == s["name"]] for s in PLAN}
    final_hold = 7.0

    # 小號
    trumpet: list[Note] = []
    tr_cc: list[tuple[float, int, int]] = []
    rng_t = random.Random(seed + 2)
    sec_vel = {"head_ab": 0, "head_a2": 3, "theme2": -2, "return": -3, "coda": -6}
    for sec in PLAN:
        if not sec.get("trumpet"):
            continue
        base = base_trumpet_line(bars, mel, sec, tuple(P["trumpet"]["range"]))
        ns, cc = humanize_trumpet(base, sec_bars[sec["name"]], rng_t, P, swing, sec_vel.get(sec["name"], 0))
        mute = 127 if (sec["trumpet"] == "harmon" and P["trumpet"]["harmon_theme2"]) else 0
        first = min((n.start for n in ns), default=sec_bars[sec["name"]][0].start)
        tr_cc.append((max(0.0, min(first - 0.5, sec_bars[sec["name"]][0].start)), 110, mute))
        trumpet += ns
        tr_cc += cc
    # 尾聲最後的長音：縮成約 5.5 拍並淡出
    last = max(trumpet, key=lambda n: n.start)
    last.dur = min(last.dur, 5.5)
    tr_cc = [c for c in tr_cc if not (c[0] > last.start and c[1] == 11)]
    for s in range(1, 11):
        tr_cc.append((last.start + 0.3 * last.dur + 0.7 * last.dur * s / 10, 11, int(100 - 72 * s / 10)))

    # 鋼琴
    rng_p = random.Random(seed + 3)
    piano: list[Note] = []
    for sec in PLAN:
        bs = sec_bars[sec["name"]]
        mode = sec["piano"]
        if mode == "intro":
            piano += piano_intro(bs, rng_p)
        elif mode == "comp":
            ns, _ = piano_comp(bs, rng_p, P, swing)
            piano += ns
            gaps = trumpet_gaps([n for n in trumpet if not n.tag], bs[0].start, bs[-1].start + 3)
            piano += piano_fills(gaps, bars, rng_p, P, swing)
        elif mode == "solo":
            piano += piano_solo(bs, rng_p, P, swing)
        elif mode == "melody":
            piano += piano_melody_section(bs, mel, rng_p)
        elif mode == "coda":
            piano += piano_coda(bs, rng_p, P, swing, final_hold)
    piano_cc: list[tuple[float, int, int]] = []
    if P["piano"]["pedal"]:
        for c in [c for b in bars for c in b.chords]:
            piano_cc.append((max(0.0, c.start - 0.04), 64, 0))
            piano_cc.append((c.start + 0.1, 64, 90))

    # 低音
    bass_mode: dict[int, str] = {}
    for i, b in enumerate(bars):
        sec = next(s for s in PLAN if s["name"] == b.section)
        m = sec["bass"]
        if m == "intro":
            m = "none" if b.index <= 4 else "intro_long"
        elif m == "coda":
            m = "pedal" if (b.src or 0) >= 84 else "two"
        bass_mode[i] = m
    bass = bass_line(bars, bass_mode, random.Random(seed + 4), P, swing, final_hold)

    # 鼓
    drum_mode: dict[int, str] = {}
    for i, b in enumerate(bars):
        sec = next(s for s in PLAN if s["name"] == b.section)
        m = sec["drums"]
        if m == "intro":
            m = "sweep_soft"                       # 前奏只有很輕的掃刷，給節拍一個底
        elif m == "coda":
            m = "brush" if (b.src or 0) <= 80 else ("sweep" if (b.src or 0) <= 86 else
                                                    ("sweep_soft" if (b.src or 0) <= 88 else "fermata"))
        drum_mode[i] = m
    brush, hat = drums(bars, drum_mode, random.Random(seed + 5), P, swing)

    # 寫入 MIDI
    mb = jr.MidiBuilder(bpm=P["bpm"], time_sig=(3, 4))
    for t, bpm in tempo_map(bars, P)[1:]:
        mb.tempo(t, bpm)
    for name, ch in (("trumpet", 0), ("piano", 1), ("bass", 2), ("brush", 3), ("hihat", 4)):
        mb.track(name, ch)
    mb.cc("trumpet", 0, 11, 100)
    mb.cc("trumpet", 0, 110, 0)
    for t, num, val in sorted(tr_cc):
        mb.cc("trumpet", t, num, val)
    for t, num, val in sorted(piano_cc):
        mb.cc("piano", t, num, val, 1)
    parts = {"trumpet": trumpet, "piano": piano, "bass": bass, "brush": brush, "hihat": hat}
    for k in parts:
        dedupe_overlaps(parts[k], keys_ok=(KEY_SWEEP, KEY_SWEEP2) if k == "brush" else ())
    for name, ch in (("trumpet", 0), ("piano", 1), ("bass", 2), ("brush", 3), ("hihat", 4)):
        for n in parts[name]:
            mb.note(name, max(0.0, n.start), max(0.03, n.dur), n.pitch, max(1, n.vel), ch)
    end_beat = bars[-1].start + final_hold + 1.0
    mb.cc("piano", end_beat - 0.3, 64, 0, 1)      # 最後放踏板（否則取樣器會一直延音）
    mb.end(end_beat)
    return {"builder": mb, "bars": bars, "parts": parts, "params": P, "seed": seed, "end_beat": end_beat}


def clean_events(res: dict) -> dict:
    """記譜用的乾淨事件：每個聲部的音符，含未人性化的 q_start/q_dur（拍），以及實際寫進 MIDI 的 start/dur。

    q_start 為 None 的音（前奏右手是手寫的微偏移）由記譜端量化。另附小節和弦與 tempo map。"""
    parts = {}
    for name, ns in res["parts"].items():
        parts[name] = [{"pitch": n.pitch, "vel": n.vel, "tag": n.tag, "mark": n.mark,
                        "q_start": None if n.q_start is None else round(n.q_start, 6),
                        "q_dur": None if n.q_dur is None else round(n.q_dur, 6),
                        "start": round(n.start, 6), "dur": round(n.dur, 6)}
                       for n in sorted(ns, key=lambda n: (n.start, n.pitch))]
    return {"seed": res["seed"], "swing": res["params"]["swing"], "beats_per_bar": BEATS_PER_BAR,
            "tempo": tempo_map(res["bars"], res["params"]), "end_beat": res["end_beat"],
            "bars": [{"bar": b.index, "section": b.section, "src": b.src,
                      "chords": [{"beat": round(c.start - b.start + 1, 3), "name": c.name()} for c in b.chords]}
                     for b in res["bars"]],
            "parts": parts}


def sections_table(res: dict) -> list[dict]:
    mf = res["builder"].mf
    tpb = mf.tpb
    bars = res["bars"]
    last_note_end = max(n.end for p in res["parts"].values() for n in p)
    out = []
    for sec in PLAN:
        bs = [b for b in bars if b.section == sec["name"]]
        s_beat = bs[0].start
        nxt = [b for b in bars if b.index == bs[-1].index + 1]
        e_beat = nxt[0].start if nxt else last_note_end
        srcs = [b.src for b in bs if b.src]
        out.append({
            "name": sec["name"], "label": sec["label"],
            "start_s": round(mf.tick_to_sec(int(round(s_beat * tpb))), 3),
            "end_s": round(mf.tick_to_sec(int(round(e_beat * tpb))), 3),
            "bars": [bs[0].index, bs[-1].index],
            "source_bars": sec["source"], "source_bar_list": [f"R{r}" for r in srcs],
            "lead": sec.get("melody") or "piano", "trumpet": sec.get("trumpet"),
            "mood": sec["mood"], "visual_keywords": sec["visual"],
        })
    return out


def leadsheet(res: dict) -> dict:
    mf = res["builder"].mf
    return {"key": "Eb major (theme2: C minor)", "time": "3/4", "bpm": res["params"]["bpm"],
            "bars": [{"bar": b.index, "section": b.section, "src": f"R{b.src}" if b.src else None,
                      "start_s": round(mf.tick_to_sec(int(round(b.start * mf.tpb))), 3),
                      "chords": [{"beat": round(c.start - b.start + 1, 2), "name": c.name()} for c in b.chords]}
                     for b in res["bars"]]}


def write_outputs(res: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    mf = res["builder"].save(out_dir / "kalliwoda_ballad.mid")
    idx = jr.find_track(mf, "trumpet")
    jr.write_smf(out_dir / "trumpet_ref.mid", jr.split_track(mf, idx))
    secs = sections_table(res)
    meta = {"seed": res["seed"], "params": res["params"], "total_s": secs[-1]["end_s"],
            "midi": "kalliwoda_ballad.mid", "note": "秒數來自 MIDI tempo map；finalize 後以實際渲染長度校正",
            "credits": CREDITS, "sections": secs}
    (out_dir / "sections.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "leadsheet.json").write_text(json.dumps(leadsheet(res), ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


CREDITS = {
    "style_note": "in the style of Chet Baker & Bill Evans（僅風格模仿，非其演奏、非其聲音）",
    "work": "Johann Wenzel Kalliwoda: Oboe Concertino Op.110, II. Romanze（公有領域）",
    "score_sources": ["IMSLP Alex'Not 打譜（CC BY-SA 4.0）", "Schott 初版（公有領域）"],
    "samples": ["Salamander Grand Piano V3 by Alexander Holm（CC-BY 3.0）", "VSCO-2-CE（CC0）",
                "Karoryfer Sneakybass / Frankensnare（CC0）", "Virtuosity Drums（CC0）"],
}


def finalize(sections_path: Path, render_report: Path, trumpet_stem: Path | None = None) -> dict:
    """以實際渲染結果校正 sections.json：總長 = 混音長度；量測小號第一個音的實際起點與預測差。"""
    meta = json.loads(sections_path.read_text(encoding="utf-8"))
    rep = json.loads(render_report.read_text(encoding="utf-8"))
    dur = rep["mix"]["duration_s"]
    meta["sections"][-1]["end_s"] = round(dur, 3)
    meta["total_s"] = round(dur, 3)
    meta["mix_lufs"] = rep["mix"].get("lufs_integrated")
    meta["mix_true_peak_dbtp"] = rep["mix"].get("true_peak_dbtp")
    if trumpet_stem and trumpet_stem.exists():
        import numpy as np
        x = jr.load_wav(trumpet_stem).mean(axis=1)
        env = np.abs(x)
        thr = env.max() * 10 ** (-40 / 20)
        first = int(np.argmax(env > thr)) / jr.SR
        pred = next(s for s in meta["sections"] if s.get("trumpet"))["start_s"]
        meta["check_trumpet_first_onset_s"] = {"measured": round(first, 3), "section_start": pred}
    meta["note"] = "秒數：各段起點來自 MIDI tempo map（渲染從 0 秒開始、無位移）；最後一段終點＝實際混音長度"
    sections_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


# ───────────────────────── 音色（SFZ）輔助 ─────────────────────────

_SAMPLE_RE = re.compile(r"_([A-G]#?)(-?\d)_v(\d)(?:_rr(\d))?\.wav$")


def scan_vsco(folder: Path) -> dict[int, dict[int, list[str]]]:
    """VSCO2 檔名（C3 = MIDI 60）→ {midi: {力度層: [檔名]}}。"""
    out: dict[int, dict[int, list[str]]] = {}
    for f in sorted(Path(folder).glob("*.wav")):
        m = _SAMPLE_RE.search(f.name)
        if m:
            midi = (int(m.group(2)) + 2) * 12 + {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7,
                                                  "G#": 8, "A": 9, "A#": 10, "B": 11}[m.group(1)]
            out.setdefault(midi, {}).setdefault(int(m.group(3)), []).append(f.name)
    return out


def _ranges(notes: list[int], ext_lo: int, ext_hi: int) -> dict[int, tuple[int, int]]:
    r = {}
    for i, n in enumerate(notes):
        lo = notes[i - 1] + (n - notes[i - 1]) // 2 + 1 if i else n - ext_lo
        hi = n + (notes[i + 1] - n) // 2 if i + 1 < len(notes) else n + ext_hi
        r[n] = (lo, hi)
    return r


def trumpet_combo_sfz(trumpet_dir: Path, rel_prefix: str, cfg: dict | None = None) -> str:
    """open（CC110 < 64）與 harmon（CC110 ≥ 64）合一的 Chet 風小號 SFZ。

    open：v1（暗）與 v3（亮）依力度交叉淡化，v3 壓低 v3_volume dB，讓 ballad 力度下亮度約 −15～−19 dB
    （原本只用 v1 時 2 kHz 以上只有 0.5%，過悶）；另疊一層帶通雜訊當氣音（breath_db）。"""
    c = {"open_cutoff": 3400, "open_veltrack": 1800, "v3_volume": -20, "xfin": [20, 110], "xfout": [60, 127],
         "harmon_cutoff": 2600, "harmon_veltrack": 900, "harmon_volume": -2, "breath_db": -48,
         "breath_cutoff": 5000}
    c.update(cfg or {})
    lines = ["// Chet 風小號：open / harmon（CC110 切換）＋氣音層；自動產生：tools/video/jazz_arrange.py sfz",
             "// 樣本 VSCO-2-CE（CC0）", "<control>", f"default_path={rel_prefix}", "",
             "<global>", "ampeg_attack=0.05", "ampeg_release=0.35", "amp_veltrack=70", "fil_type=lpf_2p",
             "resonance=0", ""]
    sus = scan_vsco(trumpet_dir / "sus")
    notes = sorted(sus)
    kr = _ranges(notes, 4, 3)
    lines += ["<master> hicc110=63", f"cutoff={c['open_cutoff']}", f"fil_veltrack={c['open_veltrack']}"]
    for n in notes:
        lo, hi = kr[n]
        layers = sus[n]
        if 1 in layers:
            lines.append(f"<group> lokey={lo} hikey={hi} pitch_keycenter={n} xfout_lovel={c['xfout'][0]} "
                         f"xfout_hivel={c['xfout'][1]}")
            lines.append(f"<region> sample=sus/{layers[1][0]}")
        if 3 in layers:
            lines.append(f"<group> lokey={lo} hikey={hi} pitch_keycenter={n} xfin_lovel={c['xfin'][0]} "
                         f"xfin_hivel={c['xfin'][1]} volume={c['v3_volume']}")
            lines.append(f"<region> sample=sus/{layers[3][0]}")
    hm = scan_vsco(trumpet_dir / "harmonM-sus")
    hn = sorted(hm)
    hk = _ranges(hn, 4, 5)
    lines += ["", "<master> locc110=64", f"cutoff={c['harmon_cutoff']}", f"fil_veltrack={c['harmon_veltrack']}",
              f"volume={c['harmon_volume']}"]
    for n in hn:
        lo, hi = hk[n]
        lay = hm[n]
        v = 1 if 1 in lay else min(lay)
        lines.append(f"<group> lokey={lo} hikey={hi} pitch_keycenter={n}")
        lines.append(f"<region> sample=harmonM-sus/{lay[v][0]}")
    lines += ["", "// 氣音：帶通雜訊，起音明顯、持續音時很淡",
              f"<master> volume={c['breath_db']} fil_type=bpf_2p cutoff={c['breath_cutoff']} ampeg_attack=0.01 "
              "ampeg_decay=0.22 ampeg_sustain=25 ampeg_release=0.2 amp_veltrack=100",
              f"<region> sample=*noise lokey={notes[0] - 6} hikey={notes[-1] + 6}", ""]
    return "\n".join(lines)


def brush_sfz(brush_dir: Path, rel_prefix: str, cfg: dict | None = None) -> str:
    """爵士刷子：key 24 = 可持續的掃刷（長 stir 樣本，不用原廠 one-shot 包絡），key 38 = 刷擊。

    原廠 Frankensnare 程式的 stir 是 loop_mode=one_shot＋ampeg_sustain=0，CC21 只加長衰減（量測 0→127
    約 0.4→1.5 秒），note 再長也會在 1.5 秒內消失，而且 stir 樣本本身比刷擊小 10–20 dB。
    這裡改成 no_loop＋sustain 100、依 note-off 釋放，另給 sweep_gain 補回音量。"""
    c = {"sweep_gain": 12, "sweep_attack": 0.16, "sweep_release": 0.3, "hit_gain": 0, "mic": "oh"}
    c.update(cfg or {})
    mic = c["mic"]
    lines = ["// 爵士刷子（掃刷可持續＋刷擊）；自動產生：tools/video/jazz_arrange.py sfz",
             "// 樣本 Karoryfer Frankensnare 14x5 maple brush（CC0）", "<control>", f"default_path={rel_prefix}", "",
             "<global>", "pitch_keytrack=0", ""]
    stirs = sorted(p.name for p in (brush_dir / mic).glob("stir_dl*_rr*.wav"))
    soft = [s for s in stirs if "dl3" in s] or stirs
    loud = [s for s in stirs if "dl4" in s] or stirs
    for (lv, hv), files in (((1, 80), soft), ((81, 127), loud)):
        if not files:
            continue
        lines.append(f"<group> lokey={KEY_SWEEP} hikey={KEY_SWEEP2} lovel={lv} hivel={hv} loop_mode=no_loop ampeg_attack={c['sweep_attack']} "
                     f"ampeg_sustain=100 ampeg_release={c['sweep_release']} volume={c['sweep_gain']} amp_veltrack=75 "
                     f"offset_random=120000 seq_length={len(files)}")
        for k, f in enumerate(files, 1):
            lines.append(f"<region> sample={mic}/{f} seq_position={k}")
    hits: dict[int, list[str]] = {}
    for p in sorted((brush_dir / mic).glob("sb_vl*_rr*.flac")):
        m = re.search(r"sb_vl(\d)_rr(\d)", p.name)
        if m:
            hits.setdefault(int(m.group(1)), []).append(p.name)
    layers = sorted(hits)
    for i, lv in enumerate(layers):
        lo = 1 + i * 127 // len(layers)
        hi = (i + 1) * 127 // len(layers)
        lines.append(f"<group> key={KEY_TAP} lovel={lo} hivel={hi} loop_mode=one_shot volume={c['hit_gain']} "
                     f"amp_veltrack=60 seq_length={len(hits[lv])}")
        for k, f in enumerate(hits[lv], 1):
            lines.append(f"<region> sample={mic}/{f} seq_position={k}")
    return "\n".join(lines) + "\n"


def write_sfz(sound_dir: Path = PROJ / "sound", trumpet_cfg: dict | None = None, brush_cfg: dict | None = None) -> list[Path]:
    lib = sound_dir.parent / "_assets" / "lib"
    out = []
    tdir = lib / "VSCO-2-CE" / "Brass" / "Trumpet"
    p = sound_dir / "sfz" / "trumpet_chet_combo.sfz"
    p.write_text(trumpet_combo_sfz(tdir, "../../_assets/lib/VSCO-2-CE/Brass/Trumpet/", trumpet_cfg), encoding="utf-8")
    out.append(p)
    bdir = lib / "frankensnare" / "Samples" / "14d_brush"
    p = sound_dir / "sfz" / "brush_jazz.sfz"
    p.write_text(brush_sfz(bdir, "../../_assets/lib/frankensnare/Samples/14d_brush/", brush_cfg), encoding="utf-8")
    out.append(p)
    return out


# ───────────────────────── CLI ─────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--params", type=Path)
    b.add_argument("--out", type=Path, default=PROJ / "arrangement")
    s = sub.add_parser("sfz")
    s.add_argument("--trumpet", type=Path, help="JSON：trumpet_combo_sfz 參數覆寫")
    s.add_argument("--brush", type=Path, help="JSON：brush_sfz 參數覆寫")
    e = sub.add_parser("events", help="輸出記譜用的乾淨（未人性化）事件 JSON")
    e.add_argument("--seed", type=int, default=7)
    e.add_argument("--params", type=Path)
    e.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("finalize")
    f.add_argument("--sections", type=Path, default=PROJ / "arrangement" / "sections.json")
    f.add_argument("--render", type=Path, required=True)
    f.add_argument("--trumpet-stem", type=Path)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
    if a.cmd == "build":
        params = json.loads(a.params.read_text(encoding="utf-8")) if a.params else None
        res = build(a.seed, params)
        meta = write_outputs(res, a.out)
        for sct in meta["sections"]:
            print(f"{sct['start_s']:7.1f}–{sct['end_s']:7.1f}s  bars {sct['bars'][0]:3d}–{sct['bars'][1]:3d}  {sct['label']}")
        print(f"total {meta['total_s']:.1f}s；notes: " + ", ".join(f"{k} {len(v)}" for k, v in res["parts"].items()))
    elif a.cmd == "sfz":
        tc = json.loads(a.trumpet.read_text(encoding="utf-8")) if a.trumpet else None
        bc = json.loads(a.brush.read_text(encoding="utf-8")) if a.brush else None
        for p in write_sfz(trumpet_cfg=tc, brush_cfg=bc):
            print(p)
    elif a.cmd == "events":
        params = json.loads(a.params.read_text(encoding="utf-8")) if a.params else None
        ev = clean_events(build(a.seed, params))
        a.out.write_text(json.dumps(ev, ensure_ascii=False, indent=0), encoding="utf-8")
        print(a.out, {k: len(v) for k, v in ev["parts"].items()})
    elif a.cmd == "finalize":
        meta = finalize(a.sections, a.render, a.trumpet_stem)
        print(json.dumps({k: meta[k] for k in ("total_s", "mix_lufs", "mix_true_peak_dbtp") if k in meta}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
