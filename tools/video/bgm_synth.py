"""《暗渠之書》影片配樂產生器：鐘聲 + 風鈴 + 鋼片琴，物理/加法合成，完全自產（無取樣、無版權素材）。

用法（在 vn-engine 根目錄）：
    python tools/video/bgm_synth.py --shots video_out/anqu_narrated.shots.json \
        --duration 554.874 --seed 7 --out video_out/remaster_v2/bgm/bgm_full.wav

設計：
- 三種音色都是自己合成：
  * 鐘（寺廟/教堂鐘）：非諧波分音 hum 0.5 / prime 1 / tierce 1.19 / quint 1.5 / nominal 2 / 2.5 / 2.9 / 4.2 / 5.4，
    每個分音拆成兩個略失諧的分量產生拍頻，低分音尾音長（低鐘 hum T60 可到 40 秒）；「遠方」鐘再過低通、殘響送多。
  * 風鈴：金屬管自由振動模態 1 : 2.756 : 5.404 : 8.933，一陣風 = 一簇敲擊（多數 1–2 聲，偶爾 3–7 聲）。
  * 鋼片琴：近正弦 + 少量 2/3/4 倍泛音，快起音、1–3 秒衰減、輕微槌擊雜訊，音高帶極小的漂移（第三章會往下滑）。
- 旋律素材：Locrian 音階片段與 [0, +1, -6, -5]（小二度 + 三全音）的 4 音動機，極稀疏。
- 對齊劇情：從 shots.json 重建旁白時間軸（與 render.line_times 同邏輯），旁白中事件率大幅降低、力度降低、
  整體再預先壓低約 5 dB；章節標題卡、旁白停頓處放鐘聲或動機；「停電」之後進入暗段：更空、更低。
- 殘響：自己生成的雙頻段指數衰減雜訊 IR（約 3.2 秒），左右聲道去相關。
- 響度：內建 ITU-R BS.1770 K-weighting 積分響度，正規化到 --lufs（預設 -30 LUFS）。

同一個 --seed、--duration、--shots → 位元完全相同的輸出。
"""
from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 48000
LINE_GAP = 0.6          # 與 vns_shots.LINE_GAP 相同：有旁白時每行後的停頓
TITLE_SEC = 3.5         # 與 render.TITLE_SEC 相同
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
DARK_WORDS = ("停電", "陷入黑暗", "熄滅")
DEEP_WORDS = ("櫓聲",)


# ───────────────────────── 時間軸 ─────────────────────────

@dataclass
class Timeline:
    duration: float
    speech: list[tuple[float, float]]                 # 旁白正在說話的區間
    titles: list[tuple[float, int]]                   # (標題卡起點, 章號)
    chapters: list[tuple[float, float, int]]          # (起, 迄, 章號)
    shot_starts: list[float]
    dark_start: float | None = None                   # 停電/進入暗處
    deep_cues: list[float] = field(default_factory=list)  # 特別要一記最低鐘的時點（例：「是櫓聲。」之後）

    def chapter_at(self, t: float) -> int:
        for a, b, n in self.chapters:
            if a <= t < b:
                return n
        return self.chapters[-1][2] if self.chapters else 1

    def in_speech(self, t: float) -> bool:
        return any(a <= t < b for a, b in self.speech)

    def gaps(self, min_len: float = 0.8) -> list[tuple[float, float]]:
        out, t = [], 0.0
        for a, b in sorted(self.speech):
            if a - t >= min_len:
                out.append((t, a))
            t = max(t, b)
        if self.duration - t >= min_len:
            out.append((t, self.duration))
        return out

    def speech_mask(self, n: int, sr: int) -> np.ndarray:
        m = np.zeros(n, dtype=bool)
        for a, b in self.speech:
            m[int(a * sr):int(b * sr)] = True
        return m


def _chapter_no(name: str, fallback: int) -> int:
    m = re.search(r"第([一二三四五六七八九十]+)章", name or "")
    if not m:
        return fallback
    s = m.group(1)
    return CN_NUM.get(s, fallback) if len(s) == 1 else fallback


def load_timeline(shots: list[dict], duration: float | None = None) -> Timeline:
    """由 shots.json 重建時間軸；逐行規則與 render.line_times 一致（pause_before 累加、行後 LINE_GAP、到 shot 尾前 0.3 秒截斷）。"""
    speech, titles, shot_starts, deep = [], [], [], []
    chap_starts: list[tuple[float, int]] = []
    dark_start = dark_shot = None
    names: list[str] = []
    end_all = 0.0
    for s in shots:
        start = float(s["start"])
        end = start + sum(s.get("use_clips") or s.get("clips") or [s.get("seconds", 0.0)])
        end_all = max(end_all, end)
        shot_starts.append(start)
        ch = s.get("chapter", "")
        if ch not in names:
            names.append(ch)
            chap_starts.append((start, _chapter_no(ch, len(names))))
        if s.get("title"):
            titles.append((start, _chapter_no(ch, len(names))))
        dark_ok = s.get("dim", 0) >= 0.5 or "power_failure" in s.get("sfx", [])
        t = start
        for ln in s.get("lines", []):
            t += float(ln.get("pause_before", 0.0))
            if t >= end - 0.3:
                break
            sec = ln.get("audio_sec")
            if sec is None:
                sec = max(2.5, len(ln.get("text", "")) / 6.0)
                seg = (t, min(t + sec, end))
                step = sec
            else:
                seg = (t, min(t + float(sec), end))
                step = float(sec) + LINE_GAP
            speech.append(seg)
            text = ln.get("text", "")
            if dark_start is None and dark_ok and any(w in text for w in DARK_WORDS):
                dark_start = t
            if any(w in text for w in DEEP_WORDS):
                deep.append(seg[1] + 0.25)
            t += step
        if dark_shot is None and (s.get("dim", 0) >= 0.9 or "power_failure" in s.get("sfx", [])):
            dark_shot = start
    if dark_start is None:
        dark_start = dark_shot
    dur = float(duration) if duration else end_all
    chapters = []
    for i, (a, n) in enumerate(chap_starts):
        b = chap_starts[i + 1][0] if i + 1 < len(chap_starts) else dur
        chapters.append((a, b, n))
    speech = [(a, min(b, dur)) for a, b in speech if a < dur]
    if dark_start is not None and dark_start >= dur - 1.0:
        dark_start = None
    deep = [t for t in deep if t < dur]
    titles = [(t, n) for t, n in titles if t < dur]
    shot_starts = [t for t in shot_starts if t < dur]
    chapters = [c for c in chapters if c[0] < dur]
    return Timeline(dur, speech, titles, chapters, shot_starts, dark_start, deep)


# ───────────────────────── 樂器 ─────────────────────────

def _env(n: int, t60: float, sr: int, attack: float = 0.002) -> np.ndarray:
    t = np.arange(n) / sr
    e = np.exp(-6.9078 * t / max(t60, 1e-3))
    na = max(1, int(attack * sr))
    e[:na] *= np.linspace(0.0, 1.0, na)
    return e


def _drift_phase(f: float, n: int, sr: int, cents0: float, glide: float) -> np.ndarray:
    """瞬時頻率 f·2^((cents0 + glide·t/T)/1200) 的相位；glide = 整個音長內滑動的 cents。"""
    t = np.arange(n) / sr
    T = n / sr
    inst = f * np.power(2.0, (cents0 + glide * t / max(T, 1e-6)) / 1200.0)
    return 2 * np.pi * np.cumsum(inst) / sr


def bell(f: float, vel: float, rng: np.random.Generator, sr: int = SR, length: float = 30.0,
         distant: bool = False, max_len: float = 45.0) -> np.ndarray:
    """寺廟/教堂鐘。f = prime（打擊音）頻率；length = hum 分音的 T60。"""
    partials = [  # (比值, 振幅, T60 相對 hum 的比例, 拍頻 Hz)
        (0.5, 0.70, 1.00, 0.25), (1.0, 0.50, 0.62, 0.55), (1.19, 0.42, 0.46, 0.8),
        (1.5, 0.22, 0.34, 0.9), (2.0, 0.50, 0.30, 1.1), (2.5, 0.24, 0.18, 1.4),
        (2.9, 0.20, 0.14, 1.6), (4.2, 0.10, 0.08, 2.0), (5.4, 0.07, 0.05, 2.6),
    ]
    n = int(min(length * 1.05, max_len) * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for ratio, amp, tr, beat in partials:
        fr = f * ratio * (1 + rng.normal(0, 0.002))
        if fr > sr * 0.45:
            continue
        # 高分音在弱敲時更弱（金屬的力度-音色關係）
        a = amp * (vel ** (0.5 + 0.35 * ratio))
        e = _env(n, length * tr, sr, attack=0.004 if ratio >= 1 else 0.03)
        d = beat * rng.uniform(0.6, 1.4)
        p1, p2 = rng.uniform(0, 2 * np.pi, 2)
        out += a * e * (np.sin(2 * np.pi * fr * t + p1) + 0.7 * np.sin(2 * np.pi * (fr + d) * t + p2)) / 1.7
    # 打擊瞬態：短暫帶通雜訊
    nk = int(0.04 * sr)
    click = rng.standard_normal(nk) * np.exp(-np.arange(nk) / (0.008 * sr))
    b, a_ = signal.butter(2, [min(f * 4, 3000) / (sr / 2), min(f * 12, 9000) / (sr / 2)], "band")
    out[:nk] += 0.06 * vel * signal.lfilter(b, a_, click)
    if distant:
        b, a_ = signal.butter(2, 1100 / (sr / 2))
        out = signal.lfilter(b, a_, out)
    return out * vel


CHIME_MODES = [(1.0, 1.0, 1.0), (2.756, 0.55, 0.45), (5.404, 0.30, 0.2), (8.933, 0.16, 0.1)]


def chime(f: float, vel: float, rng: np.random.Generator, sr: int = SR, t60: float = 5.0) -> np.ndarray:
    """風鈴金屬管：自由-自由樑的橫向振動模態。"""
    n = int(t60 * 1.05 * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for ratio, amp, tr in CHIME_MODES:
        fr = f * ratio
        if fr > 18000:
            continue
        a = amp * vel ** (0.6 + 0.25 * ratio)
        e = _env(n, t60 * tr, sr, attack=0.0008)
        out += a * e * np.sin(2 * np.pi * fr * t + rng.uniform(0, 2 * np.pi))
        out += 0.25 * a * e * np.sin(2 * np.pi * (fr + rng.uniform(0.3, 1.5)) * t)  # 管子微不對稱 → 拍頻
    nk = int(0.006 * sr)
    out[:nk] += 0.05 * vel * rng.standard_normal(nk) * np.linspace(1, 0, nk)
    return out * vel


def celesta(f: float, vel: float, rng: np.random.Generator, sr: int = SR, glide: float = 0.0) -> np.ndarray:
    """鋼片琴：近正弦 + 少量 2/3/4 倍泛音，1–3 秒衰減、輕微槌擊聲、極小音高漂移。"""
    t60 = float(np.clip(3.2 * (262.0 / f) ** 0.45, 1.0, 3.2))
    n = int(t60 * 1.1 * sr)
    cents0 = rng.normal(0, 4.0)
    out = np.zeros(n)
    for k, amp in ((1, 1.0), (2, 0.10), (3, 0.035), (4, 0.06)):
        if f * k > sr * 0.45:
            continue
        ph = _drift_phase(f * k, n, sr, cents0, glide)
        out += amp * _env(n, t60 / k ** 1.3, sr, attack=0.0015) * np.sin(ph + rng.uniform(0, 2 * np.pi))
    nk = int(0.012 * sr)
    b, a_ = signal.butter(2, 1800 / (sr / 2), "high")
    out[:nk] += 0.05 * vel * signal.lfilter(b, a_, rng.standard_normal(nk)) * np.linspace(1, 0, nk)
    return out * vel


def reverb_ir(rng: np.random.Generator, sr: int = SR, t60_low: float = 3.4, t60_high: float = 1.4,
              predelay: float = 0.028) -> np.ndarray:
    """雙頻段指數衰減雜訊 IR（高頻衰減較快 = 空氣吸收），回傳 (n, 2) 左右去相關。"""
    n = int((t60_low + 0.3) * sr)
    t = np.arange(n) / sr
    bl, al = signal.butter(2, 2500 / (sr / 2))
    bh, ah = signal.butter(2, 2500 / (sr / 2), "high")
    chans = []
    for _ in range(2):
        z = rng.standard_normal(n)
        low = signal.lfilter(bl, al, z) * np.exp(-6.9078 * t / t60_low)
        high = signal.lfilter(bh, ah, z) * np.exp(-6.9078 * t / t60_high)
        ir = low + 0.6 * high
        ir[: int(0.015 * sr)] *= np.linspace(0, 1, int(0.015 * sr))  # 柔和起始
        ir = np.concatenate([np.zeros(int(predelay * sr)), ir])
        chans.append(ir / np.sqrt(np.sum(ir ** 2)))
    return np.stack(chans, axis=1)


# ───────────────────────── 響度 ─────────────────────────

def k_weight(x: np.ndarray, sr: int = SR) -> np.ndarray:
    """ITU-R BS.1770-4 K-weighting（48 kHz 係數）。"""
    if sr != 48000:
        raise ValueError("k_weight 只實作 48 kHz 係數")
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    return signal.lfilter(b2, a2, signal.lfilter(b1, a1, x, axis=0), axis=0)


def integrated_lufs(x: np.ndarray, sr: int = SR) -> float:
    x = np.atleast_2d(x.T).T if x.ndim == 1 else x
    y = k_weight(x.astype(np.float64), sr)
    blk, hop = int(0.4 * sr), int(0.1 * sr)
    if len(y) < blk:
        return -np.inf
    p = np.sum(y ** 2, axis=1)
    c = np.concatenate([[0.0], np.cumsum(p)])
    starts = np.arange(0, len(y) - blk + 1, hop)
    ms = (c[starts + blk] - c[starts]) / blk
    lk = -0.691 + 10 * np.log10(np.maximum(ms, 1e-20))
    g = ms[lk > -70]
    if g.size == 0:
        return -np.inf
    rel = -0.691 + 10 * np.log10(g.mean()) - 10
    g2 = ms[(lk > -70) & (lk > rel)]
    return float(-0.691 + 10 * np.log10(g2.mean()))


def true_peak_db(x: np.ndarray) -> float:
    up = signal.resample_poly(x, 4, 1, axis=0)
    return float(20 * np.log10(np.max(np.abs(up)) + 1e-12))


# ───────────────────────── 作曲 ─────────────────────────

@dataclass
class Event:
    t: float
    kind: str          # bell | bell_far | chime | celesta
    f: float
    vel: float
    pan: float = 0.0   # -1 左 … +1 右
    send: float = 0.3  # 殘響送量
    glide: float = 0.0
    length: float = 0.0  # 鐘的 hum T60
    tag: str = ""      # 事件來源（title / gap / motif / random / cue）


def midi(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


LOCRIAN = [0, 1, 3, 5, 6, 8, 10]
MOTIF = [0, 1, -6, -5]               # 小二度上行、三全音下墜、再小二度
# 章節設定：rate 單位 = 次/分鐘（非旁白時段）；celesta_root 為 MIDI；bell = prime 的 MIDI
CHAPTER_CFG = {
    1: dict(celesta_root=76, oct_span=(0, 1), celesta=3.0, chime=1.2, bell=0.4, bell_note=43, glide=0.0, gap_p=1.0),
    2: dict(celesta_root=70, oct_span=(0, 1), celesta=3.2, chime=0.9, bell=0.45, bell_note=42, glide=-4.0, gap_p=1.0),
    3: dict(celesta_root=64, oct_span=(0, 1), celesta=2.4, chime=1.4, bell=0.4, bell_note=38, glide=-8.0, gap_p=0.8),
}
# 停電之後：鋼片琴降到最低音域、風鈴幾乎消失、只剩偶爾一記遠方低鐘；旁白停頓處也多半留白
DARK_CFG = dict(celesta_root=60, oct_span=(0, 0), celesta=1.6, chime=0.15, bell=0.25, bell_note=34, glide=-15.0,
                gap_p=0.45)
CHIME_TUBES = [83, 84, 89, 90, 95, 96]   # B5 C6 F6 F#6 B6 C7：小二度與三全音交錯的一組管子
SPEECH_RATE = dict(celesta=0.5, chime=0.6, bell=0.7)
SPEECH_VEL = 0.65
MAX_SILENCE = 16.0      # 秒；暗段放寬到 1.35 倍


def _cfg(tl: Timeline, t: float) -> dict:
    if tl.dark_start is not None and t >= tl.dark_start:
        return DARK_CFG
    return CHAPTER_CFG.get(tl.chapter_at(t), CHAPTER_CFG[1])


def compose(tl: Timeline, rng: np.random.Generator) -> list[Event]:
    ev: list[Event] = []
    dur = tl.duration
    quiet: list[tuple[float, float]] = []   # 刻意留白（不放隨機事件）的區間

    def is_quiet(t):
        return any(a <= t < b for a, b in quiet)

    def free(a0, b0):
        """[a0, b0) 不與任何留白/已排動機區間重疊。"""
        return not any(a < b0 and a0 < b for a, b in quiet)

    def add_motif(t0: float, root: int, vel: float, variant: int, glide: float, tag: str = "motif"):
        pat = list(MOTIF)
        if variant == 1:
            pat = [-p for p in pat]              # 倒影
        elif variant == 2:
            pat = pat[::-1]                      # 逆行
        elif variant == 3:
            pat = pat[:3]                        # 截短
        t = last = t0
        for i, p in enumerate(pat):
            if t >= dur - 0.5:
                break
            ev.append(Event(t, "celesta", midi(root + p), vel * (1.0 if i == 0 else rng.uniform(0.7, 0.95)),
                            pan=rng.uniform(-0.25, 0.25), send=0.4, glide=glide, tag=tag))
            last = t
            t += rng.uniform(0.95, 1.7) * (1.25 if i == len(pat) - 2 else 1.0)  # 最後一音前拖一下
        quiet.append((t0, last + 1.5))   # 動機期間（含最後一音的餘韻）不再疊隨機事件
        return last

    def add_gust(t0: float, vel: float, tag: str = "gust", dense: bool = False):
        r = rng.random()
        k = 1 if r < 0.45 else 2 if r < 0.75 else int(rng.integers(3, 8))
        if dense:
            k = max(k, int(rng.integers(4, 9)))
        span = rng.uniform(0.4, 1.2) + 0.35 * k
        times = np.sort(t0 + span * rng.beta(1.6, 2.2, size=k))
        last = -1
        for tt in times:
            if tt >= dur - 0.3:
                break
            idx = int(rng.integers(len(CHIME_TUBES)))
            if idx == last:
                idx = (idx + 1) % len(CHIME_TUBES)
            last = idx
            ev.append(Event(float(tt), "chime", midi(CHIME_TUBES[idx]), vel * rng.uniform(0.25, 1.0),
                            pan=-0.6 + 1.2 * idx / (len(CHIME_TUBES) - 1), send=0.32, tag=tag))

    # 1) 章節標題卡：一記鐘（第一章＝遠方低鐘 + 動機；第三章更低）
    for t0, ch in tl.titles:
        c = CHAPTER_CFG.get(ch, CHAPTER_CFG[1])
        ev.append(Event(t0 + 0.15, "bell_far" if ch != 2 else "bell", midi(c["bell_note"]), 0.6 if ch != 3 else 0.55,
                        pan=rng.uniform(-0.15, 0.15), send=0.55 if ch != 2 else 0.3,
                        length=38.0 if ch == 3 else 30.0, tag="title"))
        quiet.append((t0, t0 + 3.4))
        add_motif(t0 + 1.3, c["celesta_root"] + 12 * (ch == 1), 0.55 if ch != 3 else 0.42, variant=(ch - 1) % 4,
                  glide=c["glide"], tag="title-motif")

    # 2) 停電：切掉一切，留白 14 秒，然後一記最低、最遠的鐘
    if tl.dark_start is not None:
        # 暴雨先到：停電前 2 秒一陣急風把風鈴吹亂，然後在停電那一刻整個被切掉（render 的 cut 包絡）
        if tl.dark_start - 2.2 > 0:
            add_gust(tl.dark_start - 2.2, 0.5, tag="storm-gust", dense=True)
        quiet.append((tl.dark_start - 2.5, tl.dark_start + 14.0))
        ev.append(Event(tl.dark_start + 14.0, "bell_far", midi(DARK_CFG["bell_note"]), 0.6,
                        send=0.7, length=36.0, tag="dark-cue"))
    for tc in tl.deep_cues:          # 「是櫓聲。」之後：地底傳來的更低一記
        ev.append(Event(tc, "bell_far", midi(DARK_CFG["bell_note"] - 5), 0.55, pan=-0.2,
                        send=0.75, length=32.0, tag="deep-cue"))
        quiet.append((tc - 0.5, tc + 6.0))

    # 3) 旁白停頓（>= 1.2 秒）：動機 / 單音 / 一陣風
    speech_starts = sorted(a for a, _ in tl.speech)
    for a, b in tl.gaps(1.2):
        if is_quiet(a + 0.1) or a < 0.5:
            continue
        c = _cfg(tl, a)
        glen = b - a
        if rng.random() > c["gap_p"]:
            continue
        r = rng.random()
        if glen >= 2.6 and r < 0.45 and free(a, a + 6.5):
            add_motif(a + 0.2, c["celesta_root"] + 12 * int(rng.integers(c["oct_span"][0], c["oct_span"][1] + 1)),
                      0.5, variant=int(rng.integers(4)), glide=c["glide"], tag="gap-motif")
        elif not free(a, a + 1.0):
            continue
        elif r < 0.75:
            deg = LOCRIAN[int(rng.integers(len(LOCRIAN)))]
            ev.append(Event(a + 0.15, "celesta", midi(c["celesta_root"] + deg + 12 * int(rng.integers(0, 2))),
                            0.5, pan=rng.uniform(-0.4, 0.4), send=0.4, glide=c["glide"], tag="gap-note"))
        else:
            add_gust(a + 0.1, 0.55, tag="gap-gust")

    # 4) 換景（非標題的 shot 起點）：一陣風或一記中鐘
    title_starts = {round(t, 2) for t, _ in tl.titles}
    for s in tl.shot_starts:
        if round(s, 2) in title_starts or not free(s, s + 2.5):
            continue
        c = _cfg(tl, s)
        if rng.random() < 0.5:
            add_gust(s + 0.05, 0.5, tag="shot-gust")
        else:
            ev.append(Event(s + 0.05, "bell", midi(c["bell_note"] + 12), 0.45, pan=rng.uniform(-0.3, 0.3),
                            send=0.4, length=16.0, tag="shot-bell"))

    # 5) 隨機稀疏事件（非齊次 Poisson，旁白中率降低）
    step = 0.25
    t = 0.5
    while t < dur - 1.0:
        if not is_quiet(t):
            c = _cfg(tl, t)
            sp = tl.in_speech(t)
            for kind in ("celesta", "chime", "bell"):
                rate = c[kind] / 60.0 * (SPEECH_RATE[kind] if sp else 1.0)
                if rng.random() < rate * step:
                    vel = rng.uniform(0.3, 0.75) * (SPEECH_VEL if sp else 1.0)
                    if kind == "celesta":
                        if not sp and rng.random() < 0.12 and free(t, t + 6.5):
                            add_motif(t, c["celesta_root"], vel, int(rng.integers(4)), c["glide"], tag="motif")
                        else:
                            octv = int(rng.integers(c["oct_span"][0], c["oct_span"][1] + 1)) + (1 if sp else 0)
                            m = c["celesta_root"] + LOCRIAN[int(rng.integers(len(LOCRIAN)))] + 12 * octv
                            m = min(m, 100)
                            ev.append(Event(t, "celesta", midi(m), vel, pan=rng.uniform(-0.5, 0.5), send=0.4,
                                            glide=c["glide"], tag="random"))
                            if tl.chapter_at(t) == 2 and rng.random() < 0.2:   # 第二章：小二度雙音
                                ev.append(Event(t + 0.01, "celesta", midi(m + 1), vel * 0.8,
                                                pan=rng.uniform(-0.5, 0.5), send=0.4, glide=c["glide"], tag="random"))
                    elif kind == "chime":
                        add_gust(t, vel, tag="random-gust")
                    else:
                        far = rng.random() < 0.6
                        ev.append(Event(t, "bell_far" if far else "bell", midi(c["bell_note"] + (0 if far else 7)),
                                        vel, pan=rng.uniform(-0.4, 0.4), send=0.6 if far else 0.35,
                                        length=34.0 if far else 20.0, tag="random"))
        t += step

    # 6) 結尾：最後一句旁白一開口就鋪一記最低遠鐘，說完再一個未解決的三全音
    if tl.speech:
        la, lb = tl.speech[-1]
        ev.append(Event(max(la - 0.2, 0), "bell_far", midi(DARK_CFG["bell_note"]), 0.55, send=0.7,
                        length=40.0, tag="ending"))
        if lb + 0.4 < dur - 0.8:
            ev.append(Event(lb + 0.4, "celesta", midi(DARK_CFG["celesta_root"] + 6), 0.45, send=0.6,
                            glide=-20.0, tag="ending"))

    # 6b) 底層：每 35–50 秒一記極輕的遠方低鐘，長尾音與拍頻把稀疏的點連成一片「空氣」（停電留白除外）
    t = rng.uniform(20.0, 30.0)
    while t < dur - 8.0:
        if not (tl.dark_start is not None and tl.dark_start - 3.0 <= t < tl.dark_start + 14.0):
            c = _cfg(tl, t)
            ev.append(Event(t, "bell_far", midi(c["bell_note"] - (2 if rng.random() < 0.5 else 0)),
                            rng.uniform(0.2, 0.28), pan=rng.uniform(-0.5, 0.5), send=0.7, length=40.0, tag="drone"))
        t += rng.uniform(35.0, 50.0)

    # 7) 最長留白限制：稀疏但不能「斷掉」——超過 MAX_SILENCE 秒沒有任何起音就補一個很輕的音
    cut = (tl.dark_start, tl.dark_start + 14.0) if tl.dark_start is not None else (-1.0, -1.0)
    ev = [e for e in ev if 0 <= e.t < dur]
    ev.sort(key=lambda e: e.t)
    onsets = [e.t for e in ev]
    fill: list[Event] = []
    prev = 0.0
    for nxt in onsets + [dur - 3.0]:
        while True:
            dark = tl.dark_start is not None and prev >= tl.dark_start
            lim = MAX_SILENCE * (1.35 if dark else 1.0)
            if nxt - prev <= lim:
                break
            tf = prev + lim * rng.uniform(0.6, 0.9)
            if cut[0] <= tf < cut[1]:
                prev = cut[1]
                continue
            c = _cfg(tl, tf)
            r = rng.random()
            if r < 0.5 or dark:
                m = c["celesta_root"] + LOCRIAN[int(rng.integers(len(LOCRIAN)))] + (0 if dark else 12)
                fill.append(Event(tf, "celesta", midi(m), rng.uniform(0.22, 0.34), pan=rng.uniform(-0.5, 0.5),
                                  send=0.5, glide=c["glide"], tag="fill"))
            elif r < 0.8:
                idx = int(rng.integers(len(CHIME_TUBES)))
                fill.append(Event(tf, "chime", midi(CHIME_TUBES[idx]), rng.uniform(0.2, 0.35),
                                  pan=-0.6 + 1.2 * idx / (len(CHIME_TUBES) - 1), send=0.4, tag="fill"))
            else:
                fill.append(Event(tf, "bell_far", midi(c["bell_note"] + 7), rng.uniform(0.3, 0.4),
                                  pan=rng.uniform(-0.4, 0.4), send=0.65, length=24.0, tag="fill"))
            prev = tf
        prev = max(prev, nxt)
    ev += fill
    ev.sort(key=lambda e: (e.t, e.kind))
    return ev


# ───────────────────────── 合成 ─────────────────────────

def _smooth_mask(mask: np.ndarray, sr: int, attack: float = 0.35, release: float = 1.2) -> np.ndarray:
    """0/1 旁白遮罩 → 平滑包絡（提前 attack 秒開始壓、放開後 release 秒回來），在 100 Hz 控制率計算。"""
    hop = sr // 100
    ctrl = mask[::hop].astype(float)
    look = int(attack * 100)
    ctrl = np.maximum(ctrl, np.concatenate([ctrl[look:], np.zeros(look)]))  # 提前
    out = np.empty_like(ctrl)
    a_up = 1 - math.exp(-1 / (0.3 * 100 * attack))
    a_dn = 1 - math.exp(-1 / (100 * release / 3))
    y = 0.0
    for i, v in enumerate(ctrl):
        y += (a_up if v > y else a_dn) * (v - y)
        out[i] = y
    return np.interp(np.arange(len(mask)) / hop, np.arange(len(out)), out)


def render(tl: Timeline, seed: int, sr: int = SR, target_lufs: float = -30.0,
           speech_duck_db: float = -5.0, dark_db: float = -5.0, cut_sec: float = 13.6) -> tuple[np.ndarray, list[Event], dict]:
    rng = np.random.default_rng(seed)
    events = compose(tl, rng)
    n = int(round(tl.duration * sr))
    dry = np.zeros((n, 2), dtype=np.float64)
    send = np.zeros((n, 2), dtype=np.float64)
    gains = {"bell": 0.40, "bell_far": 0.40, "chime": 0.32, "celesta": 0.45}
    for e in events:
        if e.kind in ("bell", "bell_far"):
            x = bell(e.f, e.vel, rng, sr, length=e.length or 24.0, distant=e.kind == "bell_far")
        elif e.kind == "chime":
            x = chime(e.f, e.vel, rng, sr)
        else:
            x = celesta(e.f, e.vel, rng, sr, glide=e.glide)
        x *= gains[e.kind]
        i0 = int(e.t * sr)
        m = min(len(x), n - i0)
        if m <= 0:
            continue
        th = (e.pan + 1) * np.pi / 4
        lr = np.array([np.cos(th), np.sin(th)])
        seg = x[:m, None] * lr[None, :]
        dry[i0:i0 + m] += seg * (1 - 0.5 * e.send)
        send[i0:i0 + m] += seg * e.send
    ir = reverb_ir(rng, sr)
    wet = np.stack([signal.oaconvolve(send[:, c], ir[:, c])[:n] for c in range(2)], axis=1)
    mix = dry + 1.4 * wet
    # 旁白時段預先壓低（主控之後還會再做 sidechain ducking）
    env = _smooth_mask(tl.speech_mask(n, sr), sr)
    mix *= (10 ** (speech_duck_db / 20)) ** env[:, None]
    if tl.dark_start is not None:
        # 停電：所有聲音在 80 ms 內被切斷（連殘響尾巴），留白 cut_sec 秒後以較低的整體音量回來
        g = np.ones(n)
        i0 = int(tl.dark_start * sr)
        i1 = min(n, i0 + int(0.08 * sr))
        i2 = min(n, int((tl.dark_start + cut_sec) * sr))
        i3 = min(n, i2 + int(0.4 * sr))
        dg = 10 ** (dark_db / 20)
        g[i0:i1] = np.linspace(1, 0, i1 - i0)
        g[i1:i2] = 0.0
        g[i2:i3] = np.linspace(0, dg, i3 - i2)
        g[i3:] = dg
        mix *= g[:, None]
    # 頭尾淡入淡出
    fi, fo = int(0.05 * sr), int(min(2.5, tl.duration / 4) * sr)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.5
    # 極輕的 DC/次低頻清理
    b, a = signal.butter(2, 28 / (sr / 2), "high")
    mix = signal.filtfilt(b, a, mix, axis=0)
    lufs0 = integrated_lufs(mix, sr)
    gain = 10 ** ((target_lufs - lufs0) / 20) if np.isfinite(lufs0) else 1.0
    mix *= gain
    peak = float(np.max(np.abs(mix)))
    if peak > 0.5:  # 背景層不需要大峰值；保險：峰值壓到 -6 dBFS 以下（會讓響度略低於目標，並回報）
        mix *= 0.5 / peak
    info = {"pre_norm_lufs": lufs0, "norm_gain_db": 20 * math.log10(gain), "speech_duck_db": speech_duck_db,
            "dark_db": dark_db, "cut_sec": cut_sec if tl.dark_start is not None else 0.0}
    return mix.astype(np.float32), events, info


# ───────────────────────── 量測 ─────────────────────────

def analyze(mix: np.ndarray, tl: Timeline, events: list[Event], sr: int = SR) -> dict:
    x = mix.astype(np.float64)
    mono = x.mean(axis=1)
    mask = tl.speech_mask(len(mono), sr)

    def rms_db(v):
        return float(10 * np.log10(np.mean(v ** 2) + 1e-20))

    def centroid(v):
        if len(v) < 4096:
            return float("nan")
        f, p = signal.welch(v, sr, nperseg=8192)
        return float(np.sum(f * p) / (np.sum(p) + 1e-30))

    per_ch = []
    for a, b, ch in tl.chapters:
        i0, i1 = int(a * sr), int(min(b, tl.duration) * sr)
        evs = [e for e in events if a <= e.t < b]
        minutes = (min(b, tl.duration) - a) / 60
        per_ch.append({
            "chapter": ch, "start": round(a, 2), "end": round(min(b, tl.duration), 2),
            "notes_per_min": round(len(evs) / minutes, 2),
            "by_kind": {k: sum(e.kind == k for e in evs) for k in ("celesta", "chime", "bell", "bell_far")},
            "rms_db": round(rms_db(mono[i0:i1]), 2),
            "centroid_hz": round(centroid(mono[i0:i1]), 1),
            "lufs": round(integrated_lufs(x[i0:i1], sr), 2),
        })
    ev_speech = sum(tl.in_speech(e.t) for e in events)
    sp_sec = mask.sum() / sr
    ns_sec = (len(mask) - mask.sum()) / sr
    out = {
        "duration_sec": round(len(mono) / sr, 3),
        "sample_rate": sr,
        "integrated_lufs": round(integrated_lufs(x, sr), 2),
        "sample_peak_dbfs": round(float(20 * np.log10(np.max(np.abs(x)) + 1e-12)), 2),
        "true_peak_dbtp_4x": round(true_peak_db(x), 2),
        "has_nan": bool(np.isnan(x).any()),
        "centroid_hz": round(centroid(mono), 1),
        "events_total": len(events),
        "notes_per_min": round(len(events) / (len(mono) / sr / 60), 2),
        "notes_per_min_in_speech": round(ev_speech / max(sp_sec / 60, 1e-9), 2),
        "notes_per_min_outside_speech": round((len(events) - ev_speech) / max(ns_sec / 60, 1e-9), 2),
        "speech_sec": round(float(sp_sec), 2),
        "rms_db_speech": round(rms_db(mono[mask]), 2) if mask.any() else None,
        "rms_db_non_speech": round(rms_db(mono[~mask]), 2) if (~mask).any() else None,
        "chapters": per_ch,
        "by_tag": {},
    }
    for e in events:
        out["by_tag"][e.tag] = out["by_tag"].get(e.tag, 0) + 1
    if tl.dark_start is not None:
        i = int(tl.dark_start * sr)
        c3 = next((c for c in tl.chapters if c[0] <= tl.dark_start < c[1]), None)
        a0 = int(c3[0] * sr) if c3 else max(0, i - 30 * sr)
        pre_ev = [e for e in events if (c3[0] if c3 else 0) <= e.t < tl.dark_start]
        dark_ev = [e for e in events if e.t >= tl.dark_start]
        out["dark"] = {
            "dark_start": round(tl.dark_start, 2),
            "rms_db_dark": round(rms_db(mono[i:]), 2),
            "lufs_dark": round(integrated_lufs(x[i:], sr), 2),
            "lufs_ch1_2": round(integrated_lufs(x[:a0], sr), 2),
            "rms_db_ch1_2": round(rms_db(mono[:a0]), 2),
            "centroid_hz_dark": round(centroid(mono[i:]), 1),
            "centroid_hz_before_dark_ch1_2": round(centroid(mono[:a0]), 1),
            "notes_per_min_dark": round(len(dark_ev) / ((len(mono) - i) / sr / 60), 2),
            "events_before_dark_in_chapter": len(pre_ev),
        }
    return out


def write_wav(path: Path, mix: np.ndarray, sr: int = SR, seed: int = 0) -> None:
    """16-bit PCM + TPDF dither（dither 雜訊用固定 seed，保持可重現）。"""
    rng = np.random.default_rng(seed + 991)
    d = (rng.random(mix.shape) - rng.random(mix.shape)) / 32768.0
    y = np.clip(np.round((mix + d) * 32767.0), -32768, 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), sr, y)


def synthesize(shots_path: Path, duration: float | None, seed: int, target_lufs: float = -30.0):
    shots = json.loads(Path(shots_path).read_text(encoding="utf-8"))
    tl = load_timeline(shots, duration)
    mix, events, info = render(tl, seed, SR, target_lufs)
    return tl, mix, events, info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shots", type=Path, default=Path("video_out/anqu_narrated.shots.json"))
    ap.add_argument("--duration", type=float, default=None, help="成片秒數（預設：shots 最後一段的結尾）")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--lufs", type=float, default=-30.0)
    ap.add_argument("--out", type=Path, default=Path("video_out/remaster_v2/bgm/bgm_full.wav"))
    ap.add_argument("--stats", type=Path, default=None, help="量測結果 json（預設：<out>.stats.json）")
    a = ap.parse_args(argv)
    tl, mix, events, info = synthesize(a.shots, a.duration, a.seed, a.lufs)
    write_wav(a.out, mix, SR, a.seed)
    stats = analyze(mix, tl, events)
    stats.update({"seed": a.seed, "shots": str(a.shots), "render": info,
                  "timeline": {"titles": tl.titles, "dark_start": tl.dark_start, "deep_cues": tl.deep_cues,
                               "chapters": tl.chapters, "n_speech_segments": len(tl.speech)}})
    stats_path = a.stats or a.out.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    ev_path = a.out.with_suffix(".events.json")
    ev_path.write_text(json.dumps([e.__dict__ for e in events], ensure_ascii=False, indent=0), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("chapters", "timeline")}, ensure_ascii=False))
    for c in stats["chapters"]:
        print(json.dumps(c, ensure_ascii=False))


if __name__ == "__main__":
    main()
