"""AI 聽音工具：讓 Claude 在沒有人耳的情況下評估音樂與旁白。

四層：
  1. 音訊語言模型（Qwen2.5-Omni-7B 4-bit / Qwen2-Audio-7B-Instruct 4-bit）：describe、ask
  2. 分類與評分：Essentia（discogs400 / mtg-jamendo instrument, mood, genre）、
     Meta audiobox-aesthetics（CE/CU/PC/PQ）、LAION-CLAP（音檔 vs 文字相似度）、DSP 頻段量測
  3. 轉譜與節奏：basic-pitch（ONNX）→ 音符，與參考 MIDI 做對齊比對；beat_this / librosa 節拍、swing ratio
  4. 綜合：review 跑完全部，依目標描述產出評語（符合 / 不符 / 具體建議）

用法（重型依賴在 WSL venv ~/.venv-listen；在 Windows 直接呼叫會自動轉進 WSL 執行）：
    python tools/video/listen.py describe  <音檔> [--model omni|qwen2-audio] [--start 0 --seconds 30]
    python tools/video/listen.py ask       <音檔> "<問題>"
    python tools/video/listen.py score     <音檔> [--prompts "a" "b" ...]
    python tools/video/listen.py melody    <音檔> --ref <midi> [--track trumpet] [--transpose auto]
    python tools/video/listen.py rhythm    <音檔>
    python tools/video/listen.py review    <音檔> --brief "<目標描述>" [--ref midi] [--stems dir] [--target-bpm 60] [--no-llm]
    python tools/video/listen.py dsp       <音檔>              （純 numpy，不需模型）
    python tools/video/listen.py synth-controls <輸出資料夾>   （合成對照音檔，給驗證用）

輸出一律 JSON 到 stdout（review 另印 Markdown 評語；--out 可寫檔）。

模型位置：環境變數 LISTEN_MODELS（預設 ~/.venv-listen/models），Essentia 模型在
LISTEN_ESSENTIA（預設 repo 內 projects/kalliwoda-jazz/_assets/listen/essentia）。

設計取捨：
- 純函式（對齊、DTW、swing ratio、頻段能量、brief 解析、評語規則）只依賴 numpy，Windows 也能跑、也能測。
- Essentia（內含 TensorFlow）在子行程跑且隱藏 GPU，避免與 torch 搶 CUDA / 函式庫衝突。
- LLM 用 bitsandbytes 4-bit 放 GPU（約 7–9 GB）；GPU 空間不足時自動退回 CPU（慢）。
- 評語規則的門檻是經驗值，report.md 有記錄校準依據；LLM 的敘述只當「參考」，與量測衝突時以量測為準。
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
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DEFAULT_MODELS = Path(os.environ.get("LISTEN_MODELS", str(Path.home() / ".venv-listen" / "models")))
DEFAULT_ESSENTIA = Path(os.environ.get(
    "LISTEN_ESSENTIA", str(REPO / "projects" / "kalliwoda-jazz" / "_assets" / "listen" / "essentia")))
WSL_PY = "~/.venv-listen/bin/python"

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# 模型授權（report 與 --licenses 輸出用）
LICENSES = {
    "Qwen2.5-Omni-7B": "Apache-2.0（可商用）",
    "Qwen2-Audio-7B-Instruct": "Apache-2.0（可商用）",
    "essentia (library)": "AGPL-3.0",
    "essentia models (discogs-effnet, genre_discogs400, mtg_jamendo_*)": "CC BY-NC-SA 4.0（僅非商用/研究；商用需向 MTG-UPF 另購授權）",
    "audiobox-aesthetics": "CC-BY-4.0（程式與權重；可商用，需標示出處）",
    "laion_clap (code) + music_audioset_epoch_15_esc_90.14.pt": "CC0-1.0（程式與 lukewys/laion_clap 權重，可商用）",
    "basic-pitch": "Apache-2.0（可商用）",
    "beat_this": "MIT（程式與權重；作者註明部分訓練資料版權受限，商用需自行評估）",
    "librosa": "ISC",
}


def midi_name(p: int) -> str:
    return f"{NOTE_NAMES[int(p) % 12]}{int(p) // 12 - 1}"


# ---------------------------------------------------------------------------
# 音訊讀取（ffmpeg，支援 mp3 / mp4 / wav）
# ---------------------------------------------------------------------------

def load_audio(path: str | Path, sr: int = 44100, mono: bool = True, start: float = 0.0,
               seconds: float | None = None) -> np.ndarray:
    """ffmpeg 解碼成 float32；mono 時 shape=(n,)，否則 (n, 2)。"""
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("找不到 ffmpeg")
    cmd = [ff, "-hide_banner", "-loglevel", "error"]
    if start:
        cmd += ["-ss", str(start)]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-i", str(path), "-vn", "-ac", "1" if mono else "2", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype=np.float32).copy()
    return y if mono else y.reshape(-1, 2)


# ---------------------------------------------------------------------------
# DSP 量測（純 numpy）
# ---------------------------------------------------------------------------

BANDS = [("sub_20_60", 20, 60), ("low_60_250", 60, 250), ("lowmid_250_2k", 250, 2000),
         ("high_2k_8k", 2000, 8000), ("air_8k_20k", 8000, 20000)]


def _stft_mag(y: np.ndarray, n_fft: int = 4096, hop: int = 1024) -> np.ndarray:
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    win = np.hanning(n_fft).astype(np.float32)
    n = 1 + (len(y) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    return np.abs(np.fft.rfft(y[idx] * win, axis=1))  # (frames, bins)


def dsp_features(y: np.ndarray, sr: int) -> dict:
    """頻段能量百分比、頻譜重心、RMS/峰值、hi-hat 區（6–16 kHz）的暫態比例。"""
    y = np.asarray(y, dtype=np.float32)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    rms = float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) if len(y) else 0.0
    S = _stft_mag(y)
    P = S ** 2
    freqs = np.fft.rfftfreq(4096, 1 / sr)
    tot = float(P.sum()) + 1e-20
    bands = {name: round(100 * float(P[:, (freqs >= lo) & (freqs < hi)].sum()) / tot, 2) for name, lo, hi in BANDS}
    spec = P.sum(axis=0)
    centroid = float((freqs * spec).sum() / (spec.sum() + 1e-20))
    # hi-hat 區暫態：該頻段能量包絡的正向差分總量 / 包絡總量（打擊樂越突出越大）
    hh = P[:, (freqs >= 6000) & (freqs < 16000)].sum(axis=1)
    flux = np.maximum(np.diff(hh), 0).sum() / (hh.sum() + 1e-20) if len(hh) > 1 else 0.0
    # 短時 RMS 動態範圍（dB，第 95 與第 10 百分位差）
    frame_rms = np.sqrt(P.sum(axis=1) / P.shape[1] + 1e-20)
    db = 20 * np.log10(frame_rms + 1e-12)
    loud = db[db > db.max() - 60] if len(db) else db
    dyn = float(np.percentile(loud, 95) - np.percentile(loud, 10)) if len(loud) else 0.0
    hi_e = bands["high_2k_8k"] + bands["air_8k_20k"]
    return {
        "duration_s": round(len(y) / sr, 3),
        # 亮度：2 kHz 以上相對 250 Hz–2 kHz 的能量比（dB），比百分比更能反映 EQ 調整
        "brightness_db": round(10 * math.log10((hi_e + 1e-4) / (bands["lowmid_250_2k"] + 1e-4)), 1),
        "peak_dbfs": round(20 * math.log10(peak + 1e-12), 2),
        "rms_dbfs": round(20 * math.log10(rms + 1e-12), 2),
        "spectral_centroid_hz": round(centroid, 1),
        "band_energy_pct": bands,
        "hihat_band_pct": round(100 * float(hh.sum()) / tot, 3),
        "hihat_band_transient": round(float(flux), 3),
        "dynamic_range_db": round(dyn, 1),
    }


# ---------------------------------------------------------------------------
# 對齊：DTW 與音符編輯距離對齊（純 numpy）
# ---------------------------------------------------------------------------

def dtw(a: np.ndarray, b: np.ndarray, clip: float = 12.0) -> tuple[float, list[tuple[int, int]]]:
    """一維序列 DTW，cost=min(|a-b|, clip)；回傳 (平均每步成本, 路徑)。"""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return float(clip), []
    C = np.minimum(np.abs(a[:, None] - b[None, :]), clip)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        Ci = C[i - 1]
        prev = D[i - 1]
        row = D[i]
        diag_up = np.minimum(prev[:-1], prev[1:])  # D[i-1,j-1], D[i-1,j]
        for j in range(1, m + 1):
            best = diag_up[j - 1]
            if row[j - 1] < best:
                best = row[j - 1]
            row[j] = Ci[j - 1] + best
    # 回溯
    i, j = n, m
    path = [(i - 1, j - 1)]
    while i > 1 or j > 1:
        cand = []
        if i > 1 and j > 1:
            cand.append((D[i - 1, j - 1], i - 1, j - 1))
        if i > 1:
            cand.append((D[i - 1, j], i - 1, j))
        if j > 1:
            cand.append((D[i, j - 1], i, j - 1))
        _, i, j = min(cand)
        path.append((i - 1, j - 1))
    path.reverse()
    return float(D[n, m] / len(path)), path


def _sub_cost(d: int) -> float:
    d = abs(int(d))
    if d == 0:
        return 0.0
    if d % 12 == 0:
        return 0.45  # 八度誤判（轉譜常見）
    if d <= 2:
        return 0.7
    return 1.0


def align_notes(ref: list[dict], est: list[dict], offset: float = 0.0, gap: float = 0.8,
                time_weight: float = 0.5) -> list[tuple[int | None, int | None]]:
    """Needleman–Wunsch 對齊兩個音符序列（依 onset 排序），cost 含音高與（位移後）時間差。

    回傳配對清單：(ref_idx, est_idx)；ref_idx=None 表示多出來的音、est_idx=None 表示漏音。
    """
    n, m = len(ref), len(est)
    D = np.zeros((n + 1, m + 1))
    D[:, 0] = np.arange(n + 1) * gap
    D[0, :] = np.arange(m + 1) * gap
    T = np.zeros((n + 1, m + 1), dtype=np.int8)  # 0 diag 1 up(漏) 2 left(多)
    T[1:, 0] = 1
    T[0, 1:] = 2
    for i in range(1, n + 1):
        r = ref[i - 1]
        for j in range(1, m + 1):
            e = est[j - 1]
            dt = abs((e["onset"] - offset) - r["onset"])
            c = _sub_cost(e["pitch"] - r["pitch"]) + time_weight * min(1.0, dt)
            opts = (D[i - 1, j - 1] + c, D[i - 1, j] + gap, D[i, j - 1] + gap)
            k = int(np.argmin(opts))
            D[i, j] = opts[k]
            T[i, j] = k
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        k = T[i, j]
        if i > 0 and j > 0 and k == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and (j == 0 or k == 1):
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def skyline(notes: list[dict], min_dur: float = 0.06, merge_s: float = 0.05,
            pitch_range: tuple[int, int] | None = None) -> list[dict]:
    """多聲部音符 → 單旋律線（同時起音取最高音；過短與音域外的音丟掉）。"""
    ns = [n for n in notes if n["end"] - n["onset"] >= min_dur]
    if pitch_range:
        ns = [n for n in ns if pitch_range[0] <= n["pitch"] <= pitch_range[1]]
    ns.sort(key=lambda n: (n["onset"], -n["pitch"]))
    out: list[dict] = []
    for n in ns:
        if out and n["onset"] - out[-1]["onset"] < merge_s:
            if n["pitch"] > out[-1]["pitch"]:
                out[-1] = dict(n)
            continue
        out.append(dict(n))
    return out


def contour(notes: list[dict], hop: float = 0.1) -> np.ndarray:
    """音符 → 每 hop 秒一格的音高序列（休止格省略，讓 DTW 只比旋律形狀）。"""
    if not notes:
        return np.zeros(0)
    t0 = min(n["onset"] for n in notes)
    t1 = max(n["end"] for n in notes)
    grid = np.arange(t0, t1, hop)
    vals = np.full(len(grid), np.nan)
    for n in sorted(notes, key=lambda n: n["pitch"]):  # 高音覆蓋
        vals[(grid >= n["onset"]) & (grid < n["end"])] = n["pitch"]
    return vals[~np.isnan(vals)]


def compare_melody(ref: list[dict], est: list[dict], transpose: int | str = 0,
                   intonation: dict | None = None) -> dict:
    """參考旋律 vs 轉譜旋律：note F1、正確率、走音/漏音/多音清單、DTW 輪廓相似度。

    transpose="auto" 時在 -12..12 半音中挑 F1 最高者（樂器移調、或轉譜整體偏移）。
    intonation：{est_idx: cents偏差}（可選，來自 pyin）。
    """
    if transpose == "auto":
        best = None
        for k in range(-12, 13):
            r = compare_melody(ref, est, transpose=k)
            key = (r["note_f1"], -abs(k))
            if best is None or key > best[0]:
                best = (key, r)
        res = best[1]
        res["transpose_search"] = "auto"
        return res
    k = int(transpose)
    est_t = [dict(e, pitch=e["pitch"] - k) for e in est]
    ref = sorted(ref, key=lambda n: n["onset"])
    est_t = sorted(est_t, key=lambda n: n["onset"])
    # 第一輪不看時間求粗配，估計整體時間位移，再帶時間重配
    pairs = align_notes(ref, est_t, time_weight=0.0)
    d = [est_t[j]["onset"] - ref[i]["onset"] for i, j in pairs
         if i is not None and j is not None and est_t[j]["pitch"] == ref[i]["pitch"]]
    offset = float(np.median(d)) if d else 0.0
    pairs = align_notes(ref, est_t, offset=offset)
    exact, wrong, octave, missing, extra, timing = 0, [], [], [], [], []
    for i, j in pairs:
        if i is not None and j is not None:
            r, e = ref[i], est_t[j]
            dp = e["pitch"] - r["pitch"]
            item = {"t_ref": round(r["onset"], 3), "t_audio": round(e["onset"], 3),
                    "ref": midi_name(r["pitch"]), "heard": midi_name(e["pitch"]), "semitones": int(dp)}
            if dp == 0:
                exact += 1
                timing.append(e["onset"] - offset - r["onset"])
            elif dp % 12 == 0:
                octave.append(item)
            else:
                wrong.append(item)
        elif i is not None:
            missing.append({"t_ref": round(ref[i]["onset"], 3), "ref": midi_name(ref[i]["pitch"])})
        else:
            extra.append({"t_audio": round(est_t[j]["onset"], 3), "heard": midi_name(est_t[j]["pitch"])})
    n_ref, n_est = len(ref), len(est_t)
    prec = exact / n_est if n_est else 0.0
    rec = exact / n_ref if n_ref else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    dcost, _ = dtw(contour(ref), contour(est_t))
    out = {
        "n_ref_notes": n_ref, "n_heard_notes": n_est, "transpose_semitones": k,
        "time_offset_s": round(offset, 3),
        "note_precision": round(prec, 3), "note_recall": round(rec, 3), "note_f1": round(f1, 3),
        "contour_dtw_cost_semitones": round(dcost, 3),
        "contour_similarity": round(max(0.0, 1 - dcost / 12.0), 3),
        "onset_timing_mad_ms": round(1000 * float(np.median(np.abs(timing))), 1) if timing else None,
        "wrong_pitch": wrong, "octave_errors": octave, "missing": missing, "extra": extra,
    }
    if intonation:
        out["intonation_cents"] = intonation
    return out


# ---------------------------------------------------------------------------
# 節奏量測（純 numpy 部分）
# ---------------------------------------------------------------------------

def swing_ratio(onsets: np.ndarray, beats: np.ndarray, lo: float = 0.40, hi: float = 0.85,
                strengths: np.ndarray | None = None) -> dict:
    """每拍之內找「反拍八分音」的相位 p（0=正拍，1=下一拍），swing ratio = p/(1-p)。

    直八分 p≈0.5→1.0；三連音 swing p≈0.667→2.0。取每拍內最強的一個候選，最後取中位數。
    注意：若節拍追蹤抓到的是八分音層級（速度加倍），此量測無意義；十六分音符的 0.75 也會被誤算成 3:1。
    """
    onsets = np.asarray(onsets, float)
    beats = np.asarray(beats, float)
    if strengths is None:
        strengths = np.ones(len(onsets))
    phases = []

    def snap(b: float, T: float) -> float:
        # 節拍追蹤器與 onset 偵測器的時間基準不同（幀解析度、平滑），先把拍點吸到 ±8% 拍長內最近的 onset
        if len(onsets) == 0:
            return b
        k = int(np.argmin(np.abs(onsets - b)))
        return float(onsets[k]) if abs(onsets[k] - b) <= 0.08 * T else b

    for b0, b1 in zip(beats[:-1], beats[1:]):
        T = b1 - b0
        if T <= 0:
            continue
        b0, b1 = snap(b0, T), snap(b1, T)
        T = b1 - b0
        m = (onsets > b0 + lo * T) & (onsets < b0 + hi * T)
        if not m.any():
            continue
        st = np.where(m, strengths, -np.inf)
        k = int(np.argmax(st))
        # 十六分音網格（0.5 與 0.75 都有）時，0.5 那個只要夠強就取它，避免把直的十六分算成 3:1 swing
        ph_all = (onsets - b0) / T
        near_half = m & (np.abs(ph_all - 0.5) < 0.04) & (st >= 0.3 * st[k])
        if near_half.any():
            k = int(np.argmax(np.where(near_half, st, -np.inf)))
        phases.append((onsets[k] - b0) / T)
    if len(phases) < 3:
        return {"swing_ratio": None, "n_beats_used": len(phases), "offbeat_phase_median": None}
    p = float(np.median(phases))
    iqr = float(np.percentile(phases, 75) - np.percentile(phases, 25))
    return {"swing_ratio": round(p / (1 - p), 2), "n_beats_used": len(phases),
            "offbeat_phase_median": round(p, 3), "offbeat_phase_iqr": round(iqr, 3),
            # 反拍相位分散（例如十六分音網格 0.5/0.75 混著出現）時中位數沒有意義
            "reliable": bool(iqr <= 0.08)}


def tempo_stats(beats: np.ndarray) -> dict:
    """由拍點時間算 BPM、速度穩定度（IBI 變異係數）、漂移（BPM/分鐘）。"""
    beats = np.asarray(beats, float)
    if len(beats) < 4:
        return {"bpm": None, "n_beats": int(len(beats))}
    ibi = np.diff(beats)
    med = float(np.median(ibi))
    inl = ibi[np.abs(ibi - med) < 0.2 * med]
    # 用內點 IBI 的平均而非中位數：beat_this 拍點量化在 20 ms 格上，中位數會卡在格點（140→142.9）
    bpm = 60.0 / float(np.mean(inl if len(inl) else ibi))
    local = 60.0 / ibi
    slope = float(np.polyfit(beats[1:], local, 1)[0]) * 60 if len(local) >= 3 else 0.0
    cv = float(np.std(ibi) / np.mean(ibi))
    return {
        "bpm": round(bpm, 1),
        "bpm_half": round(bpm / 2, 1), "bpm_double": round(bpm * 2, 1),
        "n_beats": int(len(beats)),
        "ibi_cv": round(cv, 3),
        "tempo_stability": "穩" if cv < 0.04 else ("略飄" if cv < 0.10 else "不穩/自由速度"),
        "drift_bpm_per_min": round(slope, 2),
        "local_bpm_p10_p90": [round(float(np.percentile(local, 10)), 1), round(float(np.percentile(local, 90)), 1)],
    }


# ---------------------------------------------------------------------------
# 目標描述（brief）解析
# ---------------------------------------------------------------------------

BRIEF_LEXICON = {
    # 關鍵字 -> (類別, essentia jamendo 標籤, CLAP 英文片語)
    "小號": ("instrument", ["trumpet", "brass"], "muted jazz trumpet"),
    "trumpet": ("instrument", ["trumpet", "brass"], "jazz trumpet"),
    "鋼琴": ("instrument", ["piano"], "jazz piano"),
    "piano": ("instrument", ["piano"], "jazz piano"),
    "低音提琴": ("instrument", ["doublebass", "bass"], "upright double bass"),
    "double bass": ("instrument", ["doublebass", "bass"], "upright double bass"),
    "貝斯": ("instrument", ["bass", "doublebass"], "bass"),
    "鼓": ("instrument", ["drums", "percussion"], "brushed drums"),
    "刷子": ("instrument", ["drums"], "brushes on snare drum"),
    "hi-hat": ("instrument", ["drums"], "soft hi-hat"),
    "鐘": ("instrument", ["bell"], "tolling bells"),
    "風鈴": ("instrument", ["bell"], "wind chimes"),
    "鋼片琴": ("instrument", ["bell", "keyboard"], "celesta"),
    "celesta": ("instrument", ["bell", "keyboard"], "celesta"),
    "旁白": ("instrument", ["voice"], "a narrator speaking"),
    "人聲": ("instrument", ["voice"], "voice"),
    "爵士": ("genre", ["jazz", "swing", "lounge"], "jazz"),
    "jazz": ("genre", ["jazz", "swing", "lounge"], "jazz"),
    "ballad": ("mood", ["ballad", "slow", "romantic"], "slow ballad"),
    "慢板": ("mood", ["slow", "calm"], "slow tempo"),
    "慵懶": ("mood", ["relaxing", "calm", "soft"], "lazy and relaxed"),
    "抒情": ("mood", ["romantic", "emotional", "melodic", "ballad"], "lyrical"),
    "寂寥": ("mood", ["melancholic", "sad"], "lonely and melancholic"),
    "憂鬱": ("mood", ["melancholic", "sad"], "melancholic"),
    "詭異": ("mood", ["dark"], "eerie and unsettling"),
    "陰暗": ("mood", ["dark"], "dark"),
    "氛圍": ("genre", ["ambient", "atmospheric"], "ambient"),
}

# 通用反例：若這些分數高過目標描述，就是方向錯了
ANTI_PROMPTS = ["fast electronic dance music with drum machine", "heavy metal with distorted electric guitars",
                "upbeat pop song with vocals", "hip hop beat with rap"]


def parse_brief(brief: str) -> dict:
    """從中文 / 英文目標描述抓出：目標 BPM、樂器、情緒、曲風與 CLAP 用的英文句子。"""
    b = brief.lower()
    out = {"instruments": {}, "moods": set(), "genres": set(), "phrases": [], "target_bpm": None,
           "bpm_range": None}
    m = re.search(r"(\d{2,3})\s*(?:bpm|拍)", b)
    if m:
        out["target_bpm"] = float(m.group(1))
    for kw, (cat, tags, phrase) in BRIEF_LEXICON.items():
        if kw.lower() in b:
            if cat == "instrument":
                out["instruments"][kw] = tags
            elif cat == "mood":
                out["moods"].update(tags)
            else:
                out["genres"].update(tags)
            if phrase not in out["phrases"]:
                out["phrases"].append(phrase)
    if out["target_bpm"] is None and any(k in b for k in ("ballad", "慢板", "慢")):
        out["bpm_range"] = (48.0, 72.0)
    elif out["target_bpm"] is not None:
        t = out["target_bpm"]
        out["bpm_range"] = (t * 0.95, t * 1.05)
    out["moods"] = sorted(out["moods"])
    out["genres"] = sorted(out["genres"])
    out["clap_prompt"] = ", ".join(out["phrases"]) if out["phrases"] else brief
    return out


# ---------------------------------------------------------------------------
# 綜合評語（純規則，可測）
# ---------------------------------------------------------------------------

def build_critique(brief: dict, res: dict) -> dict:
    """依各層結果產出 {matches, mismatches, suggestions, confidence_notes}。所有門檻皆為經驗值。"""
    good, bad, sug, notes = [], [], [], []
    dsp = res.get("dsp") or {}
    rhythm = res.get("rhythm") or {}
    ess = res.get("essentia") or {}
    clap = res.get("clap") or {}
    aes = res.get("aesthetics") or {}
    stems = res.get("stems") or {}

    # --- 速度 ---
    bpm = (rhythm.get("tempo") or {}).get("bpm")
    rng = brief.get("bpm_range")
    if bpm and rng:
        cands = [bpm, bpm / 2, bpm * 2]
        inside = [c for c in cands if rng[0] <= c <= rng[1]]
        tgt = brief.get("target_bpm") or sum(rng) / 2
        dense = (rhythm.get("onset_rate_per_s") or 0) > 5.0
        if bpm in inside or (inside and not (dense and inside[0] < bpm)):
            use = bpm if bpm in inside else inside[0]
            extra = "" if use == bpm else f"（節拍追蹤給 {bpm:.0f}，以 {'半' if use < bpm else '倍'}速解讀）"
            good.append(f"速度約 {use:.0f} BPM，在目標範圍 {rng[0]:.0f}–{rng[1]:.0f} 內{extra}")
        elif inside:
            bad.append(f"節拍追蹤給 {bpm:.0f} BPM，起音密度每秒 {rhythm.get('onset_rate_per_s')} 個，"
                       f"不像半速 {bpm / 2:.0f} 的慢板，而是 {bpm:.0f} BPM 的快節奏")
            sug.append(f"減少密集的十六分音/打擊點，讓律動落在 {sum(rng) / 2:.0f} BPM 附近")
        else:
            near = min(cands, key=lambda c: abs(c - tgt))
            direction = "高於" if near > tgt else "低於"
            bad.append(f"速度約 {near:.0f} BPM，{direction}目標 {rng[0]:.0f}–{rng[1]:.0f}")
            sug.append(f"把速度調到約 {tgt:.0f} BPM（目前 {near:.0f}）")
    stab = (rhythm.get("tempo") or {}).get("ibi_cv")
    if stab is not None and stab >= 0.10:
        notes.append(f"拍點間隔變異係數 {stab}：速度自由或節拍追蹤不可靠（旁白/無鼓音樂常見）")

    # --- swing ---
    sw = (rhythm.get("swing") or {}).get("swing_ratio")
    wants_swing = any(g in ("jazz", "swing") for g in brief.get("genres", []))
    if wants_swing and sw is not None:
        if sw < 1.25:
            bad.append(f"反拍八分音幾乎是直的（swing ratio {sw}），聽起來不像爵士搖擺")
            sug.append("hi-hat / ride / 鋼琴反拍往後推，swing ratio 目標約 1.6–2.2（ballad 可 1.5 左右）")
        elif sw > 2.8:
            bad.append(f"swing ratio {sw} 過大（接近附點八分），可能太頓")
        else:
            good.append(f"有搖擺感（swing ratio {sw}）")

    # --- 頻段 / 亮度 ---
    be = dsp.get("band_energy_pct") or {}
    hi = be.get("high_2k_8k", 0) + be.get("air_8k_20k", 0)
    cen = dsp.get("spectral_centroid_hz")
    warm = any(m in brief.get("moods", []) for m in ("relaxing", "calm", "soft", "melancholic", "romantic"))
    bdb = dsp.get("brightness_db")
    if cen is not None and warm:
        # 門檻依 5 個樣本校準（report.md）：暖色 jazz 渲染 ≈ -15 dB、刻意調亮版 -7.5 dB、EDM +4.5 dB
        if cen > 2500 or hi > 20 or (bdb is not None and bdb > -8):
            bad.append(f"整體偏亮（頻譜重心 {cen:.0f} Hz、2 kHz 以上占 {hi:.1f}%、亮度 {bdb} dB），不像慵懶暖色調")
            sug.append("主匯流排或最亮的聲部在 2 kHz 以上做 high-shelf −2~−4 dB，或降低 hi-hat / 鈸的量")
        elif cen < 250:
            bad.append(f"整體太悶（頻譜重心 {cen:.0f} Hz）")
            sug.append("檢查是否低頻過多或高頻被濾掉；可在 3–5 kHz 補一點空氣感")
        else:
            good.append(f"音色偏暖（頻譜重心 {cen:.0f} Hz、2 kHz 以上占 {hi:.1f}%）")
    if be.get("low_60_250", 0) + be.get("sub_20_60", 0) > 60:
        bad.append(f"低頻占比 {be.get('low_60_250', 0) + be.get('sub_20_60', 0):.0f}% 過重，可能糊")
        sug.append("低音提琴或鋼琴左手 150–250 Hz 減 2–3 dB，或在非低音聲部加 HPF 100 Hz")

    # --- 分軌（有 --stems 時）---
    if stems:
        levels = {k: v.get("rms_dbfs") for k, v in stems.items() if v.get("rms_dbfs") is not None}
        lead = next((k for k in ("trumpet", "lead", "melody") if k in levels), None)
        for k in ("hihat", "brush", "drums"):
            if k in levels and lead and levels[k] > levels[lead] - 8:
                bad.append(f"{k} 太前面（比 {lead} 只低 {levels[lead] - levels[k]:.1f} dB）")
                sug.append(f"{k} 降 {max(2, 10 - (levels[lead] - levels[k])):.0f} dB 左右，讓它退到 {lead} 後方 10 dB")
        if lead:
            lb = stems[lead].get("band_energy_pct", {})
            lh = lb.get("high_2k_8k", 0) + lb.get("air_8k_20k", 0)
            if lh > 25 or (stems[lead].get("brightness_db") or -99) > -10:
                bad.append(f"{lead} 高頻太亮（2 kHz 以上占 {lh:.0f}%）")
                sug.append(f"{lead} 降 2 kHz 以上 3 dB（high-shelf）或 LPF 7 kHz，Chet Baker 的音是圓暖的")
            elif lh < 1 and "trumpet" in lead:
                notes.append(f"{lead} 2 kHz 以上只占 {lh:.1f}%，可能過悶，缺少銅管的邊緣")
        if "bass" in levels and lead and levels["bass"] < levels[lead] - 15:
            bad.append(f"低音提琴太小聲（比 {lead} 低 {levels[lead] - levels['bass']:.0f} dB）")
            sug.append("bass 加 3–4 dB，或在 700 Hz–1 kHz 補一點撥弦顆粒讓它在小喇叭上聽得到")

    # --- 與上一版比較（--baseline）---
    for item in res.get("baseline_diff") or []:
        name, key, delta = item["name"], item["metric"], item["delta"]
        if key == "brightness_db" and abs(delta) >= 3:
            (bad if delta > 0 else notes).append(f"{name} 高頻比上一版{'亮' if delta > 0 else '暗'} {abs(delta):.1f} dB")
            if delta > 0:
                sug.append(f"{name} 在 2 kHz 以上 high-shelf −{min(12, round(delta)):.0f} dB，回到上一版的亮度")
        elif key == "rms_dbfs" and abs(delta) >= 3:
            notes.append(f"{name} 音量比上一版{'大' if delta > 0 else '小'} {abs(delta):.1f} dB")

    # --- Essentia 樂器 / 情緒 / 曲風 ---
    inst = ess.get("instrument") or {}
    probes = (res.get("llm") or {}).get("probes") or {}
    for kw, tags in (brief.get("instruments") or {}).items():
        p = max((inst.get(t, 0.0) for t in tags), default=None) if inst else None
        llm_yes = (probes.get(kw) or {}).get("yes")
        ess_yes = None if p is None else p >= 0.15
        src = []
        if p is not None:
            src.append(f"Essentia {'/'.join(tags)} {p:.2f}")
        if llm_yes is not None:
            src.append(f"LLM 是非題 {'有' if llm_yes else '沒有'}")
        if not src:
            continue
        votes = [v for v in (ess_yes, llm_yes) if v is not None]
        if all(votes):
            good.append(f"聽得到「{kw}」（{'；'.join(src)}）")
        elif not any(votes):
            bad.append(f"聽不到「{kw}」（{'；'.join(src)}）")
            sug.append(f"「{kw}」存在感不足：加大音量或讓音色更有特徵")
        else:
            notes.append(f"「{kw}」兩個模型意見不一（{'；'.join(src)}），需以分軌或人耳確認")
    for kw, pr in probes.items():
        if not pr.get("expected") and pr.get("yes"):
            bad.append(f"LLM 是非題說有「{kw}」，不在目標編制內（LLM 偶有誤報，請對照 Essentia/CLAP）")
    if inst:
        for t in ("drummachine", "synthesizer", "electricguitar", "beat"):
            if inst.get(t, 0) >= 0.3 and not any(t in tags for tags in (brief.get("instruments") or {}).values()):
                bad.append(f"聽起來像有 {t}（{inst[t]:.2f}），不在目標編制內")
    mood = ess.get("mood") or {}
    if mood and brief.get("moods"):
        # mtg-jamendo 情緒分數普遍很低（多在 0.05–0.15），用名次而非絕對門檻：目標情緒進前 8 名算吻合
        top = sorted(mood.items(), key=lambda kv: -kv[1])[:8]
        inside = [(k, v) for k, v in top if k in brief["moods"]]
        if inside:
            good.append("情緒標籤吻合（前 8 名內）：" + ", ".join(f"{k} {v:.2f}" for k, v in inside))
        else:
            bad.append("情緒標籤不吻合，模型聽到的前 5 名是：" + ", ".join(f"{k} {v:.2f}" for k, v in top[:5]))
    genre = ess.get("genre_discogs400_top") or []
    if genre and brief.get("genres"):
        want = brief["genres"]
        jz = [g for g in genre[:5] if any(w in g[0].lower() for w in want)]
        if jz:
            good.append(f"Discogs 曲風前五含 {jz[0][0]}（{jz[0][1]:.2f}）")
        else:
            bad.append("Discogs 曲風前五沒有目標曲風：" + ", ".join(f"{g} {p:.2f}" for g, p in genre[:3]))

    # --- CLAP ---
    if clap.get("brief_vs_anti"):
        m = clap["brief_vs_anti"]
        if m["margin"] > 0:
            good.append(f"CLAP：目標描述相似度 {m['brief']:.3f} 高於反例最高 {m['anti_max']:.3f}")
        else:
            bad.append(f"CLAP：更像「{m['anti_best']}」（{m['anti_max']:.3f}）而不是目標描述（{m['brief']:.3f}）")

    # --- 美學分數 ---
    if aes:
        pq, ce = aes.get("PQ"), aes.get("CE")
        if pq is not None and pq < 6.0:
            bad.append(f"製作品質分數 PQ={pq:.2f} 偏低（專業錄音通常 > 7）")
            sug.append("檢查底噪、失真、取樣音色的機械感；加真實房間殘響與力度變化")
        elif pq is not None:
            good.append(f"製作品質 PQ={pq:.2f}")
        if ce is not None and ce < 5.0:
            notes.append(f"內容享受度 CE={ce:.2f} 偏低")

    notes.append("門檻皆為經驗值；LLM 敘述僅供參考，與量測衝突時以量測為準。")
    return {"matches": good, "mismatches": bad, "suggestions": sug, "notes": notes}


def critique_markdown(title: str, brief_text: str, crit: dict, llm: str | None = None) -> str:
    lines = [f"# 聆聽評語：{title}", "", f"目標：{brief_text}", "", "## 符合目標之處"]
    lines += [f"- {x}" for x in crit["matches"]] or ["- （無）"]
    lines += ["", "## 不符之處"] + ([f"- {x}" for x in crit["mismatches"]] or ["- （無）"])
    lines += ["", "## 具體調整建議"] + ([f"- {x}" for x in crit["suggestions"]] or ["- （無）"])
    if llm:
        lines += ["", "## 音訊語言模型的看法（可信度較低，僅供參考）", "", llm.strip()]
    lines += ["", "## 備註"] + [f"- {x}" for x in crit["notes"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 合成對照音檔（純 numpy，驗證與測試用）
# ---------------------------------------------------------------------------

def _env(n: int, sr: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / sr
    return np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-t / decay)


def synth_edm(sr: int = 44100, seconds: float = 30.0, bpm: float = 140.0, seed: int = 0) -> np.ndarray:
    """快節奏電子舞曲：四拍大鼓、拍手、16 分閉合 hi-hat、鋸齒 bass、方波 lead（明顯不符 ballad）。"""
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    y = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    t = np.arange(int(0.25 * sr)) / sr
    kick = np.sin(2 * np.pi * (50 + 120 * np.exp(-t * 30)) * t) * np.exp(-t * 12)
    clap = rng.standard_normal(int(0.15 * sr)) * _env(int(0.15 * sr), sr, 0.001, 0.04)
    hat = np.diff(rng.standard_normal(int(0.05 * sr) + 1)) * _env(int(0.05 * sr), sr, 0.0005, 0.012)
    bass_notes = [36, 36, 39, 41]
    lead_notes = [72, 75, 79, 77, 75, 72, 70, 72]
    k = 0
    while k * beat / 4 < seconds:
        pos = int(k * beat / 4 * sr)
        if k % 4 == 0:
            seg = kick[: n - pos]
            y[pos: pos + len(seg)] += 0.9 * seg
        if k % 8 == 4:
            seg = clap[: n - pos]
            y[pos: pos + len(seg)] += 0.5 * seg
        seg = hat[: n - pos]
        y[pos: pos + len(seg)] += 0.35 * seg
        if k % 2 == 1:  # 反拍 bass
            f = 440 * 2 ** ((bass_notes[(k // 16) % 4] - 69) / 12)
            L = min(int(beat / 2 * sr), n - pos)
            tt = np.arange(L) / sr
            saw = 2 * ((f * tt) % 1) - 1
            y[pos: pos + L] += 0.3 * saw * _env(L, sr, 0.002, 0.12)
        if k % 4 == 2:
            f = 440 * 2 ** ((lead_notes[(k // 4) % 8] - 69) / 12)
            L = min(int(beat / 2 * sr), n - pos)
            tt = np.arange(L) / sr
            sq = np.sign(np.sin(2 * np.pi * f * tt))
            y[pos: pos + L] += 0.15 * sq * _env(L, sr, 0.002, 0.2)
        k += 1
    return (0.8 * y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


def synth_swing_hats(sr: int = 22050, seconds: float = 20.0, bpm: float = 60.0, ratio: float = 2.0,
                     seed: int = 0) -> np.ndarray:
    """只有 hi-hat 的搖擺節奏（正拍 + 以 ratio 推後的反拍），測 swing ratio 用。"""
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    y = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    hat = np.diff(rng.standard_normal(int(0.04 * sr) + 1)) * _env(int(0.04 * sr), sr, 0.0005, 0.01)
    p = ratio / (1 + ratio)
    b = 0
    while b * beat < seconds:
        for ph, amp in ((0.0, 1.0), (p, 0.6)):
            pos = int((b + ph) * beat * sr)
            if pos < n:
                seg = hat[: n - pos]
                y[pos: pos + len(seg)] += amp * seg
        b += 1
    return y


def synth_melody(notes: list[dict], sr: int = 22050, tail: float = 0.5) -> np.ndarray:
    """音符 → 簡單加法合成的單音旋律（泛音衰減，像柔和的木管/弱音小號）。"""
    if not notes:
        return np.zeros(int(sr * tail), np.float32)
    n = int(sr * (max(x["end"] for x in notes) + tail))
    y = np.zeros(n, np.float32)
    for x in notes:
        f = 440 * 2 ** ((x["pitch"] - 69) / 12)
        s = int(x["onset"] * sr)
        L = min(int((x["end"] - x["onset"]) * sr), n - s)
        t = np.arange(L) / sr
        tone = sum(np.sin(2 * np.pi * f * h * t) / h ** 1.5 for h in range(1, 6))
        env = np.minimum(1, t / 0.02) * np.minimum(1, (L / sr - t) / 0.05)
        y[s: s + L] += (0.3 * tone * env).astype(np.float32)
    return y


def write_wav(path: str | Path, y: np.ndarray, sr: int) -> None:
    import wave
    y = np.clip(np.asarray(y, np.float32), -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())


# ---------------------------------------------------------------------------
# MIDI 讀取（重用 jazz_render 的 SMF 解析，不依賴 mido）
# ---------------------------------------------------------------------------

def read_midi_notes(path: str | Path, track: str | int | None = None) -> list[dict]:
    """讀 MIDI → [{pitch, onset, end, velocity}]（秒）。track=None 時合併所有軌。"""
    import pretty_midi  # ~/.venv-listen 內已安裝
    pm = pretty_midi.PrettyMIDI(str(path))
    insts = pm.instruments
    if track is not None:
        if isinstance(track, int) or str(track).isdigit():
            insts = [insts[int(track)]]
        else:
            insts = [i for i in insts if str(track).lower() in (i.name or "").lower()] or insts
    return sorted([{"pitch": n.pitch, "onset": float(n.start), "end": float(n.end), "velocity": n.velocity}
                   for i in insts if not i.is_drum for n in i.notes], key=lambda d: d["onset"])


# ---------------------------------------------------------------------------
# 模型層（延遲 import；只在 WSL venv 可用）
# ---------------------------------------------------------------------------

def _gpu_free_gb() -> float:
    try:
        import torch
        if not torch.cuda.is_available():
            return 0.0
        free, _ = torch.cuda.mem_get_info()
        return free / 2 ** 30
    except Exception:
        return 0.0


class AudioLLM:
    """Qwen2.5-Omni-7B（thinker，4-bit）或 Qwen2-Audio-7B-Instruct（4-bit）。"""

    # 官方預設的「virtual human」system prompt 會讓模型進入閒聊模式，對音樂常回「我聽不到音訊」再憑空猜；
    # 實測不給 system prompt 時才會老實描述（見 report.md）。
    SYSTEM_OMNI: str | None = None

    def __init__(self, model: str = "omni", device: str = "auto"):
        import torch
        from transformers import BitsAndBytesConfig
        self.kind = model
        self.torch = torch
        root = DEFAULT_MODELS / ("Qwen2.5-Omni-7B" if model == "omni" else "Qwen2-Audio-7B-Instruct")
        if not root.exists():
            raise FileNotFoundError(f"模型不在：{root}")
        use_gpu = device == "cuda" or (device == "auto" and _gpu_free_gb() > 10.0)
        kw = {}
        if use_gpu:
            kw = dict(quantization_config=BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                llm_int8_skip_modules=["audio_tower", "lm_head", "multi_modal_projector"]),
                device_map="cuda:0", dtype=torch.bfloat16)
        else:
            kw = dict(device_map="cpu", dtype=torch.bfloat16)
        self.device = "cuda:0" if use_gpu else "cpu"
        if model == "omni":
            from transformers import Qwen2_5OmniProcessor, Qwen2_5OmniThinkerForConditionalGeneration
            self.proc = Qwen2_5OmniProcessor.from_pretrained(root)
            self.model = Qwen2_5OmniThinkerForConditionalGeneration.from_pretrained(root, **kw)
        else:
            from transformers import AutoProcessor, Qwen2AudioForConditionalGeneration
            self.proc = AutoProcessor.from_pretrained(root)
            self.model = Qwen2AudioForConditionalGeneration.from_pretrained(root, **kw)
        self.model.eval()

    def ask(self, y16k: np.ndarray, question: str, max_new_tokens: int = 400) -> str:
        torch = self.torch
        if self.kind == "omni":
            msgs = [{"role": "user", "content": [{"type": "audio", "audio": "in.wav"},
                                                 {"type": "text", "text": question}]}]
            if self.SYSTEM_OMNI:
                msgs.insert(0, {"role": "system", "content": [{"type": "text", "text": self.SYSTEM_OMNI}]})
            text = self.proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
            inputs = self.proc(text=text, audio=[y16k], return_tensors="pt", padding=True, use_audio_in_video=False)
        else:
            conv = [{"role": "user", "content": [{"type": "audio", "audio_url": "in.wav"},
                                                 {"type": "text", "text": question}]}]
            text = self.proc.apply_chat_template(conv, add_generation_prompt=True, tokenize=False)
            inputs = self.proc(text=text, audio=[y16k], sampling_rate=16000, return_tensors="pt", padding=True)
        inputs = inputs.to(self.device)
        for k, v in list(inputs.items()):
            if hasattr(v, "dtype") and v.dtype == torch.float32:
                inputs[k] = v.to(torch.bfloat16)
        tok = self.proc.tokenizer
        eos = [i for i in (tok.convert_tokens_to_ids("<|im_end|>"), tok.convert_tokens_to_ids("<|endoftext|>"))
               if isinstance(i, int) and i >= 0]
        with torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                      eos_token_id=eos, pad_token_id=eos[-1], repetition_penalty=1.05)
        gen = out[:, inputs["input_ids"].shape[1]:]
        txt = self.proc.batch_decode(gen, skip_special_tokens=True)[0].strip()
        return re.split(r"\n\s*Human\s*[:：]?", txt)[0].strip()  # 保險：切掉自問自答的續寫


DESCRIBE_PROMPT = ("Describe this audio in one paragraph: the instruments or sound sources, genre, mood, "
                   "tempo, and the mix (brightness, balance, reverb, noise). If there is speech, say the language.")


def normalize_rms(y: np.ndarray, target_dbfs: float = -20.0, peak_max: float = 0.98) -> np.ndarray:
    """RMS 拉到 target（安靜的 BGM 常在 -30 LUFS 以下，LLM 會說「聽不到」），峰值不超過 peak_max。"""
    rms = float(np.sqrt(np.mean(np.asarray(y, np.float64) ** 2)))
    if rms < 1e-6:
        return y
    g = 10 ** (target_dbfs / 20) / rms
    pk = float(np.max(np.abs(y))) * g
    if pk > peak_max:
        g *= peak_max / pk
    return (y * g).astype(np.float32)


def llm_windows(path: str, start: float, seconds: float, window: float = 30.0) -> list[tuple[float, np.ndarray]]:
    y = normalize_rms(load_audio(path, sr=16000, start=start, seconds=seconds))
    step = int(window * 16000)
    return [(start + i / 16000, y[i: i + step]) for i in range(0, max(len(y), 1), step) if len(y[i: i + step]) > 16000]


def essentia_predict(path: str, models: Path = DEFAULT_ESSENTIA) -> dict:
    """在子行程（隱藏 GPU）跑 Essentia；回傳 instrument / mood / genre 機率與 discogs400 前 10。"""
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="", TF_CPP_MIN_LOG_LEVEL="3")
    r = subprocess.run([sys.executable, __file__, "_essentia", str(path), "--models", str(models)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError("essentia 失敗：" + r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def _essentia_child(path: str, models: Path) -> dict:
    from essentia.standard import MonoLoader, TensorflowPredict2D, TensorflowPredictEffnetDiscogs
    audio = MonoLoader(filename=str(path), sampleRate=16000, resampleQuality=4)()
    emb = TensorflowPredictEffnetDiscogs(graphFilename=str(models / "discogs-effnet-bs64-1.pb"),
                                         output="PartitionedCall:1")(audio)
    out = {}
    g = json.loads((models / "genre_discogs400-discogs-effnet-1.json").read_text())
    pred = TensorflowPredict2D(graphFilename=str(models / "genre_discogs400-discogs-effnet-1.pb"),
                               input="serving_default_model_Placeholder", output="PartitionedCall:0")(emb)
    p = pred.mean(axis=0)
    out["genre_discogs400_top"] = [(g["classes"][i], round(float(p[i]), 3)) for i in np.argsort(-p)[:10]]
    for key, name in (("instrument", "mtg_jamendo_instrument"), ("mood", "mtg_jamendo_moodtheme"),
                      ("genre", "mtg_jamendo_genre")):
        meta = json.loads((models / f"{name}-discogs-effnet-1.json").read_text())
        pr = TensorflowPredict2D(graphFilename=str(models / f"{name}-discogs-effnet-1.pb"),
                                 input="model/Placeholder", output="model/Sigmoid")(emb).mean(axis=0)
        out[key] = {c: round(float(v), 3) for c, v in zip(meta["classes"], pr)}
    return out


_CLAP = None


def _load_clap():
    """官方 laion_clap + music_audioset_epoch_15_esc_90.14.pt（HTSAT-base）。

    註：transformers 5.x 的 ClapModel 載 laion/larger_clap_music 時文字塔壞掉（任兩句 cos≈0.999），故不用。
    """
    global _CLAP
    if _CLAP is None:
        os.environ.setdefault("HF_HOME", str(DEFAULT_MODELS / "hf_home"))
        import laion_clap
        import torch
        ckpt = DEFAULT_MODELS / "laion_clap" / "music_audioset_epoch_15_esc_90.14.pt"
        if not ckpt.exists():
            raise FileNotFoundError(f"CLAP 權重不在：{ckpt}")
        m = laion_clap.CLAP_Module(enable_fusion=False, amodel="HTSAT-base", device="cpu")
        sd = torch.load(ckpt, map_location="cpu", weights_only=False)
        sd = sd.get("state_dict", sd)
        sd = {k[len("module."):] if k.startswith("module.") else k: v for k, v in sd.items()}
        sd = {k: v for k, v in sd.items() if not k.endswith("position_ids")}
        missing, unexpected = m.model.load_state_dict(sd, strict=False)
        if [k for k in missing if "position_ids" not in k]:
            raise RuntimeError(f"CLAP 權重缺鍵：{missing[:5]}")
        m.eval()
        _CLAP = m
    return _CLAP


def clap_similarity(path: str, prompts: list[str], window: float = 10.0) -> dict:
    """LAION-CLAP：音檔切 10 秒窗、平均 embedding，與每句 prompt 算 cosine（-1..1，實務上約 -0.1..0.6）。"""
    import torch
    m = _load_clap()
    y = load_audio(path, sr=48000)
    step = int(window * 48000)
    chunks = [y[i: i + step] for i in range(0, len(y), step) if len(y[i: i + step]) > 48000 * 2] or [y[:step]]
    chunks = np.stack([np.pad(c, (0, step - len(c))) for c in chunks]).astype(np.float32)
    with torch.inference_mode():
        ae = m.get_audio_embedding_from_data(x=chunks, use_tensor=False)
        te = m.get_text_embedding(prompts, use_tensor=False)
    ae = ae / np.linalg.norm(ae, axis=1, keepdims=True)
    a = ae.mean(0)
    a = a / np.linalg.norm(a)
    te = te / np.linalg.norm(te, axis=1, keepdims=True)
    return {p: round(float(s), 4) for p, s in zip(prompts, te @ a)}


def aesthetics(path: str) -> dict:
    """Meta audiobox-aesthetics：CE 內容享受、CU 內容實用、PC 製作複雜度、PQ 製作品質（約 1–10）。

    直接餵 tensor（torchaudio 2.9+ 的 load 需要 torchcodec，繞開）。
    """
    os.environ.setdefault("HF_HOME", str(DEFAULT_MODELS / "hf_home"))
    import torch
    from audiobox_aesthetics.infer import initialize_predictor
    y = load_audio(path, sr=48000)
    pred = initialize_predictor()
    r = pred.forward([{"path": torch.from_numpy(y)[None, :], "sample_rate": 48000}])[0]
    del pred
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {k: round(float(v), 3) for k, v in r.items()}


def transcribe(path: str) -> list[dict]:
    """basic-pitch（ONNX 模型）→ 音符清單。"""
    from basic_pitch import ICASSP_2022_MODEL_PATH, FilenameSuffix, build_icassp_2022_model_path
    from basic_pitch.inference import predict
    try:
        model_path = build_icassp_2022_model_path(FilenameSuffix.onnx)
    except Exception:
        model_path = ICASSP_2022_MODEL_PATH
    import tempfile
    y = load_audio(path, sr=22050)
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"
        write_wav(wav, y, 22050)
        _, pm, _ = predict(str(wav), model_path)
    return sorted([{"pitch": n.pitch, "onset": float(n.start), "end": float(n.end), "velocity": n.velocity}
                   for i in pm.instruments for n in i.notes], key=lambda d: d["onset"])


def intonation_cents(path: str, pairs_ref_est: list[tuple[dict, dict]], offset_pitch: int = 0) -> dict:
    """pyin 取 f0，對每個配對音算中位數音分偏差（只對單音軌有意義）。"""
    import librosa
    y = load_audio(path, sr=22050)
    lo = min(r["pitch"] for r, _ in pairs_ref_est) + offset_pitch - 2
    hi = max(r["pitch"] for r, _ in pairs_ref_est) + offset_pitch + 2
    f0, vflag, _ = librosa.pyin(y, fmin=librosa.midi_to_hz(lo), fmax=librosa.midi_to_hz(hi), sr=22050,
                                frame_length=2048, hop_length=256)
    times = librosa.times_like(f0, sr=22050, hop_length=256)
    res = []
    for r, e in pairs_ref_est:
        a, b = e["onset"] + 0.3 * (e["end"] - e["onset"]), e["onset"] + 0.8 * (e["end"] - e["onset"])
        m = (times >= a) & (times <= b) & vflag & ~np.isnan(f0)
        if m.sum() < 3:
            continue
        cents = 1200 * np.log2(np.median(f0[m]) / librosa.midi_to_hz(r["pitch"] + offset_pitch))
        res.append({"t_audio": round(e["onset"], 2), "ref": midi_name(r["pitch"]), "cents": round(float(cents), 1)})
    bad = [x for x in res if abs(x["cents"]) > 25]
    return {"n_measured": len(res), "median_abs_cents": round(float(np.median([abs(x["cents"]) for x in res])), 1)
            if res else None, "out_of_tune_gt25c": bad}


def beat_track(path: str) -> dict:
    """beat_this（若可用）否則 librosa；另外用 hi-hat 區 onset 算 swing。"""
    import librosa
    y = load_audio(path, sr=22050)
    engine = "librosa"
    downbeats = []
    try:
        from beat_this.inference import File2Beats
        dev = "cuda" if _gpu_free_gb() > 2 else "cpu"
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "a.wav"
            write_wav(wav, y, 22050)
            beats, downbeats = File2Beats(checkpoint_path="final0", device=dev, dbn=False)(str(wav))
        engine = "beat_this"
    except Exception as ex:  # noqa: BLE001
        engine = f"librosa（beat_this 失敗：{type(ex).__name__}）"
        _, beats = librosa.beat.beat_track(y=y, sr=22050, units="time")
    beats = np.asarray(beats, float)
    # hi-hat / 反拍偵測：高頻 onset envelope
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=256))
    freqs = librosa.fft_frequencies(sr=22050, n_fft=1024)
    hf = S[freqs >= 4000]
    env = np.maximum(0, np.diff(np.log1p(hf * 50), axis=1)).sum(axis=0)
    env = np.concatenate([[0], env])
    on = librosa.onset.onset_detect(onset_envelope=env, sr=22050, hop_length=256, units="frames")
    on_t = librosa.frames_to_time(on, sr=22050, hop_length=256)
    strength = env[on] if len(on) else np.zeros(0)
    # 全頻 onset 也算一次（鋼琴 / 小號反拍）
    on2 = librosa.onset.onset_detect(y=y, sr=22050, units="time")
    sw = swing_ratio(on_t, beats, strengths=strength)
    sw_note = None
    if sw["swing_ratio"] is None and len(beats) >= 8:
        # 追蹤器可能抓成倍速（拍點落在八分音上）：改用隔一拍的拍點（兩種相位取可用拍數多者）
        cands = [swing_ratio(on_t, beats[i::2], strengths=strength) for i in (0, 1)]
        best = max(cands, key=lambda r: r["n_beats_used"])
        if best["swing_ratio"] is not None:
            sw, sw_note = best, "拍點疑似倍速，swing 以半速拍點計算"
    fb = swing_ratio(on2, beats)
    # 採用順序：高頻帶（hi-hat/ride）可靠 → 全頻可靠 → 都不可靠則不給數字
    chosen = next((r for r in (sw, fb) if r["swing_ratio"] is not None and r["reliable"]),
                  {"swing_ratio": None, "reliable": False, "n_beats_used": 0})
    ts = tempo_stats(beats)
    if chosen["swing_ratio"] is not None and (ts.get("ibi_cv") or 0) >= 0.10:
        chosen = {"swing_ratio": None, "reliable": False, "n_beats_used": 0}
        sw_note = (sw_note or "") + "；拍點不穩，swing 不採用"
    elif chosen["swing_ratio"] is None and (sw["swing_ratio"] or fb["swing_ratio"]):
        sw_note = (sw_note or "") + "；反拍相位分散，swing 不可靠（可能是十六分音網格或自由速度）"
    return {
        "engine": engine,
        "tempo": ts,
        "beats_head": [round(float(b), 2) for b in beats[:16]],
        "n_downbeats": int(len(downbeats)),
        "beats_per_bar_est": round(len(beats) / len(downbeats), 2) if len(downbeats) else None,
        "swing": chosen,
        "swing_note": sw_note,
        "swing_hihat_band": sw,
        "swing_fullband": fb,
        "onset_rate_per_s": round(len(on2) / (len(y) / 22050), 2),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _to_wsl_path(p: str) -> str:
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", p)
    if m:
        return f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/")
    return p.replace("\\", "/")


def _maybe_reexec_in_wsl(argv: list[str]) -> None:
    """Windows 上缺模型依賴時，轉到 WSL venv 執行同一條指令（路徑自動轉換）。"""
    if os.name != "nt" or os.environ.get("LISTEN_NO_WSL"):
        return
    if argv and argv[0] in ("dsp", "synth-controls", "licenses"):
        return
    try:
        import torch  # noqa: F401
        import librosa  # noqa: F401
        return
    except ImportError:
        pass
    conv = []
    for a in argv:
        conv.append(_to_wsl_path(a) if re.match(r"^[A-Za-z]:[\\/]", a) or os.path.exists(a) else a)
    cmd = " ".join(["cd", _q(_to_wsl_path(os.getcwd())), "&&", WSL_PY, _q(_to_wsl_path(__file__))] + [_q(a) for a in conv])
    r = subprocess.run(["wsl", "-e", "bash", "-lc", cmd])  # -e：繞過預設 shell（fish）
    sys.exit(r.returncode)


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _emit(obj: dict, out: str | None) -> None:
    txt = json.dumps(obj, ensure_ascii=False, indent=1, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
    if out:
        Path(out).write_text(txt, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
    print(txt)


def cmd_describe(a) -> dict:
    llm = AudioLLM(a.model)
    outs = []
    for t0, seg in llm_windows(a.audio, a.start, a.seconds, a.window):
        outs.append({"start_s": round(t0, 1), "text": llm.ask(seg, a.prompt or DESCRIBE_PROMPT)})
    return {"audio": a.audio, "model": a.model, "device": llm.device, "windows": outs}


def cmd_ask(a) -> dict:
    llm = AudioLLM(a.model)
    outs = [{"start_s": round(t0, 1), "answer": llm.ask(seg, a.question)}
            for t0, seg in llm_windows(a.audio, a.start, a.seconds, a.window)]
    return {"audio": a.audio, "model": a.model, "question": a.question, "windows": outs}


DEFAULT_PROMPTS = [
    "slow melancholic jazz ballad with muted trumpet, piano, upright bass and brushed drums",
    "lazy lonely late-night cool jazz trio",
    "eerie music box with bells, wind chimes and celesta",
    "a woman narrating a story in Mandarin Chinese",
    "a man narrating a story in Mandarin Chinese",
] + ANTI_PROMPTS


def cmd_score(a) -> dict:
    res: dict = {"audio": a.audio}
    y = load_audio(a.audio, sr=44100)
    res["dsp"] = dsp_features(y, 44100)
    for name, fn in (("essentia", lambda: essentia_predict(a.audio)),
                     ("aesthetics", lambda: aesthetics(a.audio)),
                     ("clap", lambda: clap_similarity(a.audio, a.prompts or DEFAULT_PROMPTS))):
        if name in (a.skip or []):
            continue
        try:
            res[name] = fn()
        except Exception as ex:  # noqa: BLE001
            res[name] = {"error": f"{type(ex).__name__}: {ex}"[:400]}
    ess = res.get("essentia") or {}
    if "instrument" in ess:
        for k in ("instrument", "mood", "genre"):
            res.setdefault("essentia_top", {})[k] = sorted(ess[k].items(), key=lambda kv: -kv[1])[:8]
    return res


def cmd_melody(a) -> dict:
    ref = read_midi_notes(a.ref, a.track)
    est_all = transcribe(a.audio)
    rng = (min(n["pitch"] for n in ref) - 3, max(n["pitch"] for n in ref) + 3) if ref and not a.no_range else None
    if a.transpose == "auto" or a.transpose not in ("0", 0):
        rng = None if a.transpose == "auto" else rng
    ref_line = skyline(ref)
    est_line = skyline(est_all, pitch_range=rng)
    tr = "auto" if a.transpose == "auto" else int(a.transpose)
    res = compare_melody(ref_line, est_line, transpose=tr)
    if not a.no_intonation and ref_line and est_line:
        try:
            est_t = sorted(est_line, key=lambda n: n["onset"])
            refs = sorted(ref_line, key=lambda n: n["onset"])
            k = res["transpose_semitones"]
            pairs = align_notes(refs, [dict(e, pitch=e["pitch"] - k) for e in est_t], offset=res["time_offset_s"])
            pr = [(refs[i], est_t[j]) for i, j in pairs if i is not None and j is not None
                  and est_t[j]["pitch"] - k == refs[i]["pitch"]]
            res["intonation"] = intonation_cents(a.audio, pr, offset_pitch=k) if pr else None
        except Exception as ex:  # noqa: BLE001
            res["intonation"] = {"error": f"{type(ex).__name__}: {ex}"[:300]}
    res["pitch_range_filter"] = rng
    res["n_transcribed_all"] = len(est_all)
    return {"audio": a.audio, "ref": a.ref, **res}


def cmd_rhythm(a) -> dict:
    return {"audio": a.audio, **beat_track(a.audio)}


ANTI_PROBES = {"electric guitar": "Is there an electric guitar in this audio? Answer only yes or no.",
               "drum machine": "Is there a drum machine or electronic beat in this audio? Answer only yes or no.",
               "singing": "Is there singing in this audio? Answer only yes or no."}
PROBE_Q = dict(ANTI_PROBES, **{
    "小號": "Is there a trumpet in this audio? Answer only yes or no.",
    "trumpet": "Is there a trumpet in this audio? Answer only yes or no.",
    "鋼琴": "Is there a piano in this audio? Answer only yes or no.",
    "低音提琴": "Is there an upright double bass or bass line in this audio? Answer only yes or no.",
    "鼓": "Are there drums or percussion in this audio? Answer only yes or no.",
    "刷子": "Are there brushes played on a snare drum in this audio? Answer only yes or no.",
    "hi-hat": "Is there a hi-hat cymbal in this audio? Answer only yes or no.",
    "鐘": "Are there bells in this audio? Answer only yes or no.",
    "風鈴": "Are there wind chimes in this audio? Answer only yes or no.",
    "鋼片琴": "Is there a celesta or glockenspiel in this audio? Answer only yes or no.",
    "旁白": "Is there a person speaking in this audio? Answer only yes or no.",
})


def _yes(ans: str):
    a = ans.strip().lower()
    if a.startswith(("yes", "是", "有")):
        return True
    if a.startswith(("no", "否", "沒", "无", "無")):
        return False
    return None


def cmd_review(a) -> dict:
    brief = parse_brief(a.brief)
    if a.target_bpm:
        brief["target_bpm"] = a.target_bpm
        brief["bpm_range"] = (a.target_bpm * 0.95, a.target_bpm * 1.05)
    prompts = [brief["clap_prompt"]] + ANTI_PROMPTS + (a.prompts or [])
    sa = argparse.Namespace(audio=a.audio, prompts=prompts, skip=a.skip)
    res = cmd_score(sa)
    clap = res.get("clap") or {}
    if brief["clap_prompt"] in clap:
        anti = {p: clap[p] for p in ANTI_PROMPTS if p in clap}
        best = max(anti, key=anti.get)
        clap["brief_vs_anti"] = {"brief": clap[brief["clap_prompt"]], "anti_best": best, "anti_max": anti[best],
                                 "margin": round(clap[brief["clap_prompt"]] - anti[best], 4)}
    try:
        res["rhythm"] = beat_track(a.audio)
    except Exception as ex:  # noqa: BLE001
        res["rhythm"] = {"error": str(ex)[:300]}
    if a.ref:
        # 有分軌時對主奏分軌比對（混音裡的鋼琴音會被算成多音/錯音）；沒有才用混音
        lead = next((Path(a.stems) / f"{n}.wav" for n in ([a.track] if a.track else []) + ["trumpet", "lead", "melody"]
                     if a.stems and n and (Path(a.stems) / f"{n}.wav").exists()), None)
        try:
            res["melody"] = cmd_melody(argparse.Namespace(audio=str(lead or a.audio), ref=a.ref, track=a.track,
                                                          transpose="0", no_range=False, no_intonation=lead is None))
            res["melody"]["source"] = "stem" if lead else "mix"
        except Exception as ex:  # noqa: BLE001
            res["melody"] = {"error": str(ex)[:300]}
    if a.stems:
        res["stems"] = {}
        for w in sorted(Path(a.stems).glob("*.wav")):
            res["stems"][w.stem] = dsp_features(load_audio(w, sr=44100), 44100)
    if a.baseline:
        base = json.loads(Path(a.baseline).read_text(encoding="utf-8"))
        diffs = []
        pairs = [("混音", res.get("dsp") or {}, base.get("dsp") or {})]
        pairs += [(k, v, (base.get("stems") or {}).get(k) or {}) for k, v in (res.get("stems") or {}).items()]
        for name, cur, old in pairs:
            for key in ("brightness_db", "rms_dbfs"):
                if cur.get(key) is not None and old.get(key) is not None:
                    diffs.append({"name": name, "metric": key, "now": cur[key], "before": old[key],
                                  "delta": round(cur[key] - old[key], 1)})
        res["baseline_diff"] = diffs
    llm_text = None
    if not a.no_llm:
        try:
            llm = AudioLLM(a.model)
            segs = llm_windows(a.audio, 0.0, a.seconds, 30.0)[:2]
            # 不把目標描述給模型（實測給了它就照抄目標說「都符合」），只做盲描述 + 是非題
            desc = [f"[{t0:.0f}s] " + llm.ask(s_, DESCRIBE_PROMPT, max_new_tokens=300) for t0, s_ in segs]
            probes = {}
            for kw in list(brief["instruments"]) + [k for k in ANTI_PROBES if k not in brief["instruments"]]:
                q = PROBE_Q.get(kw) or f"Is there {BRIEF_LEXICON.get(kw, (0, 0, kw))[2]} in this audio? Answer only yes or no."
                ans = llm.ask(segs[0][1], q, max_new_tokens=6)
                probes[kw] = {"answer": ans, "yes": _yes(ans), "expected": kw in brief["instruments"]}
            llm_text = "\n\n".join(desc) + "\n\n是非題（第一個 30 秒窗）：" + "；".join(
                f"{k}={'有' if v['yes'] else ('沒有' if v['yes'] is False else '?')}" for k, v in probes.items())
            res["llm"] = {"model": a.model, "device": llm.device, "describe": desc, "probes": probes, "text": llm_text}
        except Exception as ex:  # noqa: BLE001
            res["llm"] = {"error": f"{type(ex).__name__}: {ex}"[:300]}
    crit = build_critique(brief, res)
    if "melody" in res and "note_f1" in (res["melody"] or {}):
        m = res["melody"]
        if m.get("source") == "stem":
            ok = m["note_f1"] >= 0.9
            (crit["matches"] if ok else crit["mismatches"]).append(
                f"主奏分軌對參考 MIDI：note F1={m['note_f1']}、漏 {len(m['missing'])}、錯音 {len(m['wrong_pitch'])}")
            for w in m["wrong_pitch"][:8]:
                crit["suggestions"].append(f"{w['t_audio']}s 應為 {w['ref']}，聽到 {w['heard']}")
            for w in m["missing"][:8]:
                crit["suggestions"].append(f"參考 {w['t_ref']}s 的 {w['ref']} 沒出聲（檢查力度、音域、取樣是否缺音）")
            ints = (m.get("intonation") or {}).get("out_of_tune_gt25c") or []
            for w in ints[:5]:
                crit["suggestions"].append(f"{w['t_audio']}s {w['ref']} 偏 {w['cents']:+.0f} 音分")
        else:
            # 混音：只看 recall（旋律有沒有出現），精確度會被伴奏污染
            ok = m["note_recall"] >= 0.85
            (crit["matches"] if ok else crit["mismatches"]).append(
                f"混音中參考旋律音找回率 {m['note_recall']}（混音的錯音/多音不可靠，請給 --stems 比對主奏分軌）")
    res["brief"] = {k: v for k, v in brief.items()}
    res["critique"] = crit
    res["critique_markdown"] = critique_markdown(Path(a.audio).name, a.brief, crit, llm_text)
    return res


def cmd_synth_controls(a) -> dict:
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_wav(out / "control_edm_140bpm.wav", synth_edm(44100, 30.0, 140.0), 44100)
    write_wav(out / "control_swing_hats_60bpm_r2.wav", synth_swing_hats(22050, 20.0, 60.0, 2.0), 22050)
    write_wav(out / "control_straight_hats_60bpm.wav", synth_swing_hats(22050, 20.0, 60.0, 1.0), 22050)
    return {"written": sorted(p.name for p in out.glob("control_*.wav"))}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_essentia":
        p = argparse.ArgumentParser()
        p.add_argument("audio")
        p.add_argument("--models", type=Path, default=DEFAULT_ESSENTIA)
        a = p.parse_args(argv[1:])
        print(json.dumps(_essentia_child(a.audio, a.models)))
        return 0
    _maybe_reexec_in_wsl(argv)
    ap = argparse.ArgumentParser(description="AI 聽音工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--out", help="JSON 另存檔案")
        return s

    for name in ("describe", "ask"):
        s = add(name)
        s.add_argument("audio")
        if name == "ask":
            s.add_argument("question")
        s.add_argument("--model", default="omni", choices=["omni", "qwen2-audio"])
        s.add_argument("--start", type=float, default=0.0)
        s.add_argument("--seconds", type=float, default=30.0)
        s.add_argument("--window", type=float, default=30.0)
        if name == "describe":
            s.add_argument("--prompt")
    s = add("score")
    s.add_argument("audio")
    s.add_argument("--prompts", nargs="*")
    s.add_argument("--skip", nargs="*", default=[], help="essentia aesthetics clap")
    s = add("melody")
    s.add_argument("audio")
    s.add_argument("--ref", required=True)
    s.add_argument("--track")
    s.add_argument("--transpose", default="0", help="半音數或 auto")
    s.add_argument("--no-range", action="store_true", help="不依參考音域過濾轉譜結果")
    s.add_argument("--no-intonation", action="store_true")
    s = add("rhythm")
    s.add_argument("audio")
    s = add("dsp")
    s.add_argument("audio")
    s = add("review")
    s.add_argument("audio")
    s.add_argument("--brief", required=True)
    s.add_argument("--ref")
    s.add_argument("--track")
    s.add_argument("--stems")
    s.add_argument("--target-bpm", type=float)
    s.add_argument("--prompts", nargs="*")
    s.add_argument("--skip", nargs="*", default=[])
    s.add_argument("--no-llm", action="store_true")
    s.add_argument("--model", default="omni", choices=["omni", "qwen2-audio"])
    s.add_argument("--seconds", type=float, default=60.0)
    s.add_argument("--md", help="評語 Markdown 另存檔案")
    s.add_argument("--baseline", help="上一版 review 的 JSON，逐軌比較亮度與音量變化")
    s = add("synth-controls")
    s.add_argument("out_dir")
    add("licenses")
    a = ap.parse_args(argv)
    if a.cmd == "dsp":
        res = {"audio": a.audio, **dsp_features(load_audio(a.audio, 44100), 44100)}
    elif a.cmd == "licenses":
        res = LICENSES
    else:
        res = {"describe": cmd_describe, "ask": cmd_ask, "score": cmd_score, "melody": cmd_melody,
               "rhythm": cmd_rhythm, "review": cmd_review, "synth-controls": cmd_synth_controls}[a.cmd](a)
    if a.cmd == "review" and a.md:
        Path(a.md).write_text(res["critique_markdown"], encoding="utf-8")
    _emit(res, a.out)
    if a.cmd == "review":
        print(res["critique_markdown"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
