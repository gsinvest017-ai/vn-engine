"""Kalliwoda Romanze 爵士三重奏編曲 → 真人演奏家可讀的樂譜（MusicXML ＋ MuseScore PDF）。

來源：jazz_arrange.py 的「未人性化」事件（clean_events：lay-back、抖動、琶音滾奏之前的拍位置），
不是從人性化後的 MIDI 反推；只有前奏右手那幾個手寫微偏移的音（沒有 q_start）才量化。

用法（repo 根目錄）：
    python tools/video/jazz_score.py build   [--seed 7] [--out projects/kalliwoda-jazz/notation]
    python tools/video/jazz_score.py pdf     [--mscore <MuseScore4.exe>]      # MusicXML → PDF（＋每頁 PNG 給檢查）
    python tools/video/jazz_score.py verify  [--stems <iter6/stems>]          # basic-pitch 聽寫比對（WSL ~/.venv-listen）
    python tools/video/jazz_score.py readback                                 # music21 讀回（WSL ~/.venv-jazz）

build 輸出（--out）：
    full_score.musicxml                 總譜（小號移調記譜）
    parts/trumpet_bb.musicxml           Trumpet in B♭ 分譜（移調、和弦記號也移調）
    parts/piano.musicxml                鋼琴（大譜表，寫出 voicing）
    parts/piano_comp_slash.musicxml     鋼琴 "comp freely" 版（伴奏段改斜線＋和弦記號）
    parts/bass.musicxml                 Double Bass（高八度記譜，實音低八度）
    parts/drums.musicxml                Drum set（刷子）
    lead_sheet_C.musicxml / lead_sheet_Bb.musicxml   小號旋律＋和弦（C 調／B♭ 調）
    score_events.json                   記譜後的事件（實音、拍位置），給 verify／readback／測試

記譜規則（摘要）：
- 3/4、E♭ 大調（第二主題 c 小調同調號）、♩≈58 "Slow jazz waltz, swing 8ths (lazy, laid back)"。
- swing 八分音（拍內相位 0.63）記成直八分；swing 十六分音（0.315／0.815）記成 0.25／0.75；
  三連音、六連音（間奏原曲快速音群）照寫；其他未落在格上的點量化到半拍（樂句內）或 1/4 拍（經過音）。
- 每個聲部先做「垂直切片」（同時發聲的音合成和弦、延續的音用連結線），再在拍點切分、
  依拍內格線（二分／三連／六連）拼寫時值，最後把整拍合併成二分、附點二分、附點四分。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction as Fr
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PROJ = REPO / "projects" / "kalliwoda-jazz"
OUT = PROJ / "notation"
RENDER = PROJ / "_render" / "notation"
DIV = 24                    # MusicXML divisions / 四分音符（1/8 拍=3、六連音=4、三連音=8）
BAR = 3                     # 3/4
MEAS = BAR * DIV
MSCORE_CANDIDATES = [
    Path(r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe"),
    Path.home() / "tools" / "MuseScore4-portable" / "MuseScore 4" / "bin" / "MuseScore4.exe",
]

TITLE = "Romanze — after Kalliwoda Op.110"
SUBTITLE = "Slow jazz waltz ballad for trumpet, piano, bass & drums"
COMPOSER = "Johann Wenzel Kalliwoda (1801–1866)\nRomanze from Concertino Op.110"
ARRANGER = "arr. in the style of Chet Baker & Bill Evans"
RIGHTS = ("Transcription source: IMSLP, Alex'Not engraving (CC BY-SA 4.0) · Schott first edition, 1841 "
          "(public domain). This arrangement's notation is shared under CC BY-SA 4.0.")
TEMPO_TEXT = "Slow jazz waltz, swing 8ths (lazy, laid back)"

KEY_FIFTHS = -3             # E♭ 大調
EB_SCALE = {3, 5, 7, 8, 10, 0, 2}
LETTERS = "CDEFGAB"
NAT = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
KEY_SPELL = {0: ("C", 0), 1: ("D", -1), 2: ("D", 0), 3: ("E", -1), 4: ("E", 0), 5: ("F", 0), 6: ("G", -1),
             7: ("G", 0), 8: ("A", -1), 9: ("A", 0), 10: ("B", -1), 11: ("B", 0)}

# 段落 → 排練記號與名稱
SECTION_TEXT = {"intro": "Intro (piano)", "head_ab": "Head (a + b)", "head_a2": "Head (a′)",
                "piano_solo": "Piano solo", "interlude": "Interlude (C minor)",
                "theme2": "Theme II", "link": "Link", "return": "Return (head)",
                "coda": "Coda"}
DYN_LEVELS = ["pp", "p", "mp", "mf", "f"]
CHORD_CUTS = False          # True：在和弦變換點切開長音（改用連結線）；False：用 <harmony><offset>

# 鼓（MIDI 鍵 → 記譜位置、符頭、樂器）
KEY_SWEEP, KEY_SWEEP2, KEY_TAP, KEY_HAT, KEY_RIDE = 24, 25, 38, 44, 51
DRUM_INST = {  # id: (名稱, midi-unpitched 1 起算, display step, octave, notehead)
    "snare": ("Snare (brushes)", 39, "C", 5, "normal"),
    "sweep": ("Snare brush sweep", 25, "B", 4, "slash"),   # 編曲 MIDI 鍵 24
    "ride": ("Ride cymbal (brush)", 52, "F", 5, "x"),
    "hat": ("Hi-hat (foot)", 45, "C", 4, "x"),       # 下加一線
}


# ───────────────────────── 時間量化 ─────────────────────────

def snap(x: float, swing: float, fallback: Fr = Fr(1, 2), end: bool = False) -> Fr:
    """編曲拍位置 → 記譜格點。swing 相位記成直八分；1/8 與 1/6 的倍數照寫；其餘量化到 fallback。

    編曲資料裡的格點是精確值（0.63、0.315、1/8 倍數），三連音寫成 0.33／0.67；手寫的微偏移（0.12、0.64）
    與「起點＋任意時值」算出的終點（0.83）不能被當成格點，所以容差很小，終點（end=True）更嚴。"""
    b = math.floor(x + 1e-9)
    f = x - b
    tol8, tol6 = (0.0015, 0.0015) if end else (0.0015, 0.004)
    for tgt, val in ((swing, Fr(1, 2)), (swing / 2, Fr(1, 4)), (swing + (1 - swing) / 2, Fr(3, 4))):
        if abs(f - tgt) < 0.0015:
            return b + val
    for den, tol in ((8, tol8), (6, tol6)):
        k = round(f * den)
        if abs(f - k / den) < tol:
            return b + Fr(k, den)
    k = round(f / float(fallback))
    return b + k * fallback


def beat_grid(phases: set[Fr]) -> str:
    """一個拍內所有邊界點的相位 → 'bin'（1/8 格）、'trip'（1/3）、'sext'（1/6）。"""
    if all((p * 8).denominator == 1 for p in phases):
        return "bin"
    if all((p * 3).denominator == 1 for p in phases):
        return "trip"
    return "sext"


def harmonize_grid(notes: list) -> None:
    """同一聲部、同一拍內的邊界點若混了無法共存的格（例如 1/4 與 1/3），全部改量化到 1/6。"""
    pts: dict[int, list] = {}
    for n in notes:
        for attr in ("start", "end"):
            t = getattr(n, attr)
            pts.setdefault(math.floor(t), []).append((n, attr))
    for b, lst in pts.items():
        ph = {getattr(n, a) - b for n, a in lst}
        # 孤立的六連音點（第二主題骨幹化後殘留的 5/6、1/6 拍）→ 讀譜用的附點八分＋十六分（差 1/12 拍）
        lone = {Fr(5, 6): Fr(3, 4), Fr(1, 6): Fr(1, 4)}
        if len(ph - {Fr(0)}) == 1 and next(iter(ph - {Fr(0)})) in lone:
            f = next(iter(ph - {Fr(0)}))
            for n, a in lst:
                if getattr(n, a) - b == f:
                    setattr(n, a, b + lone[f])
            continue
        if beat_grid(ph) == "sext" and not all((p * 6).denominator == 1 for p in ph):
            for n, a in lst:
                t = getattr(n, a)
                setattr(n, a, b + Fr(round((t - b) * 6), 6))
    for n in notes:
        if n.end <= n.start:
            n.end = n.start + Fr(1, 6)


# ───────────────────────── 音高拼寫 ─────────────────────────

def pitch_of(step: str, alter: int, octave: int) -> int:
    return (octave + 1) * 12 + NAT[step] + alter


def spell_with(p: int, step: str) -> tuple[str, int, int]:
    """用指定音名拼 p（自動算升降與八度）。"""
    best = None
    for octv in range(-1, 10):
        a = p - pitch_of(step, 0, octv)
        if abs(a) <= 2 and (best is None or abs(a) < abs(best[1])):
            best = (step, a, octv)
    return best


def transpose_spelled(sp: tuple[str, int, int], p: int, dletter: int, dsemi: int) -> tuple[str, int, int]:
    """記好的音名往上移 dletter 個音名、dsemi 個半音（B♭ 小號：+1, +2）。"""
    li = LETTERS.index(sp[0]) + dletter
    return spell_with(p + dsemi, LETTERS[li % 7])


CHORD_RE = re.compile(r"^([A-G][b#]?)(.*?)(?:/([A-G][b#]?))?$")


def parse_chord(name: str) -> dict:
    m = CHORD_RE.match(name)
    if not m:
        raise ValueError(name)
    root, suf, bass = m.group(1), m.group(2), m.group(3)
    return {"name": name, "root": root, "suffix": suf, "bass": bass,
            "root_pc": (NAT[root[0]] + root.count("#") - root.count("b")) % 12}


def chord_letter_offset(iv: int, suffix: str) -> int:
    """和弦音相對根音的音名距離（依和弦性質決定 #9/b3、#11/b5、b13/#5、bb7）。"""
    minor = suffix.startswith("m") and not suffix.startswith("maj")
    if iv == 3:
        return 2 if (minor or "dim" in suffix or "b5" in suffix) else 1       # m3 或 #9
    if iv == 6:
        return 4 if ("dim" in suffix or "b5" in suffix) else 3                 # b5 或 #11
    if iv == 8:
        return 4 if "#5" in suffix else 5                                      # #5 或 b13
    if iv == 9 and "dim" in suffix:
        return 6                                                               # bb7
    return {0: 0, 1: 1, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 10: 6, 11: 6}[iv]


def spell(p: int, chord: dict | None, nxt: int | None = None) -> tuple[str, int, int]:
    """E♭ 大調下的實音拼寫：調內音用調號拼；調外的和弦音依和弦拼；其他半音依走向（上行用升、下行用降）。"""
    pc = p % 12
    root_in_key = chord is None or chord["root_pc"] in EB_SCALE
    if chord is not None and (pc not in EB_SCALE or not root_in_key):
        iv = (pc - chord["root_pc"]) % 12
        if pc not in EB_SCALE or iv in (0, 3, 4, 7, 10, 11, 1, 2, 5, 6, 8, 9):
            li = (LETTERS.index(chord["root"][0]) + chord_letter_offset(iv, chord["suffix"])) % 7
            sp = spell_with(p, LETTERS[li])
            if sp and abs(sp[1]) <= 1:
                return sp
    if pc in EB_SCALE:
        s, a = KEY_SPELL[pc]
        return spell_with(p, s)
    if nxt is not None and nxt - p == 1:                                        # 半音上行 → 升記號
        s = LETTERS[(LETTERS.index(KEY_SPELL[(pc + 1) % 12][0]) - 1) % 7]
        sp = spell_with(p, s)
        if abs(sp[1]) <= 1:
            return sp
    s, a = KEY_SPELL[pc]
    return spell_with(p, s)


# ───────────────────────── 記譜事件 ─────────────────────────

@dataclass
class NE:
    """一個記譜音（實音）。start/end 是整首的拍（Fraction）。"""
    start: Fr
    end: Fr
    pitch: int                        # 實音 MIDI；鼓 = MIDI 鍵
    vel: int = 64
    graces: list = field(default_factory=list)     # 前置倚音（實音 MIDI）
    marks: set = field(default_factory=set)        # tenuto breath slur_start slur_stop fermata arpeggio ghost
    dyn: str | None = None
    wedge: str | None = None          # "diminuendo"：從這個音到它結束
    words: list = field(default_factory=list)      # [(文字, placement)]
    inst: str | None = None           # 鼓的樂器 id
    src: int | None = None            # clean_events 裡的索引（驗證用）
    spelled: tuple | None = None      # 實音拼寫 (step, alter, octave)


def chord_timeline(leadsheet: dict) -> list[tuple[Fr, dict]]:
    out = []
    for b in leadsheet["bars"]:
        for c in b["chords"]:
            out.append((Fr((b["bar"] - 1) * BAR) + Fr(c["beat"]).limit_denominator(12) - 1, parse_chord(c["name"])))
    return sorted(out, key=lambda x: x[0])


def chord_at(tl: list[tuple[Fr, dict]], t: Fr) -> dict | None:
    cur = None
    for s, c in tl:
        if s <= t:
            cur = c
        else:
            break
    return cur


def _qs(n: dict) -> float:
    return n["start"] if n["q_start"] is None else n["q_start"]


def _qd(n: dict) -> float:
    return n["dur"] if n["q_dur"] is None else n["q_dur"]


def mono_line(ev: list[dict], swing: float, idx: list[int], end_beat: Fr, legato: bool = True,
              fallback_tags: tuple = ("passing", "inner")) -> list[NE]:
    """單音線條（小號、鋼琴右手線條、低音）：量化、裝飾音掛到下一個主音、連奏補齊小空隙。"""
    out: list[NE] = []
    pending: list[int] = []
    for i in idx:
        n = ev[i]
        if n["tag"] in ("grace", "slide"):
            pending.append(n["pitch"])
            continue
        fb = Fr(1, 4) if n["tag"] in fallback_tags else Fr(1, 2)
        s = snap(_qs(n), swing, fb)
        e = snap(_qs(n) + _qd(n), swing, fb, end=True)
        ne = NE(s, max(e, s + Fr(1, 8)), n["pitch"], n["vel"], graces=pending, src=i)
        pending = []
        if n["mark"] == "phrase_end":
            ne.marks.add("phrase_end")
        if out and out[-1].start == ne.start:          # 量化後撞在同一點：前一個變成倚音
            prev = out.pop()
            ne.graces = prev.graces + [prev.pitch] + ne.graces
        out.append(ne)
    for a, z in zip(out, out[1:]):
        a.end = min(a.end, z.start)
        gap = z.start - a.end
        if legato and 0 < gap < Fr(1, 2) and "phrase_end" not in a.marks:
            a.end = z.start
        if a.end <= a.start:
            a.end = z.start
    for n in out:
        n.end = min(n.end, end_beat)
    return [n for n in out if n.end > n.start]


def phrase_marks(line: list[NE], vel_ref: float, mute_words: dict[Fr, str] | None = None) -> None:
    """小號：每個樂句一條圓滑線、句尾換氣記號、長的句尾音漸弱；力度依樂句平均力度（相對全曲中位數）。"""
    phrases: list[list[NE]] = [[]]
    for n in line:
        phrases[-1].append(n)
        if "phrase_end" in n.marks:
            phrases.append([])
    last_dyn = None
    phrases = [p for p in phrases if p]
    for pi, ph in enumerate(phrases):
        if len(ph) >= 2:
            ph[0].marks.add("slur_start")
            ph[-1].marks.add("slur_stop")
        if pi < len(phrases) - 1:
            ph[-1].marks.add("breath")
        if ph[-1].end - ph[-1].start >= Fr(3, 2):
            ph[-1].wedge = "diminuendo"
        v = sorted(n.vel for n in ph)[len(ph) // 2]
        lvl = DYN_LEVELS[max(0, min(4, 2 + round((v - vel_ref) / 7)))]
        if lvl != last_dyn:
            ph[0].dyn = lvl
            last_dyn = lvl
        med = sorted(n.vel for n in ph)[len(ph) // 2]
        for n in ph[:-1]:
            if n.end - n.start >= 1 and n.vel >= med and n.start == int(n.start):
                n.marks.add("tenuto")


# ───────────────────────── 切片與時值拼寫 ─────────────────────────

@dataclass
class Seg:
    start: Fr
    end: Fr
    notes: list          # [(NE, attack: bool, continues: bool)]；空 = 休止
    slash: bool = False


def slice_voice(notes: list[NE], t0: Fr, t1: Fr, extra_cuts: set[Fr] | None = None) -> list[Seg]:
    cuts = {t0, t1} | (extra_cuts or set())
    for n in notes:
        if n.end > t0 and n.start < t1:
            cuts.add(max(t0, n.start))
            cuts.add(min(t1, n.end))
    cuts = sorted(c for c in cuts if t0 <= c <= t1)
    segs: list[Seg] = []
    for a, b in zip(cuts, cuts[1:]):
        snd = {}
        for n in notes:
            if n.start <= a < n.end:
                if n.pitch not in snd or n.start > snd[n.pitch].start:
                    snd[n.pitch] = n
        items = [(n, n.start == a, n.end > b) for n in sorted(snd.values(), key=lambda n: n.pitch)]
        if not items and segs and not segs[-1].notes:
            segs[-1].end = b
            continue
        segs.append(Seg(a, b, items))
    return segs


BIN_TYPES = {Fr(3): ("half", 1), Fr(2): ("half", 0), Fr(3, 2): ("quarter", 1), Fr(1): ("quarter", 0),
             Fr(3, 4): ("eighth", 1), Fr(1, 2): ("eighth", 0), Fr(3, 8): ("16th", 1), Fr(1, 4): ("16th", 0),
             Fr(1, 8): ("32nd", 0)}
TRIP_TYPES = {Fr(2, 3): ("quarter", 0), Fr(1, 3): ("eighth", 0)}
SEXT_TYPES = {Fr(1, 2): ("eighth", 1), Fr(1, 3): ("eighth", 0), Fr(1, 6): ("16th", 0)}


@dataclass
class El:
    """一個要寫出的 <note>（或和弦／休止），在小節內。"""
    start: Fr                 # 整首拍
    dur: Fr
    seg: Seg
    first: bool               # 此切片的第一個片段（掛起音屬性）
    last: bool                # 此切片的最後一個片段（掛結束屬性）
    tmod: tuple | None = None  # (actual, normal, normal-type)
    tuplet: str | None = None  # start/stop


def spell_durations(segs: list[Seg], m0: Fr) -> list[El]:
    """一個小節、一個聲部：切片 → 拍內片段 → 依格線拼時值 → 合併整拍。"""
    # 每拍的格線
    grids = {}
    for k in range(BAR):
        b0 = m0 + k
        ph = {s.start - b0 for s in segs if b0 <= s.start < b0 + 1} | \
             {s.end - b0 for s in segs if b0 < s.end < b0 + 1} | {Fr(0)}
        grids[k] = beat_grid(ph)
    els: list[El] = []
    for s in segs:
        pieces = []
        t = s.start
        while t < s.end:
            k = int(t - m0)
            nb = min(s.end, m0 + k + 1)
            pieces.append((t, nb, k))
            t = nb
        for pi, (a, b, k) in enumerate(pieces):
            g = grids[k]
            t = a
            while t < b:
                ph = t - (m0 + k)
                rem = b - t
                if rem == 1 and ph == 0:
                    v, tm = Fr(1), None
                elif g == "bin":
                    v = next(x for x in (Fr(1), Fr(3, 4), Fr(1, 2), Fr(3, 8), Fr(1, 4), Fr(1, 8)) if x <= rem)
                    tm = None
                elif g == "trip":
                    v = next(x for x in (Fr(2, 3), Fr(1, 3)) if x <= rem)
                    tm = (3, 2, "eighth")
                else:
                    v = next(x for x in (Fr(1, 2), Fr(1, 3), Fr(1, 6)) if x <= rem and (x != Fr(1, 2) or
                                                                                      ph in (0, Fr(1, 2))))
                    tm = (6, 4, "16th")
                els.append(El(t, v, s, first=(t == s.start), last=(t + v == s.end), tmod=tm))
                t += v
    # 合併整拍（同一切片的延續，或兩個休止）
    merged: list[El] = []
    for e in els:
        if merged:
            p = merged[-1]
            same = p.seg is e.seg
            ph_p = p.start - m0
            both_rest = not p.seg.notes and not e.seg.notes and not p.seg.slash and not e.seg.slash
            whole = p.tmod is None and e.tmod is None and (p.start - m0).denominator == 1 and \
                (e.start - m0).denominator == 1 and e.dur == 1 and p.dur in (1, 2)
            if whole and ((same and p.seg.notes and not p.seg.slash) or (both_rest and ph_p == 0 and p.dur == 1)):
                if p.dur + e.dur <= 3:
                    p.dur += e.dur
                    p.last = e.last
                    continue
            # 切分音：反拍八分音連到下一拍 → 反拍上的四分音符／附點四分音符（爵士譜慣例，少一條連結線）
            if same and p.seg.notes and not p.seg.slash and p.tmod is None and e.tmod is None \
                    and p.dur == Fr(1, 2) and (p.start - m0) % 1 == Fr(1, 2) and (e.start - m0).denominator == 1 \
                    and e.dur in (Fr(1, 2), Fr(1)):
                p.dur += e.dur
                p.last = e.last
                continue
            if same and p.seg.notes and not p.seg.slash and p.tmod is None and e.tmod is None and p.dur == 1 \
                    and (p.start - m0).denominator == 1 and e.dur == Fr(1, 2) and (e.start - m0).denominator == 1:
                p.dur = Fr(3, 2)
                p.last = e.last
                continue
        merged.append(e)
    # 連音括號
    for k in range(BAR):
        inb = [e for e in merged if e.tmod and int(e.start - m0) == k]
        if inb:
            inb[0].tuplet = "start"
            inb[-1].tuplet = "stop" if len(inb) > 1 else "start-stop"
    return merged


def dur_type(e: El) -> tuple[str, int]:
    if e.tmod is None:
        return BIN_TYPES[e.dur]
    if e.tmod[0] == 3:
        return TRIP_TYPES[e.dur]
    return SEXT_TYPES[e.dur]


# ───────────────────────── MusicXML 寫出 ─────────────────────────

def pitch_xml(sp: tuple[str, int, int], tag: str = "pitch") -> str:
    alt = f"<alter>{sp[1]}</alter>" if sp[1] else ""
    return f"<{tag}><step>{sp[0]}</step>{alt}<octave>{sp[2]}</octave></{tag}>"


@dataclass
class VoiceSpec:
    number: str
    staff: int
    notes: list                     # list[NE]
    stem: str | None = None         # 兩個聲部同時出現時 up/down
    slash_bars: set = field(default_factory=set)   # 這些小節寫成節奏斜線（comp freely／掃刷）


@dataclass
class PartSpec:
    pid: str
    name: str
    abbr: str
    staves: int
    clefs: list                     # [("G",2)] / [("G",2),("F",4)] / [("percussion",2)]
    voices: list                    # list[VoiceSpec]
    transpose: tuple | None = None  # (diatonic, chromatic, octave_change)；寫譜 = 實音 − 這個移調
    key_fifths: int = KEY_FIFTHS
    program: int = 1
    chords: list | None = None      # chord timeline（顯示在第 1 行譜上方）
    chord_transpose: tuple = (0, 0)
    drum: bool = False
    measure_words: dict = field(default_factory=dict)   # {bar: [(文字, placement, staff)]}
    measure_dyn: dict = field(default_factory=dict)     # {bar: [(dyn, staff)]}
    hide_rests_bars: dict = field(default_factory=dict)  # {staff: set(bars)} 休止不印（斜線版左手）
    dashes: list = field(default_factory=list)           # [(start_bar, end_bar, 文字)]
    system_text: bool = True        # 排練記號、段落名、速度（總譜只放在最上面一個聲部）


def _note_xml(e: El, n: NE | None, sp, voice: VoiceSpec, part: PartSpec, chord_flag: bool,
              tie_stop: bool, tie_start: bool, extra_notations: list[str], is_first_of_chord: bool,
              rest_hidden: bool = False, slash: bool = False) -> str:
    typ, dots = dur_type(e)
    x = ["<note" + (' print-object="no"' if rest_hidden else "") + ">"]
    if chord_flag:
        x.append("<chord/>")
    if n is None and not slash:
        x.append("<rest/>")
    elif slash and not part.drum:
        x.append(pitch_xml(("B", -1, 4)))      # 斜線放在第三線；用 B♭ 避免 E♭／F 調號下冒出還原記號
    elif part.drum:
        inst = DRUM_INST[n.inst if n is not None else "sweep"]
        x.append(f"<unpitched><display-step>{inst[2]}</display-step><display-octave>{inst[3]}</display-octave></unpitched>")
    else:
        x.append(pitch_xml(sp))
    x.append(f"<duration>{int(e.dur * DIV)}</duration>")
    if tie_stop:
        x.append('<tie type="stop"/>')
    if tie_start:
        x.append('<tie type="start"/>')
    if part.drum and (n is not None or slash):
        iid = n.inst if n is not None else "sweep"
        x.append(f'<instrument id="{part.pid}-{iid}"/>')
    x.append(f"<voice>{voice.number}</voice><type>{typ}</type>" + "<dot/>" * dots)
    if e.tmod:
        x.append(f"<time-modification><actual-notes>{e.tmod[0]}</actual-notes><normal-notes>{e.tmod[1]}"
                 f"</normal-notes><normal-type>{e.tmod[2]}</normal-type></time-modification>")
    if n is not None or slash:
        if slash:
            x.append("<stem>none</stem>")
        elif voice.stem:
            x.append(f"<stem>{voice.stem}</stem>")
        if slash:
            x.append("<notehead>slash</notehead>")
        elif part.drum:
            head = DRUM_INST[n.inst][4]
            par = ' parentheses="yes"' if "ghost" in n.marks else ""
            if head != "normal" or par:
                x.append(f"<notehead{par}>{head}</notehead>")
    x.append(f"<staff>{voice.staff}</staff>")
    nots = []
    if tie_stop:
        nots.append('<tied type="stop"/>')
    if tie_start:
        nots.append('<tied type="start"/>')
    if is_first_of_chord and e.tuplet:
        for t in (["start", "stop"] if e.tuplet == "start-stop" else [e.tuplet]):
            nots.append(f'<tuplet type="{t}"/>')
    nots += extra_notations
    if nots:
        x.append("<notations>" + "".join(nots) + "</notations>")
    x.append("</note>")
    return "".join(x)


def _direction(inner: str, placement: str = "above", staff: int = 1, sound: str = "", offset: int = 0) -> str:
    off = f"<offset>{offset}</offset>" if offset else ""
    return (f'<direction placement="{placement}">{inner}{off}<staff>{staff}</staff>{sound}</direction>')


def _words(text: str, bold: bool = False, italic: bool = False, size: float | None = None) -> str:
    attrs = (' font-weight="bold"' if bold else "") + (' font-style="italic"' if italic else "") + \
            (f' font-size="{size}"' if size else "")
    return f"<direction-type><words{attrs}>{escape(text)}</words></direction-type>"


KIND = [  # (suffix, kind)：MuseScore 會用 kind＋degree 自己重組名稱（9sus4 會變成 sus4b7add9、6/9 疊字），
    # 所以那幾種用 kind="other" ＋ text，讓它照字面顯示；其餘用語意 kind。
    ("maj9", "major-ninth"), ("13", "dominant-13th"), ("m9", "minor-ninth"), ("m7b5", "half-diminished"),
    ("dim7", "diminished-seventh"), ("maj7(#11)", "other"), ("6/9", "other"), ("m6/9", "other"),
    ("7(b9,b13)", "other"), ("9sus4", "other"), ("7(#5)", "other"),
]


def harmony_xml(c: dict, staff: int, offset: int, trans: tuple[int, int]) -> str:
    def rootx(name: str, tag: str) -> str:
        sp = (name[0], name.count("#") - name.count("b"), 4)
        if trans != (0, 0):
            p = pitch_of(*sp)
            sp = transpose_spelled(sp, p, trans[0], trans[1])
        alt = f"<{tag}-alter>{sp[1]}</{tag}-alter>" if sp[1] else ""
        return f"<{tag}><{tag}-step>{sp[0]}</{tag}-step>{alt}</{tag}>"
    kind = next((k for s, k in KIND if s == c["suffix"]), "other" if c["suffix"] else "major")
    degs = []
    x = ["<harmony print-frame=\"no\">", rootx(c["root"], "root"),
         f'<kind text="{escape(c["suffix"])}">{kind}</kind>']
    if c["bass"]:
        x.append(rootx(c["bass"], "bass"))
    for v, a, t in degs:
        x.append(f"<degree><degree-value>{v}</degree-value><degree-alter>{a}</degree-alter>"
                 f"<degree-type>{t}</degree-type></degree>")
    if offset:
        x.append(f"<offset>{offset}</offset>")
    x.append(f"<staff>{staff}</staff></harmony>")
    return "".join(x)


def write_part_measures(part: PartSpec, n_bars: int, sections: list[dict], tempo_marks: dict,
                        breaks: set[int], first_attrs_extra: str = "") -> list[str]:
    """回傳每小節的 <measure> XML 字串。"""
    measures = []
    sec_start = {s["bars"][0]: s for s in sections}
    sec_end = {s["bars"][1] for s in sections}
    letters = {s["bars"][0]: chr(ord("A") + i) for i, s in enumerate(sections)}
    for m in range(1, n_bars + 1):
        m0 = Fr((m - 1) * BAR)
        m1 = m0 + BAR
        x = [f'<measure number="{m}">']
        if m in breaks and m > 1:
            x.append('<print new-system="yes"/>')
        if m == 1:
            clefs = "".join(
                (f'<clef number="{i + 1}"><sign>{c[0]}</sign>' + (f"<line>{c[1]}</line>" if c[0] != "percussion" else "")
                 + "</clef>") for i, c in enumerate(part.clefs))
            tr = ""
            if part.transpose:
                d, c_, o = part.transpose
                tr = f"<transpose><diatonic>{d}</diatonic><chromatic>{c_}</chromatic>" + \
                     (f"<octave-change>{o}</octave-change>" if o else "") + "</transpose>"
            stav = f"<staves>{part.staves}</staves>" if part.staves > 1 else ""
            sd = "<staff-details><staff-lines>5</staff-lines></staff-details>" if part.drum else ""
            x.append(f"<attributes><divisions>{DIV}</divisions><key><fifths>{0 if part.drum else part.key_fifths}"
                     f"</fifths><mode>major</mode></key><time><beats>3</beats><beat-type>4</beat-type></time>"
                     f"{stav}{clefs}{sd}{tr}</attributes>")
        # 排練記號、段落名
        if m in sec_start and part.system_text:
            s = sec_start[m]
            cue = "".join(f" — {t}" for t, plc, _ in part.measure_words.get(m, []) if plc == "section")
            x.append(_direction(f"<direction-type><rehearsal enclosure=\"square\">{letters[m]}</rehearsal>"
                                f"</direction-type>" + _words("  " + SECTION_TEXT.get(s["name"], s["name"]), bold=True)
                                + (_words(cue, italic=True) if cue else "")))
        for inner, snd in (tempo_marks.get(m, []) if part.system_text else []):
            x.append(_direction(inner, sound=snd))
        for text, plc, st in [w for w in part.measure_words.get(m, []) if w[1] != "section"]:
            # 段落開頭的上方已有排練記號＋段落名＋和弦記號，演奏法文字放上方會被擠到前一行；m>1 一律放下方
            x.append(_direction(_words(text, italic=True), plc if m == 1 else "below", st))
        for dyn, st in part.measure_dyn.get(m, []):
            x.append(_direction(f"<direction-type><dynamics><{dyn}/></dynamics></direction-type>", "below", st))
        for (a, b, text) in part.dashes:
            if m == a:
                x.append(_direction(_words(text, italic=True) + '<direction-type><dashes type="start" number="2"/>'
                                    '</direction-type>', "above", 1))
        # 和弦記號
        harm = []
        if part.chords:
            harm = [(t, c) for t, c in part.chords if m0 <= t < m1]
        body = []

        def active(v):
            return (m in v.slash_bars) or any(n.end > m0 and n.start < m1 for n in v.notes)
        written = []
        for voice in part.voices:
            same_staff = [v for v in part.voices if v.staff == voice.staff]
            act = [v for v in same_staff if active(v)]
            if active(voice) or (not act and voice is same_staff[0]):
                written.append(voice)
        anchor = next((v for v in written if v.staff == 1), None)
        for voice in written:
            vnotes = [n for n in voice.notes if n.end > m0 and n.start < m1]
            slash = m in voice.slash_bars
            same_staff = [v for v in written if v.staff == voice.staff]
            others_active = len(same_staff) > 1
            number = voice.number if others_active else [v for v in part.voices if v.staff == voice.staff][0].number
            if not vnotes and not slash:
                hidden = m in part.hide_rests_bars.get(voice.staff, set())
                h = "".join(harmony_xml(c, voice.staff, int((t - m0) * DIV), part.chord_transpose)
                            for t, c in harm) if (harm and voice is anchor) else ""
                if h:
                    harm = []
                extra = _fermata_rest(m == n_bars)
                po = ' print-object="no"' if hidden else ""
                body.append(h + f'<note{po}><rest measure="yes"/>'
                            f"<duration>{MEAS}</duration><voice>{number}</voice><staff>{voice.staff}</staff>"
                            f"{extra}</note>")
                body.append(f"<backup><duration>{MEAS}</duration></backup>")
                continue
            vs = VoiceSpec(number, voice.staff, voice.notes, voice.stem if others_active else None,
                           voice.slash_bars)
            if slash:
                segs = [Seg(m0 + k, m0 + k + 1, [], slash=True) for k in range(BAR)]
            else:
                cuts = {t for t, _ in harm} if (CHORD_CUTS and harm and voice is anchor) else set()
                segs = slice_voice(vnotes, m0, m1, cuts)
            els = spell_durations(segs, m0)
            out = []
            for e in els:
                # 和弦記號：寫在涵蓋它的第一個元素前
                if harm and voice is anchor:
                    while harm and harm[0][0] < e.start + e.dur:
                        t, c = harm.pop(0)
                        out.append(harmony_xml(c, voice.staff, int((t - e.start) * DIV), part.chord_transpose))
                if e.seg.slash:
                    fer = ['<fermata type="upright"/>'] if (m == n_bars and e.start + e.dur == m1) else []
                    out.append(_note_xml(e, None, None, vs, part, False, False, False, fer, True, slash=True))
                    continue
                if not e.seg.notes:
                    fer = ['<fermata type="upright"/>'] if (m == n_bars and e.start + e.dur == m1) else []
                    hide = m in part.hide_rests_bars.get(voice.staff, set()) or                         (part.drum and others_active and voice is not same_staff[0])
                    out.append(_note_xml(e, None, None, vs, part, False, False, False, fer, True, rest_hidden=hide))
                    continue
                # 附在起音上的東西：力度、文字、倚音
                if e.first:
                    for n, attack, _ in e.seg.notes:
                        if not attack:
                            continue
                        if n.dyn:
                            out.append(_direction(f"<direction-type><dynamics><{n.dyn}/></dynamics></direction-type>",
                                                  "below", voice.staff))
                        if n.wedge:
                            out.append(_direction(f'<direction-type><wedge type="{n.wedge}" number="1"/></direction-type>',
                                                  "below", voice.staff))
                        for text, plc in n.words:
                            out.append(_direction(_words(text, italic=True), plc, voice.staff))
                    gr = [g for n, attack, _ in e.seg.notes if attack for g in n.graces]
                    top = max((n for n, a, _ in e.seg.notes if a), key=lambda n: n.pitch, default=None)
                    for g in gr:
                        gsp = _written(spell(g, chord_at(part.chords or [], e.start), top.pitch if top else None), g, part)
                        out.append(f'<note><grace slash="yes"/>{pitch_xml(gsp)}<voice>{vs.number}</voice>'
                                   f"<type>eighth</type><stem>up</stem><staff>{vs.staff}</staff></note>")
                for ci, (n, attack, cont) in enumerate(e.seg.notes):
                    tie_stop = not (e.first and attack)
                    tie_start = not (e.last and not cont)
                    extra = []
                    arts = []
                    if e.first and attack and "tenuto" in n.marks:
                        arts.append("<tenuto/>")
                    if e.last and not cont and "breath" in n.marks:
                        arts.append("<breath-mark/>")
                    if arts and ci == 0:
                        extra.append("<articulations>" + "".join(arts) + "</articulations>")
                    if e.first and attack and "slur_start" in n.marks and ci == len(e.seg.notes) - 1:
                        extra.append('<slur type="start" number="1"/>')
                    if e.first and attack and "slur_stop" in n.marks and ci == len(e.seg.notes) - 1:
                        extra.append('<slur type="stop" number="1"/>')
                    if e.first and attack and "arpeggio" in n.marks:
                        extra.append("<arpeggiate/>")
                    if m == n_bars and e.start + e.dur == m1 and ci == 0:
                        extra.append('<fermata type="upright"/>')
                    sp = None if part.drum else _written(n.spelled, n.pitch, part)
                    out.append(_note_xml(e, n, sp, vs, part, ci > 0, tie_stop, tie_start, extra, ci == 0))
                # 漸弱結束
                if e.last:
                    for n, _, cont in e.seg.notes:
                        if not cont and n.wedge:
                            out.append(_direction('<direction-type><wedge type="stop" number="1"/></direction-type>',
                                                  "below", voice.staff))
                            break
            body.append("".join(out))
            body.append(f"<backup><duration>{MEAS}</duration></backup>")
        if body and body[-1].startswith("<backup>"):
            body.pop()
        x.extend(body)
        for (a, b, text) in part.dashes:
            if m == b:
                x.append(_direction('<direction-type><dashes type="stop" number="2"/></direction-type>', "above", 1))
        if m == n_bars:
            x.append('<barline location="right"><bar-style>light-heavy</bar-style></barline>')
        elif m in sec_end:
            x.append('<barline location="right"><bar-style>light-light</bar-style></barline>')
        x.append("</measure>")
        measures.append("".join(x))
    return measures


def _fermata_rest(last: bool) -> str:
    return '<notations><fermata type="upright"/></notations>' if last else ""


def _written(sp: tuple, p: int, part: PartSpec) -> tuple:
    if not part.transpose:
        return sp
    d, c, o = part.transpose
    # 寫譜 = 實音 − 移調（transpose 是「寫譜 → 實音」）
    return transpose_spelled(sp, p, -d - 7 * o, -c - 12 * o)


def score_xml(parts: list[PartSpec], n_bars: int, sections: list[dict], tempo_marks: dict, breaks: set[int],
              subtitle: str = SUBTITLE) -> str:
    x = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
         '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
         '"http://www.musicxml.org/dtds/partwise.dtd">',
         '<score-partwise version="4.0">',
         f"<work><work-title>{escape(TITLE)}</work-title></work>",
         "<identification>",
         f'<creator type="composer">{escape(COMPOSER)}</creator>',
         f'<creator type="arranger">{escape(ARRANGER)}</creator>',
         f"<rights>{escape(RIGHTS)}</rights>",
         "<encoding><software>vn-engine-jazz tools/video/jazz_score.py</software></encoding>",
         "</identification>",
         "<defaults><scaling><millimeters>7.0</millimeters><tenths>40</tenths></scaling>"
         "<page-layout><page-height>1697</page-height><page-width>1200</page-width>"
         '<page-margins type="both"><left-margin>80</left-margin><right-margin>80</right-margin>'
         "<top-margin>80</top-margin><bottom-margin>80</bottom-margin></page-margins></page-layout></defaults>",
         f'<credit page="1"><credit-type>title</credit-type><credit-words default-x="600" default-y="1610" '
         f'justify="center" valign="top" font-size="22">{escape(TITLE)}</credit-words></credit>',
         f'<credit page="1"><credit-type>subtitle</credit-type><credit-words default-x="600" default-y="1560" '
         f'justify="center" valign="top" font-size="12">{escape(subtitle)}</credit-words></credit>',
         # MuseScore 會把 composer 與 arranger 放在同一個位置互相重疊，所以合成一個右上角文字框
         f'<credit page="1"><credit-type>composer</credit-type><credit-words default-x="1120" default-y="1520" '
         f'justify="right" valign="top" font-size="10">{escape(COMPOSER + chr(10) + ARRANGER)}</credit-words></credit>',
         f'<credit page="1"><credit-type>rights</credit-type><credit-words default-x="600" default-y="60" '
         f'justify="center" valign="bottom" font-size="7">{escape(RIGHTS)}</credit-words></credit>',
         "<part-list>"]
    for p in parts:
        x.append(f'<score-part id="{p.pid}"><part-name>{escape(p.name)}</part-name>'
                 f"<part-abbreviation>{escape(p.abbr)}</part-abbreviation>")
        if p.drum:
            for iid, (nm, _, _, _, _) in DRUM_INST.items():
                x.append(f'<score-instrument id="{p.pid}-{iid}"><instrument-name>{escape(nm)}</instrument-name>'
                         f"</score-instrument>")
            for iid, (nm, un, _, _, _) in DRUM_INST.items():
                x.append(f'<midi-instrument id="{p.pid}-{iid}"><midi-channel>10</midi-channel>'
                         f"<midi-unpitched>{un}</midi-unpitched></midi-instrument>")
        else:
            x.append(f'<score-instrument id="{p.pid}-I1"><instrument-name>{escape(p.name)}</instrument-name>'
                     f'</score-instrument><midi-instrument id="{p.pid}-I1"><midi-program>{p.program}</midi-program>'
                     f"</midi-instrument>")
        x.append("</score-part>")
    x.append("</part-list>")
    for p in parts:
        x.append(f'<part id="{p.pid}">')
        x.extend(write_part_measures(p, n_bars, sections, tempo_marks, breaks))
        x.append("</part>")
    x.append("</score-partwise>")
    return "\n".join(x)


# ───────────────────────── 從編曲建立各聲部 ─────────────────────────

def load_inputs(seed: int = 7) -> dict:
    sys.path.insert(0, str(HERE))
    import jazz_arrange as ja
    res = ja.build(seed)
    ev = ja.clean_events(res)
    arr = PROJ / "arrangement"
    leadsheet = json.loads((arr / "leadsheet.json").read_text(encoding="utf-8"))
    sections = json.loads((arr / "sections.json").read_text(encoding="utf-8"))["sections"]
    # 樂譜要對應實際渲染的那份 MIDI
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "rebuild.mid"
        res["builder"].save(tmp)
        same = tmp.read_bytes() == (arr / "kalliwoda_ballad.mid").read_bytes()
    return {"events": ev, "leadsheet": leadsheet, "sections": sections, "midi_matches_arrangement": same}


def build_notation(inp: dict) -> dict:
    ev = inp["events"]
    sw = ev["swing"]
    P = ev["parts"]
    n_bars = len(ev["bars"])
    end_beat = Fr(n_bars * BAR)
    tl = chord_timeline(inp["leadsheet"])
    sections = inp["sections"]
    sec_of_bar = {b: s for s in sections for b in range(s["bars"][0], s["bars"][1] + 1)}

    # 小號
    tr_idx = [i for i, n in enumerate(P["trumpet"]) if _qs(n) < float(end_beat)]
    trumpet = mono_line(P["trumpet"], sw, tr_idx, end_beat)
    vel_ref = sorted(n.vel for n in trumpet)[len(trumpet) // 2]
    phrase_marks(trumpet, vel_ref)
    for a, z in zip(trumpet, trumpet[1:] + [None]):
        a.spelled = spell(a.pitch, chord_at(tl, a.start), z.pitch if z else None)

    # 低音
    bass = mono_line(P["bass"], sw, list(range(len(P["bass"]))), end_beat, legato=False)
    for a, z in zip(bass, bass[1:] + [None]):
        a.spelled = spell(a.pitch, chord_at(tl, a.start), z.pitch if z else None)

    # 鋼琴：線條（單音）與和弦（voicing）
    pn = P["piano"]
    groups: dict = {}
    for i, n in enumerate(pn):
        if n["q_start"] is not None and n["tag"] != "inner":
            groups.setdefault((round(n["q_start"], 5), round(n["q_dur"], 5)), []).append(i)
    line_idx, chord_idx = [], []
    for i, n in enumerate(pn):
        if n["q_start"] is None:
            line_idx.append(i)
        elif n["tag"] == "inner" or n["mark"] == "inner_src" or                 len(groups[(round(n["q_start"], 5), round(n["q_dur"], 5))]) >= 2:
            chord_idx.append(i)
        else:
            line_idx.append(i)
    rh_line = mono_line(pn, sw, sorted(line_idx, key=lambda i: _qs(pn[i])), end_beat)
    chords: list[NE] = []
    for i in chord_idx:
        n = pn[i]
        s = snap(_qs(n), sw, Fr(1, 2))
        e = min(end_beat, snap(_qs(n) + _qd(n), sw, Fr(1, 2), end=True))
        ne = NE(s, max(e, s + Fr(1, 4)), n["pitch"], n["vel"], src=i)
        if n["mark"] == "arpeggio_fermata":
            ne.marks.add("arpeggio")
        chords.append(ne)
    # 和弦音不要拖進下一個 voicing（內聲部移動除外）
    starts = sorted({c.start for c in chords if pn[c.src]["tag"] != "inner"})
    for c in chords:
        nxt = next((t for t in starts if t > c.start), None)
        if nxt is not None and c.end > nxt and pn[c.src]["tag"] != "inner":
            c.end = nxt
    # inner move：被取代的那個音（相差 ≤ 2 半音、在移動點附近結束）剛好在移動點結束，避免切出碎片
    for inn in [c for c in chords if pn[c.src]["tag"] == "inner"]:
        for c in chords:
            if c is not inn and c.start < inn.start < c.end <= inn.start + 1 and abs(c.pitch - inn.pitch) <= 2:
                c.end = inn.start
    for c in chords:
        c.spelled = spell(c.pitch, chord_at(tl, c.start))
    for a, z in zip(rh_line, rh_line[1:] + [None]):
        a.spelled = spell(a.pitch, chord_at(tl, a.start), z.pitch if z else None)
    # 右手線條：兩小節一句的圓滑線（獨奏）／每段補圓滑線
    _piano_slurs(rh_line)
    rh_top = [c for c in chords if c.pitch >= 60]
    lh = [c for c in chords if c.pitch < 60] + [n for n in rh_line if n.pitch < 55]
    rh_line = [n for n in rh_line if n.pitch >= 55]
    for voice in (trumpet, bass, rh_line, rh_top, lh):
        harmonize_grid(voice)

    # 鼓
    brush, hat = P["brush"], P["hihat"]
    taps, sweeps_bars, ride_notes = [], {}, []
    for i, n in enumerate(brush):
        b = int(n["q_start"] // BAR) + 1
        if n["pitch"] in (KEY_SWEEP, KEY_SWEEP2):
            sweeps_bars.setdefault(min(b, n_bars), 0)
            continue
        taps.append(NE(snap(n["q_start"], sw), 0, n["pitch"], n["vel"], inst="snare", src=i,
                       marks={"ghost"} if n["mark"] == "ghost" else set()))
    feet = []
    for i, n in enumerate(hat):
        s = snap(n["q_start"], sw)
        if n["pitch"] == KEY_RIDE:
            ride_notes.append(NE(s, 0, n["pitch"], n["vel"], inst="ride", src=i))
        else:
            feet.append(NE(s, s + 1, n["pitch"], n["vel"], inst="hat", src=i))
    hands = sorted(taps + ride_notes, key=lambda n: (n.start, n.pitch))
    onsets = sorted({n.start for n in hands})
    for n in hands:     # 打擊：時值到同聲部下一個起音（最多一拍、不過小節線）
        nxt = next((t for t in onsets if t > n.start), n.start + 1)
        bar_end = Fr((int(n.start // BAR) + 1) * BAR)
        n.end = min(nxt, n.start + 1, bar_end)
    for n in feet:
        n.end = min(n.end, Fr((int(n.start // BAR) + 1) * BAR))
    hand_bars = {int(n.start // BAR) + 1 for n in hands}
    sweep_only = {b for b in sweeps_bars if b not in hand_bars}

    return {"trumpet": trumpet, "bass": bass, "rh_line": rh_line, "rh_top": rh_top, "lh": lh,
            "drum_hands": hands, "drum_feet": feet, "sweep_only": sweep_only, "chords": tl,
            "sections": sections, "sec_of_bar": sec_of_bar, "n_bars": n_bars, "swing": sw,
            "piano_raw": pn, "events": ev}


def _piano_slurs(line: list[NE]) -> None:
    """鋼琴右手線條：相鄰音距 < 1 拍視為同一句，句子加圓滑線。"""
    if not line:
        return
    ph = [[line[0]]]
    for a, z in zip(line, line[1:]):
        if z.start - a.end >= 1 or z.start - a.start >= 4:
            ph.append([z])
        else:
            ph[-1].append(z)
    for p in ph:
        if len(p) >= 2:
            p[0].marks.add("slur_start")
            p[-1].marks.add("slur_stop")


def tempo_marks(n_bars: int) -> dict:
    metro = ('<direction-type><metronome parentheses="no"><beat-unit>quarter</beat-unit>'
             '<per-minute>58</per-minute></metronome></direction-type>')
    return {
        1: [(_words(TEMPO_TEXT, bold=True) + metro, '<sound tempo="58"/>')],
        88: [(_words("rit.", italic=True) + '<direction-type><dashes type="start" number="3"/></direction-type>',
              '<sound tempo="55"/>')],
        91: [('<direction-type><dashes type="stop" number="3"/></direction-type>' + _words("Più lento", bold=True) +
              '<direction-type><metronome parentheses="yes"><beat-unit>quarter</beat-unit><per-minute>47'
              '</per-minute></metronome></direction-type>', '<sound tempo="47"/>')],
        92: [(_words("poco a poco rit.", italic=True), '<sound tempo="46"/>')],
        n_bars: [(_words("molto rit.", italic=True), '<sound tempo="40"/>')],
    }


def section_dyn(notes: list[NE], sections: list[dict], ref: float, staff: int = 1,
                skip: set[str] = frozenset()) -> dict:
    """每段第一個音前放一個力度（依該段中位數力度相對全聲部中位數，每 7 個 velocity 一級）。"""
    out = {}
    last = None
    for s in sections:
        if s["name"] in skip:
            continue
        a, b = (s["bars"][0] - 1) * BAR, s["bars"][1] * BAR
        vs = sorted(n.vel for n in notes if a <= n.start < b)
        if not vs:
            continue
        lvl = DYN_LEVELS[max(0, min(4, 2 + round((vs[len(vs) // 2] - ref) / 7)))]
        if lvl != last:
            first = min((n for n in notes if a <= n.start < b), key=lambda n: n.start)
            out.setdefault(int(first.start // BAR) + 1, []).append((lvl, staff))
            last = lvl
    return out


def make_parts(nt: dict) -> dict[str, PartSpec]:
    n_bars = nt["n_bars"]
    secs = nt["sections"]
    tl = nt["chords"]
    first_bar = {s["name"]: s["bars"][0] for s in secs}

    tp = PartSpec("P1", "Trumpet in B♭", "Tpt.", 1, [("G", 2)], [VoiceSpec("1", 1, nt["trumpet"])],
                  transpose=(-1, -2, 0), key_fifths=KEY_FIFTHS + 2, program=57)
    tp.measure_words = {first_bar["head_ab"]: [("open", "section", 1)],
                        first_bar["theme2"]: [("harmon mute (stem in)", "section", 1)],
                        first_bar["return"]: [("open", "section", 1)]}

    lh = nt["lh"]
    rh_top, rh_line = nt["rh_top"], nt["rh_line"]
    pno = PartSpec("P2", "Piano", "Pno.", 2, [("G", 2), ("F", 4)],
                   [VoiceSpec("1", 1, rh_line, "up"), VoiceSpec("2", 1, rh_top, "down"), VoiceSpec("5", 2, lh)],
                   program=1, chords=tl)
    pno.measure_words = {1: [("legato, with pedal (change with each chord)", "below", 1)],
                         first_bar["piano_solo"]: [("R.H. solo (as written or ad lib.)", "above", 1)]}
    allp = rh_line + rh_top + lh
    ref = sorted(n.vel for n in allp)[len(allp) // 2]
    pno.measure_dyn = section_dyn(allp, secs, ref, 1)

    bs = PartSpec("P3", "Double Bass", "D.B.", 1, [("F", 4)], [VoiceSpec("1", 1, nt["bass"])],
                  transpose=(0, 0, -1), program=33, chords=tl)
    bfirst = min(n.start for n in nt["bass"])
    bs.measure_words = {int(bfirst // BAR) + 1: [("pizz.", "above", 1)],
                        first_bar["piano_solo"]: [("walk (in 3)", "above", 1)],
                        first_bar["interlude"]: [("in 1 / 2-feel", "above", 1)]}
    bref = sorted(n.vel for n in nt["bass"])[len(nt["bass"]) // 2]
    bs.measure_dyn = section_dyn(nt["bass"], secs, bref, 1)

    dr = PartSpec("P4", "Drum Set", "Dr.", 1, [("percussion", 2)],
                  [VoiceSpec("1", 1, nt["drum_hands"], "up", slash_bars=nt["sweep_only"]),
                   VoiceSpec("2", 1, nt["drum_feet"], "down")], drum=True, program=1)
    dr.measure_words = {1: [("Brushes — L.H. sweeps in circles, one per beat ⟳ (slashes = sweep only)", "above", 1)],
                        first_bar["head_ab"]: [("R.H. taps 2 & 3, L.H. sweep, H.H. foot", "above", 1)],
                        first_bar["piano_solo"]: [("R.H. ride, L.H. sweep", "above", 1)],
                        first_bar["interlude"]: [("snare, lighter", "above", 1)],
                        n_bars: [("circle, dim. al niente", "above", 1)]}
    dr.measure_dyn = {1: [("pp", 1)], first_bar["head_ab"]: [("p", 1)]}
    for b in sorted(nt["sweep_only"]):
        if b > first_bar["coda"] and b - 1 not in nt["sweep_only"]:
            dr.measure_dyn.setdefault(b, []).append(("pp", 1))
    # 刷子掃圈的長線：每段有輕拍的小節
    for s in secs:
        bars = [b for b in range(s["bars"][0], s["bars"][1] + 1) if b not in nt["sweep_only"]]
        if bars:
            dr.dashes.append((bars[0], bars[-1], "sweep ⟳"))
    return {"trumpet": tp, "piano": pno, "bass": bs, "drums": dr}


def piano_slash_variant(pno: PartSpec, nt: dict) -> PartSpec:
    """伴奏段改成斜線 "comp freely"（前奏、獨奏、間奏、尾聲最後幾小節仍照寫）。"""
    comp_secs = {"head_ab", "head_a2", "theme2", "link", "return"}
    bars = set()
    for s in nt["sections"]:
        if s["name"] in comp_secs:
            bars |= set(range(s["bars"][0], s["bars"][1] + 1))
        if s["name"] == "coda":
            bars |= set(range(s["bars"][0], s["bars"][0] + 7))
    lo = lambda ns: [n for n in ns if int(n.start // BAR) + 1 not in bars]  # noqa: E731
    v1 = VoiceSpec("1", 1, lo(pno.voices[0].notes), "up", slash_bars=bars)
    v2 = VoiceSpec("2", 1, lo(pno.voices[1].notes), "down")
    v3 = VoiceSpec("5", 2, lo(pno.voices[2].notes))
    p = PartSpec("P2", "Piano (comp freely)", "Pno.", 2, [("G", 2), ("F", 4)], [v1, v2, v3], chords=pno.chords)
    p.measure_words = dict(pno.measure_words)
    first = {s["name"]: s["bars"][0] for s in nt["sections"]}
    for nm in ("head_ab", "theme2", "return"):
        p.measure_words.setdefault(first[nm], []).append(
            ("comp freely — rootless voicings, fill the trumpet's gaps", "above", 1))
    p.measure_dyn = pno.measure_dyn
    p.hide_rests_bars = {2: bars}
    return p


def lead_sheet(nt: dict, bb: bool) -> PartSpec:
    first = {s["name"]: s["bars"][0] for s in nt["sections"]}
    tr_bars = {int(n.start // BAR) + 1 for n in nt["trumpet"]} | {int((n.end - Fr(1, 100)) // BAR) + 1 for n in nt["trumpet"]}
    slash = set(range(1, nt["n_bars"] + 1)) - tr_bars
    v = VoiceSpec("1", 1, nt["trumpet"], slash_bars=slash)
    p = PartSpec("P1", "Trumpet in B♭" if bb else "Melody (C)", "Tpt." if bb else "Mel.", 1, [("G", 2)], [v],
                 transpose=(-1, -2, 0) if bb else None, key_fifths=KEY_FIFTHS + (2 if bb else 0), program=57,
                 chords=nt["chords"], chord_transpose=(1, 2) if bb else (0, 0))
    p.measure_words = {1: [("piano intro — slashes = rhythm section only", "above", 1)],
                       first["theme2"]: [("harmon mute", "section", 1)], first["return"]: [("open", "section", 1)]}
    return p


def section_breaks(sections: list[dict]) -> set[int]:
    return {s["bars"][0] for s in sections}


def build(seed: int = 7, out: Path = OUT) -> dict:
    inp = load_inputs(seed)
    nt = build_notation(inp)
    parts = make_parts(nt)
    n_bars, secs = nt["n_bars"], nt["sections"]
    tm = tempo_marks(n_bars)
    brk = section_breaks(secs)
    out.mkdir(parents=True, exist_ok=True)
    (out / "parts").mkdir(exist_ok=True)
    files = {}

    def w(path: Path, ps: list[PartSpec], sub: str, breaks: set[int] = frozenset()):
        path.write_text(score_xml(ps, n_bars, secs, tm, set(breaks), sub), encoding="utf-8")
        files[str(path.relative_to(out))] = path

    import copy
    below = [copy.copy(parts[k]) for k in ("piano", "bass", "drums")]
    for p in below:
        p.system_text = False
    w(out / "full_score.musicxml", [parts["trumpet"]] + below, "Full score (transposed) — " + SUBTITLE)
    w(out / "parts" / "trumpet_bb.musicxml", [_with_part_chords(parts["trumpet"], nt)], "Trumpet in B♭")
    w(out / "parts" / "piano.musicxml", [parts["piano"]], "Piano")
    w(out / "parts" / "piano_comp_slash.musicxml", [piano_slash_variant(parts["piano"], nt)],
      "Piano — comp-freely (slash) version")
    w(out / "parts" / "bass.musicxml", [parts["bass"]], "Double Bass (sounds an octave lower)")
    w(out / "parts" / "drums.musicxml", [parts["drums"]], "Drum Set (brushes)")
    w(out / "lead_sheet_C.musicxml", [lead_sheet(nt, False)], "Lead sheet — concert pitch (C)")
    w(out / "lead_sheet_Bb.musicxml", [lead_sheet(nt, True)], "Lead sheet — B♭ instruments")
    events = score_events(nt, inp)
    (out / "score_events.json").write_text(json.dumps(events, ensure_ascii=False, indent=0), encoding="utf-8")
    return {"files": files, "events": events, "notation": nt, "parts": parts}


def _with_part_chords(tp: PartSpec, nt: dict) -> PartSpec:
    import copy
    p = copy.copy(tp)
    # 只在小號有吹的小節（和前一小節）標和弦；休息段落留給多小節休止符
    play = {int(n.start // BAR) + 1 for n in nt["trumpet"]} | {int((n.end - Fr(1, 100)) // BAR) + 1 for n in nt["trumpet"]}
    play |= {b - 1 for b in play}
    p.chords = [(t, c) for t, c in nt["chords"] if int(t // BAR) + 1 in play]
    p.chord_transpose = (1, 2)
    return p


def score_events(nt: dict, inp: dict) -> dict:
    def ser(ns: list[NE], part: str, staff: int = 1) -> list[dict]:
        return [{"part": part, "staff": staff, "pitch": n.pitch, "start": float(n.start), "end": float(n.end),
                 "start_frac": str(n.start), "bar": int(n.start // BAR) + 1,
                 "beat": float(n.start - (int(n.start // BAR)) * BAR) + 1, "graces": n.graces,
                 "src": n.src, "inst": n.inst} for n in sorted(ns, key=lambda n: (n.start, n.pitch))]
    ev = nt["events"]
    return {"tempo": ev["tempo"], "n_bars": nt["n_bars"], "swing": nt["swing"],
            "midi_matches_arrangement": inp["midi_matches_arrangement"],
            "parts": {"trumpet": ser(nt["trumpet"], "trumpet"), "bass": ser(nt["bass"], "bass"),
                      "piano": ser(nt["rh_line"] + nt["rh_top"], "piano", 1) + ser(nt["lh"], "piano", 2),
                      "drums": ser(nt["drum_hands"] + nt["drum_feet"], "drums")},
            "midi": {k: [{"pitch": n["pitch"], "start": n["start"], "dur": n["dur"], "tag": n["tag"]}
                         for n in v] for k, v in ev["parts"].items()},
            "sweep_only_bars": sorted(nt["sweep_only"])}


# ───────────────────────── PDF（MuseScore CLI）─────────────────────────

STYLE_PART = """<?xml version="1.0" encoding="UTF-8"?>
<museScore version="4.70">
  <Style>
    <createMultiMeasureRests>1</createMultiMeasureRests>
    <minEmptyMeasures>2</minEmptyMeasures>
    <spatium>1.75</spatium>
    <pageWidth>8.27</pageWidth>
    <pageHeight>11.69</pageHeight>
    <pagePrintableWidth>7.4826</pagePrintableWidth>
    <showMeasureNumberOne>0</showMeasureNumberOne>
  </Style>
</museScore>
"""
STYLE_SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<museScore version="4.70">
  <Style>
    <spatium>1.35</spatium>
    <pageWidth>8.27</pageWidth>
    <pageHeight>11.69</pageHeight>
    <pagePrintableWidth>7.4826</pagePrintableWidth>
    <enableVerticalSpread>0</enableVerticalSpread>
    <minSystemDistance>6</minSystemDistance>
    <maxSystemDistance>9</maxSystemDistance>
    <staffDistance>4</staffDistance>
    <akkoladeDistance>4</akkoladeDistance>
    <hideEmptyStaves>1</hideEmptyStaves>
    <dontHideStavesInFirstSystem>1</dontHideStavesInFirstSystem>
  </Style>
</museScore>
"""


def find_mscore(explicit: str | None = None) -> Path:
    cands = ([Path(explicit)] if explicit else []) + ([Path(os.environ["MSCORE"])] if os.environ.get("MSCORE") else []) \
        + MSCORE_CANDIDATES
    for c in cands:
        if c.exists():
            return c
    w = shutil.which("MuseScore4") or shutil.which("mscore")
    if w:
        return Path(w)
    raise FileNotFoundError("找不到 MuseScore4.exe（可用 --mscore 或環境變數 MSCORE 指定）")


def export_pdfs(out: Path = OUT, mscore: str | None = None, png: bool = True) -> list[dict]:
    ms = find_mscore(mscore)
    RENDER.mkdir(parents=True, exist_ok=True)
    (RENDER / "style_part.mss").write_text(STYLE_PART, encoding="utf-8")
    (RENDER / "style_score.mss").write_text(STYLE_SCORE, encoding="utf-8")
    jobs = []
    for x in sorted(out.rglob("*.musicxml")):
        style = RENDER / ("style_score.mss" if x.name == "full_score.musicxml" else "style_part.mss")
        jobs.append((x, x.with_suffix(".pdf"), style))
    results = []
    for src, pdf, style in jobs:
        mscz = RENDER / (src.stem + ".mscz")
        r1 = subprocess.run([str(ms), "-S", str(style), "-o", str(mscz), str(src)], capture_output=True, text=True,
                            timeout=600)
        r2 = subprocess.run([str(ms), "-o", str(pdf), str(mscz)], capture_output=True, text=True, timeout=600)
        item = {"src": str(src.relative_to(out)), "pdf": str(pdf.relative_to(out)), "ok": pdf.exists(),
                "rc": [r1.returncode, r2.returncode]}
        if png:
            pat = RENDER / "png" / (src.stem + ".png")
            pat.parent.mkdir(parents=True, exist_ok=True)
            for old in pat.parent.glob(src.stem + "-*.png"):
                old.unlink()
            subprocess.run([str(ms), "-r", "110", "-o", str(pat), str(mscz)], capture_output=True, text=True, timeout=600)
            item["png"] = sorted(str(p) for p in pat.parent.glob(src.stem + "-*.png"))
        results.append(item)
    return results


# ───────────────────────── 驗證（聽寫比對）─────────────────────────

def beat_to_sec_fn(tempo: list) -> callable:
    tm = sorted((float(b), float(v)) for b, v in tempo)

    def f(beat: float) -> float:
        s = 0.0
        for (b0, bpm), nxt in zip(tm, tm[1:] + [(float("inf"), 0)]):
            if beat <= b0:
                break
            s += (min(beat, nxt[0]) - b0) * 60.0 / bpm
        return s
    return f


def sec_to_beat_fn(tempo: list) -> callable:
    tm = sorted((float(b), float(v)) for b, v in tempo)
    b2s = beat_to_sec_fn(tempo)

    def f(sec: float) -> float:
        for (b0, bpm), nxt in zip(tm, tm[1:] + [(float("inf"), 0)]):
            s0 = b2s(b0)
            s1 = b2s(nxt[0]) if nxt[0] != float("inf") else float("inf")
            if sec < s1:
                return b0 + (sec - s0) * bpm / 60.0
        return tm[-1][0]
    return f


def compare_line(score: list[dict], heard: list[dict], tempo: list, pitch_range: tuple[int, int]) -> dict:
    """單音聲部：score（拍）↔ basic-pitch（秒）。對齊用 listen.align_notes；音高吻合＝對到的配對中音高相同；
    拍位吻合＝音高相同的配對中，聽到的起音換算成拍後落在記譜位置 −0.25～+0.6 拍內（lay-back 在後）。"""
    import listen as L
    b2s = beat_to_sec_fn(tempo)
    s2b = sec_to_beat_fn(tempo)
    ref = [{"pitch": n["pitch"], "onset": b2s(n["start"]), "end": b2s(n["end"]), "beat": n["start"]} for n in score]
    est = L.skyline(heard, min_dur=0.06, pitch_range=pitch_range)
    res = L.compare_melody(ref, est, transpose=0)
    ref_s = sorted(ref, key=lambda n: n["onset"])
    est_s = sorted(est, key=lambda n: n["onset"])
    pairs = L.align_notes(ref_s, est_s, offset=res["time_offset_s"])
    matched = [(ref_s[i], est_s[j]) for i, j in pairs if i is not None and j is not None]
    same = [(r, e) for r, e in matched if r["pitch"] == e["pitch"]]
    octv = [(r, e) for r, e in matched if r["pitch"] != e["pitch"] and (r["pitch"] - e["pitch"]) % 12 == 0]
    d_beats = [s2b(e["onset"]) - r["beat"] for r, e in same]
    in_beat = [d for d in d_beats if -0.25 <= d <= 0.6]
    import statistics as st
    lag = st.median(d_beats) if d_beats else 0.0

    def bar_ok(r, e):   # 扣掉整體 lay-back 後，聽到的起音落在同一小節（小節線附近 ±0.25 拍的抖動也算）
        a = s2b(e["onset"]) - lag
        return int(a // BAR) == int(r["beat"] // BAR) or abs(a - r["beat"]) <= 0.25
    same_bar = [1 for r, e in same if bar_ok(r, e)]
    low = [(r, e) for r, e in matched if r["pitch"] >= 36]
    return {"n_score": len(ref), "n_heard": len(est), "pairs": len(matched),
            "pitch_match_rate_of_pairs": round(len(same) / len(matched), 4) if matched else None,
            "pitch_or_octave_match_rate_of_pairs": round((len(same) + len(octv)) / len(matched), 4) if matched else None,
            "score_notes_recalled_exact_pitch": round(len(same) / len(ref), 4) if ref else None,
            "pitch_match_rate_pairs_from_C2_up": round(sum(1 for r, e in low if r["pitch"] == e["pitch"]) / len(low), 4)
            if low else None,
            "pairs_below_C2": len(matched) - len(low),
            "note_f1_listen": res["note_f1"],
            "beat_position_match_rate": round(len(in_beat) / len(same), 4) if same else None,
            "bar_match_rate_after_lag": round(len(same_bar) / len(same), 4) if same else None,
            "median_lag_beats": round(st.median(d_beats), 3) if d_beats else None,
            "p10_p90_lag_beats": [round(x, 3) for x in st.quantiles(d_beats, n=10)[::8]] if len(d_beats) > 10 else None,
            "wrong_pitch_examples": res["wrong_pitch"][:8], "missing_examples": res["missing"][:8]}


def compare_piano_bars(score: list[dict], heard: list[dict], tempo: list, bars: list[int]) -> dict:
    """鋼琴：每小節「記譜音高類集合」vs「轉寫音高類集合」（起音在該小節內、長度 ≥ 0.1 s）。"""
    b2s = beat_to_sec_fn(tempo)
    rows = []
    for b in bars:
        a, z = (b - 1) * BAR, b * BAR
        S = {n["pitch"] % 12 for n in score if a <= n["start"] < z}
        sa, sz = b2s(a) - 0.05, b2s(z) - 0.05
        T = {n["pitch"] % 12 for n in heard if sa <= n["onset"] < sz and n["end"] - n["onset"] >= 0.1}
        inter = S & T
        rows.append({"bar": b, "score_pcs": sorted(S), "heard_pcs": sorted(T),
                     "recall": round(len(inter) / len(S), 3) if S else None,
                     "precision": round(len(inter) / len(T), 3) if T else None})
    rec = [r["recall"] for r in rows if r["recall"] is not None]
    pre = [r["precision"] for r in rows if r["precision"] is not None]
    return {"bars": bars, "mean_pc_recall": round(sum(rec) / len(rec), 3), "mean_pc_precision": round(sum(pre) / len(pre), 3),
            "bars_full_recall": sum(1 for r in rec if r == 1.0), "rows": rows}


def compare_midi(events: dict) -> dict:
    """記譜事件 ↔ 實際渲染的（人性化）MIDI：逐音對應（同音高、最近位置），看記譜位置偏離多少拍。"""
    out = {}
    for part in ("trumpet", "bass", "piano"):
        sc = events["parts"][part]
        md = [n for n in events["midi"][part] if n["tag"] not in ("grace", "slide")]
        used = set()
        devs = []
        for m in md:
            cands = [(abs(s["start"] - m["start"]), k) for k, s in enumerate(sc)
                     if s["pitch"] == m["pitch"] and k not in used and abs(s["start"] - m["start"]) < 1.0]
            if cands:
                d, k = min(cands)
                used.add(k)
                devs.append(m["start"] - sc[k]["start"])
        import statistics as st
        out[part] = {"midi_notes": len(md), "matched_same_pitch_within_1_beat": len(devs),
                     "match_rate": round(len(devs) / len(md), 4),
                     "within_half_beat": round(sum(1 for d in devs if -0.3 <= d <= 0.5) / len(md), 4),
                     "median_humanize_offset_beats": round(st.median(devs), 3) if devs else None,
                     "score_notes": len(sc)}
    return out


def verify(stems: Path, out: Path = OUT, cache: Path = RENDER) -> dict:
    sys.path.insert(0, str(HERE))
    import listen as L
    events = json.loads((out / "score_events.json").read_text(encoding="utf-8"))
    heard = {}
    for part in ("trumpet", "bass", "piano"):
        cp = cache / f"transcribe_{part}.json"
        if cp.exists():
            heard[part] = json.loads(cp.read_text(encoding="utf-8"))
        else:
            heard[part] = [{k: (float(v) if k != "pitch" else int(v)) for k, v in n.items()}
                           for n in L.transcribe(str(stems / f"{part}.wav"))]
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(heard[part]), encoding="utf-8")
    T = events["tempo"]
    res = {"stems": str(stems), "method": "basic-pitch (ICASSP 2022, ONNX) transcription of iter6 stems vs notated "
                                          "events; tempo map converts seconds↔beats",
           "trumpet": compare_line(events["parts"]["trumpet"], heard["trumpet"], T, (50, 84)),
           "bass": compare_line(events["parts"]["bass"], heard["bass"], T, (26, 55)),
           "piano": compare_piano_bars(events["parts"]["piano"], heard["piano"], T,
                                       list(range(9, 17)) + list(range(36, 44)) + list(range(71, 79))),
           "score_vs_rendered_midi": compare_midi(events)}
    (out / "verification.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def readback(out: Path = OUT) -> dict:
    """music21 讀回每個 MusicXML：小節數、拍號、調號，並把小號／低音的實音與 score_events 逐音比對。"""
    import music21 as m21
    events = json.loads((out / "score_events.json").read_text(encoding="utf-8"))
    rep = {}
    for x in sorted(out.rglob("*.musicxml")):
        key = str(x.relative_to(out))
        try:
            s = m21.converter.parse(str(x))
        except Exception as ex:  # noqa: BLE001
            rep[key] = {"ok": False, "error": f"{type(ex).__name__}: {ex}"[:300]}
            continue
        info = {"ok": True, "parts": len(s.parts)}
        p0 = s.parts[0]
        ms = list(p0.getElementsByClass("Measure"))
        info["measures"] = len(ms)
        ts = p0.recurse().getElementsByClass("TimeSignature")
        info["time"] = ts[0].ratioString if ts else None
        ks = p0.recurse().getElementsByClass("KeySignature")
        info["key_sharps_first_part"] = ks[0].sharps if ks else None
        info["chord_symbols"] = len(list(s.recurse().getElementsByClass("ChordSymbol")))
        bad = [m.number for p in s.parts for m in p.getElementsByClass("Measure")
               if abs(m.duration.quarterLength - 3.0) > 1e-6 and not m.duration.quarterLength == 0]
        info["measures_not_3_beats"] = bad[:10]
        for pname, target in (("Trumpet", "trumpet"), ("Double Bass", "bass")):
            for p in s.parts:
                if (p.partName or "").startswith(pname) or (target == "trumpet" and key.startswith("lead_sheet")):
                    snd = p.toSoundingPitch() if key.startswith(("full", "parts", "lead_sheet_Bb")) else p
                    got = []
                    for n in snd.recurse().notes:
                        if isinstance(n, m21.harmony.ChordSymbol) or n.duration.isGrace or                                 getattr(n, "notehead", "") == "slash":
                            continue
                        if n.tie is not None and n.tie.type in ("stop", "continue"):
                            continue
                        off = float(n.getOffsetInHierarchy(snd))
                        for pp in (n.pitches if n.isChord else [n.pitch]):
                            got.append((round(off, 3), pp.midi))
                    want = [(round(e["start"], 3), e["pitch"]) for e in events["parts"][target]]
                    info[f"{target}_notes_match"] = {"read": len(got), "expected": len(want),
                                                    "identical": sorted(got) == sorted(want)}
                    if sorted(got) != sorted(want):
                        diff = sorted(set(got) ^ set(want))[:8]
                        info[f"{target}_notes_match"]["diff_examples"] = diff
                    break
        rep[key] = info
    (out / "readback.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def _wsl(cmd_args: list[str], venv: str) -> int:
    def conv(p: str) -> str:
        m = re.match(r"^([A-Za-z]):[\\/](.*)$", p)
        return f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/") if m else p.replace("\\", "/")
    parts = [conv(str(REPO)), f"~/{venv}/bin/python", conv(str(Path(__file__).resolve()))] + \
            [conv(a) if re.match(r"^[A-Za-z]:[\\/]", a) else a for a in cmd_args]
    cmd = f"cd '{parts[0]}' && {parts[1]} '{parts[2]}' " + " ".join(f"'{a}'" for a in parts[3:])
    return subprocess.run(["wsl", "-e", "bash", "-lc", cmd]).returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--out", type=Path, default=OUT)
    p = sub.add_parser("pdf")
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--mscore")
    p.add_argument("--no-png", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--stems", type=Path, default=PROJ / "_render" / "music" / "iter6" / "stems")
    v.add_argument("--out", type=Path, default=OUT)
    r = sub.add_parser("readback")
    r.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "build":
        res = build(a.seed, a.out)
        print(json.dumps({"files": sorted(res["files"]), "midi_matches_arrangement":
                          res["events"]["midi_matches_arrangement"]}, ensure_ascii=False, indent=1))
    elif a.cmd == "pdf":
        print(json.dumps(export_pdfs(a.out, a.mscore, not a.no_png), ensure_ascii=False, indent=1))
    elif a.cmd == "verify":
        try:
            import basic_pitch  # noqa: F401
        except ImportError:
            if os.name == "nt":
                return _wsl(["verify", "--stems", str(a.stems), "--out", str(a.out)], ".venv-listen")
            raise
        res = verify(a.stems, a.out)
        print(json.dumps({k: {kk: vv for kk, vv in v.items() if not isinstance(vv, list) or kk == "bars"}
                          if isinstance(v, dict) else v for k, v in res.items()}, ensure_ascii=False, indent=1))
    elif a.cmd == "readback":
        try:
            import music21  # noqa: F401
        except ImportError:
            if os.name == "nt":
                return _wsl(["readback", "--out", str(a.out)], ".venv-jazz")
            raise
        print(json.dumps(readback(a.out), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
