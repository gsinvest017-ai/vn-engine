"""多軌 MIDI → 取樣音色庫（SFZ / SF2）→ 分軌 wav + 混音 wav 的批次渲染器（爵士三重奏專案用，也可通用）。

用法（在 repo 根目錄）：
    python tools/video/jazz_render.py --midi song.mid --config projects/kalliwoda-jazz/sound/render_config.json \
        --out projects/kalliwoda-jazz/_assets/render/test

輸出（--out 資料夾）：
    stems_midi/<軌名>.mid     每軌拆出來的單軌 MIDI（含指揮軌 tempo）
    stems/<軌名>.wav          每軌渲染結果（48 kHz 立體聲 float32，已套 gain/pan/濾波，未加殘響）
    reverb_wet.wav            殘響濕訊號（各軌 send 加總後過 ffmpeg afir 卷積）
    premix.wav                乾 + 濕，響度先對齊到 -20 LUFS，未壓縮
    mix.wav                   過 ffmpeg bus 壓縮 + 增益 + limiter 的最終混音（24-bit PCM）
    render_report.json        每軌與混音的量測（峰值、true peak、LUFS、爆音、空白音、頻段能量）

設定檔（JSON，路徑相對於設定檔所在資料夾）：
    {
      "samplerate": 48000,
      "tracks": [
        {"name": "trumpet", "midi_track": "trumpet", "sfz": "sfz/trumpet_chet.sfz",
         "gain_db": 0, "pan": -0.15, "reverb_send": 0.3, "hpf_hz": 0, "lpf_hz": 0, "init_cc": {"64": 0},
         "fold_range": [33, 72]}
      ],
      "reverb": {"t60_low": 2.2, "t60_high": 1.0, "predelay": 0.025, "seed": 7, "wet_db": 0},
      "bus": {"compressor": "threshold=0.125:ratio=2:attack=25:release=300:knee=4", "limit_db": -1.0},
      "target_lufs": -16.0
    }
    - "transpose"：半音數（選填，先套用）；"fold_range"：[lo, hi]，transpose 後仍超出音色音域的音以八度摺回（選填）；"init_cc"：tick 0 送出的 CC（選填）。
    - "midi_track"：用 MIDI 軌名（track name meta）比對，也可給整數索引。
    - 音色：".sfz" 走 sfizz_render；".sf2"/".sf3" 走 fluidsynth（需在 PATH 上；目前未實測）。
    - sfizz_render 位置：設定檔 "sfizz_render"、環境變數 SFIZZ_RENDER、PATH，
      或 repo 內 projects/*/_assets/bin/**/sfizz_render(.exe) 依序尋找。

設計取捨：
- MIDI 讀寫自己實作（標準 SMF format 0/1，含 running status），不依賴 mido，方便 Windows 原生 Python 直接跑。
- 殘響用 bgm_synth.reverb_ir 產生的雙頻段雜訊 IR，交給 ffmpeg afir 卷積；沒有 ffmpeg 時退回 scipy fftconvolve。
- 響度 / true peak 沿用 bgm_synth 的 BS.1770 實作。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).parent))
import bgm_synth as _bgm  # noqa: E402  (reverb_ir / integrated_lufs / true_peak_db)

SR = 48000
REPO = Path(__file__).resolve().parents[2]
SILENCE_DBFS = -60.0     # 低於此視為無聲（再與「峰值 - 45 dB」取較低者）
CLIP_LEVEL = 0.999


# ───────────────────────── MIDI（SMF）讀寫 ─────────────────────────

@dataclass
class MidiFile:
    tpb: int
    tracks: list[list[tuple[int, bytes]]] = field(default_factory=list)  # 每軌 [(絕對 tick, 原始訊息 bytes)]

    def track_name(self, i: int) -> str:
        for _, m in self.tracks[i]:
            if m[0] == 0xFF and m[1] == 0x03:
                return _meta_payload(m).decode("latin-1")
        return ""

    def tempo_map(self) -> list[tuple[int, int]]:
        """[(tick, 每拍微秒)]，合併所有軌的 set-tempo，缺省 120 BPM。"""
        tm = [(t, int.from_bytes(_meta_payload(m), "big"))
              for tr in self.tracks for t, m in tr if m[0] == 0xFF and m[1] == 0x51]
        tm.sort()
        if not tm or tm[0][0] != 0:
            tm.insert(0, (0, 500000))
        return tm

    def tick_to_sec(self, tick: int) -> float:
        sec, last_t, last_us = 0.0, 0, 500000
        for t, us in self.tempo_map():
            if t >= tick:
                break
            sec += (t - last_t) * last_us / 1e6 / self.tpb
            last_t, last_us = t, us
        return sec + (tick - last_t) * last_us / 1e6 / self.tpb

    def notes(self, i: int) -> list[tuple[float, float, int, int]]:
        """第 i 軌的音符 [(起秒, 長秒, pitch, vel)]。"""
        on: dict[tuple[int, int], list[tuple[int, int]]] = {}
        out = []
        for t, m in self.tracks[i]:
            st = m[0] & 0xF0
            if st == 0x90 and m[2] > 0:
                on.setdefault((m[0] & 0x0F, m[1]), []).append((t, m[2]))
            elif st == 0x80 or (st == 0x90 and m[2] == 0):
                q = on.get((m[0] & 0x0F, m[1]))
                if q:
                    t0, v = q.pop(0)
                    s0 = self.tick_to_sec(t0)
                    out.append((s0, self.tick_to_sec(t) - s0, m[1], v))
        return sorted(out)

    def end_sec(self) -> float:
        last = max((t for tr in self.tracks for t, _ in tr), default=0)
        return self.tick_to_sec(last)


def _meta_payload(m: bytes) -> bytes:
    n, k = _read_vlq(m, 2)
    return m[k:k + n]


def _read_vlq(b: bytes, i: int) -> tuple[int, int]:
    v = 0
    while True:
        c = b[i]
        i += 1
        v = (v << 7) | (c & 0x7F)
        if not c & 0x80:
            return v, i


def _vlq(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append(0x80 | (v & 0x7F))
        v >>= 7
    return bytes(reversed(out))


_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}


def read_smf(path: Path | str) -> MidiFile:
    b = Path(path).read_bytes()
    if b[:4] != b"MThd":
        raise ValueError(f"{path}: 不是 Standard MIDI File")
    hlen = struct.unpack(">I", b[4:8])[0]
    fmt, ntrk, div = struct.unpack(">HHH", b[8:14])
    if div & 0x8000:
        raise ValueError("不支援 SMPTE time division")
    mf = MidiFile(tpb=div)
    i = 8 + hlen
    for _ in range(ntrk):
        if b[i:i + 4] != b"MTrk":
            raise ValueError(f"{path}: track chunk 損毀 @ {i}")
        n = struct.unpack(">I", b[i + 4:i + 8])[0]
        d = b[i + 8:i + 8 + n]
        i += 8 + n
        j, t, status, evs = 0, 0, 0, []
        while j < len(d):
            dt, j = _read_vlq(d, j)
            t += dt
            c = d[j]
            if c == 0xFF:
                ln, k = _read_vlq(d, j + 2)
                evs.append((t, bytes(d[j:k + ln])))
                j = k + ln
            elif c in (0xF0, 0xF7):
                ln, k = _read_vlq(d, j + 1)
                evs.append((t, bytes(d[j:k + ln])))
                j = k + ln
            else:
                if c & 0x80:
                    status = c
                    j += 1
                k = _DATA_LEN[status & 0xF0]
                evs.append((t, bytes([status]) + bytes(d[j:j + k])))
                j += k
        mf.tracks.append(evs)
    return mf


def write_smf(path: Path | str, mf: MidiFile) -> None:
    out = bytearray(b"MThd" + struct.pack(">IHHH", 6, 1 if len(mf.tracks) > 1 else 0, len(mf.tracks), mf.tpb))
    for tr in mf.tracks:
        body, last = bytearray(), 0
        evs = sorted(tr, key=lambda e: (e[0], _event_order(e[1])))
        for t, m in evs:
            if m[:2] == b"\xff\x2f":
                continue
            body += _vlq(t - last) + m
            last = t
        body += _vlq(0) + b"\xff\x2f\x00"
        out += b"MTrk" + struct.pack(">I", len(body)) + body
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(bytes(out))


def _event_order(m: bytes) -> int:
    """同一 tick：meta → CC/program → note-off → note-on（避免同音重擊時先開後關把新音關掉）。"""
    if m[0] == 0xFF:
        return 0
    st = m[0] & 0xF0
    if st == 0x80 or (st == 0x90 and m[2] == 0):
        return 2
    return 3 if st == 0x90 else 1


class MidiBuilder:
    """用「拍」為單位寫多軌 MIDI 的小工具（測試曲與改編稿都用它）。"""

    def __init__(self, bpm: float = 60.0, tpb: int = 480, time_sig: tuple[int, int] = (4, 4)):
        self.tpb = tpb
        us = int(round(60e6 / bpm))
        num, den = time_sig
        cond = [(0, b"\xff\x03" + _vlq(9) + b"conductor"),
                (0, b"\xff\x51\x03" + us.to_bytes(3, "big")),
                (0, b"\xff\x58\x04" + bytes([num, den.bit_length() - 1, 24, 8]))]
        self.mf = MidiFile(tpb=tpb, tracks=[cond])
        self._idx: dict[str, int] = {}

    def track(self, name: str, channel: int = 0, program: int | None = None) -> int:
        if name not in self._idx:
            nb = name.encode("latin-1")
            evs = [(0, b"\xff\x03" + _vlq(len(nb)) + nb)]
            if program is not None:
                evs.append((0, bytes([0xC0 | channel, program])))
            self.mf.tracks.append(evs)
            self._idx[name] = len(self.mf.tracks) - 1
        return self._idx[name]

    def _tick(self, beat: float) -> int:
        return max(0, int(round(beat * self.tpb)))

    def note(self, name: str, beat: float, dur: float, pitch: int, vel: int, channel: int = 0) -> None:
        tr = self.mf.tracks[self.track(name, channel)]
        t0, t1 = self._tick(beat), self._tick(beat + dur)
        t1 = max(t1, t0 + 1)
        tr.append((t0, bytes([0x90 | channel, pitch & 0x7F, max(1, min(127, int(vel)))])))
        tr.append((t1, bytes([0x80 | channel, pitch & 0x7F, 0])))

    def cc(self, name: str, beat: float, num: int, val: int, channel: int = 0) -> None:
        self.mf.tracks[self.track(name, channel)].append(
            (self._tick(beat), bytes([0xB0 | channel, num & 0x7F, max(0, min(127, int(val)))])))

    def tempo(self, beat: float, bpm: float) -> None:
        us = int(round(60e6 / bpm))
        self.mf.tracks[0].append((self._tick(beat), b"\xff\x51\x03" + us.to_bytes(3, "big")))

    def end(self, beat: float) -> None:
        """在指揮軌放一個 marker 讓檔案長度至少到 beat（尾音用）。"""
        self.mf.tracks[0].append((self._tick(beat), b"\xff\x06\x03end"))

    def save(self, path: Path | str) -> MidiFile:
        write_smf(path, self.mf)
        return self.mf


def split_track(mf: MidiFile, index: int, tail_sec: float = 0.0,
                init_cc: dict | None = None) -> MidiFile:
    """指揮軌（tempo / 拍號，所有軌裡的 meta 0x51/0x58）+ 第 index 軌 → 新的 format-1 MidiFile。
    init_cc {"64": 0, ...}：在 tick 0 插入的 CC（channel 取該軌第一個 channel 訊息，預設 0）。"""
    trk = list(mf.tracks[index])
    if init_cc:
        ch = next((m[0] & 0x0F for _, m in trk if 0x80 <= m[0] < 0xF0), 0)
        trk = [(0, bytes([0xB0 | ch, int(k) & 0x7F, int(v) & 0x7F])) for k, v in init_cc.items()] + trk
    cond = [(t, m) for tr in mf.tracks for t, m in tr if m[0] == 0xFF and m[1] in (0x51, 0x58)]
    if tail_sec > 0:
        last = max((t for tr in mf.tracks for t, _ in tr), default=0)
        us = mf.tempo_map()[-1][1]
        cond.append((last + int(tail_sec * 1e6 / us * mf.tpb), b"\xff\x06\x04tail"))
    return MidiFile(tpb=mf.tpb, tracks=[sorted(cond, key=lambda e: e[0]), trk])


def find_track(mf: MidiFile, key: str | int) -> int:
    if isinstance(key, int):
        return key
    names = [mf.track_name(i) for i in range(len(mf.tracks))]
    for i, n in enumerate(names):
        if n == key:
            return i
    for i, n in enumerate(names):
        if key.lower() in n.lower():
            return i
    raise KeyError(f"MIDI 找不到軌 {key!r}；現有軌名：{names}")


# ───────────────────────── 渲染後端 ─────────────────────────

def find_sfizz(cfg_path: str | None = None) -> str | None:
    for cand in (cfg_path, os.environ.get("SFIZZ_RENDER")):
        if cand and Path(cand).exists():
            return str(cand)
    for name in ("sfizz_render", "sfizz-render"):
        w = shutil.which(name)
        if w:
            return w
    for p in sorted(REPO.glob("projects/*/_assets/bin/**/sfizz_render*")):
        if p.suffix in ("", ".exe") and p.is_file():
            return str(p)
    return None


def render_stem(instrument: Path, midi: Path, wav: Path, sr: int, sfizz: str | None,
                extra_args: list[str] | None = None) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    ext = instrument.suffix.lower()
    if ext == ".sfz":
        if not sfizz:
            raise FileNotFoundError("找不到 sfizz_render（設 SFIZZ_RENDER 或放到 projects/*/_assets/bin/）")
        cmd = [sfizz, "--sfz", str(instrument), "--midi", str(midi), "--wav", str(wav),
               "-s", str(sr), "-q", "3", "-p", "128", *(extra_args or [])]
    elif ext in (".sf2", ".sf3"):
        fs = shutil.which("fluidsynth")
        if not fs:
            raise FileNotFoundError("找不到 fluidsynth（SF2 後端需要）")
        cmd = [fs, "-ni", "-g", "1.0", "-r", str(sr), "-F", str(wav), str(instrument), str(midi)]
    else:
        raise ValueError(f"不支援的音色格式：{instrument}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not wav.exists():
        raise RuntimeError(f"渲染失敗 {instrument.name}: rc={r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")


# ───────────────────────── 音訊工具 ─────────────────────────

def load_wav(path: Path, sr: int = SR) -> np.ndarray:
    """讀成 (n, 2) float64，必要時重取樣到 sr。"""
    rate, x = wavfile.read(str(path))
    if x.dtype.kind == "i":
        x = x.astype(np.float64) / float(np.iinfo(x.dtype).max + 1)
    elif x.dtype.kind == "u":
        x = (x.astype(np.float64) - 128.0) / 128.0
    else:
        x = x.astype(np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    x = x[:, :2]
    if rate != sr:
        g = np.gcd(rate, sr)
        x = signal.resample_poly(x, sr // g, rate // g, axis=0)
    return x


def write_float(path: Path, x: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), sr, x.astype(np.float32))


def pan_gain(x: np.ndarray, pan: float, gain_db: float) -> np.ndarray:
    """立體聲 balance（等功率）：pan -1 = 全左、+1 = 全右。"""
    th = (max(-1.0, min(1.0, pan)) + 1) * np.pi / 4
    g = 10 ** (gain_db / 20) * np.sqrt(2)
    return np.stack([x[:, 0] * np.cos(th) * g, x[:, 1] * np.sin(th) * g], axis=1)


def filt(x: np.ndarray, hpf: float, lpf: float, sr: int = SR) -> np.ndarray:
    if hpf and hpf > 0:
        sos = signal.butter(2, hpf / (sr / 2), "high", output="sos")
        x = signal.sosfilt(sos, x, axis=0)
    if lpf and 0 < lpf < sr / 2:
        sos = signal.butter(2, lpf / (sr / 2), output="sos")
        x = signal.sosfilt(sos, x, axis=0)
    return x


def db(v: float) -> float:
    return float(20 * np.log10(max(v, 1e-12)))


def analyze_audio(x: np.ndarray, sr: int = SR, notes: list[tuple[float, float, int, int]] | None = None) -> dict:
    """峰值 / true peak / RMS / LUFS / 爆音樣本 / 最長靜音 / 頻段能量 / 空白音。"""
    mono = x.mean(axis=1)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    win = int(0.05 * sr)
    nwin = len(mono) // win
    frames = mono[: nwin * win].reshape(nwin, win) if nwin else np.zeros((0, win))
    lv = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-20) if nwin else np.array([])
    # 靜音門檻：絕對 -60 dBFS 與「峰值 - 45 dB」取較低者（取樣庫原始電平常很小，只看絕對值會把整軌判成靜音）
    sil = min(SILENCE_DBFS, db(peak) - 45.0)
    active = np.where(lv > sil)[0]
    longest_gap = 0.0
    if active.size:
        seg = lv[active[0]:active[-1] + 1] <= sil
        run = best = 0
        for s in seg:
            run = run + 1 if s else 0
            best = max(best, run)
        longest_gap = best * win / sr
    f, pxx = signal.welch(mono, sr, nperseg=8192) if len(mono) >= 8192 else (np.array([1.0]), np.array([0.0]))
    tot = float(pxx.sum()) + 1e-30
    bands = {"sub_20_60": (20, 60), "low_60_250": (60, 250), "lowmid_250_2k": (250, 2000),
             "high_2k_8k": (2000, 8000), "air_8k_20k": (8000, 20000)}
    band_pct = {k: round(100 * float(pxx[(f >= a) & (f < b)].sum()) / tot, 2) for k, (a, b) in bands.items()}
    out = {
        "duration_s": round(len(x) / sr, 3),
        "peak_dbfs": round(db(peak), 2),
        "true_peak_dbtp": round(_bgm.true_peak_db(x), 2) if len(x) else None,
        "rms_dbfs": round(db(float(np.sqrt(np.mean(x ** 2)))) if len(x) else -240, 2),
        "lufs_integrated": round(_bgm.integrated_lufs(x, sr), 2) if sr == 48000 and len(x) else None,
        "clipped_samples": int(np.sum(np.abs(x) >= CLIP_LEVEL)),
        "first_sound_s": round(active[0] * win / sr, 3) if active.size else None,
        "last_sound_s": round((active[-1] + 1) * win / sr, 3) if active.size else None,
        "silence_threshold_dbfs": round(sil, 1),
        "longest_internal_silence_s": round(longest_gap, 3),
        "spectral_centroid_hz": round(float((f * pxx).sum() / tot), 1),
        "band_energy_pct": band_pct,
    }
    if notes is not None:
        out.update(note_levels(mono, sr, notes))
    return out


def note_levels(mono: np.ndarray, sr: int, notes: list[tuple[float, float, int, int]]) -> dict:
    """每個音符在 [起音, 起音 + min(長度, 1 s)] 內的最大短時（20 ms）RMS。
    空白音 = 低於 max(-75 dBFS 絕對下限, 該軌音符中位數 - 30 dB)。
    （單看絕對值會把本來就小聲的刷子 stir / hi-hat 腳踩誤判，所以用相對門檻。）"""
    w = int(0.02 * sr)
    lv = []
    for s0, d, _p, _v in notes:
        a = int(s0 * sr)
        seg = mono[a:a + int(min(max(d, 0.1), 1.0) * sr)]
        k = len(seg) // w
        if k == 0:
            lv.append(-240.0)
            continue
        fr = seg[: k * w].reshape(k, w)
        lv.append(db(float(np.sqrt(np.max(np.mean(fr ** 2, axis=1))))))
    med = float(np.median(lv)) if lv else -240.0
    thr = max(-75.0, med - 30.0)
    dead = [{"t": round(n[0], 3), "pitch": n[2], "vel": n[3], "level_dbfs": round(l, 1)}
            for n, l in zip(notes, lv) if l < thr]
    by_pitch: dict[int, list[float]] = {}
    for n, l in zip(notes, lv):
        by_pitch.setdefault(n[2], []).append(l)
    return {"notes": len(notes), "note_level_median_dbfs": round(med, 1), "dead_threshold_dbfs": round(thr, 1),
            "dead_notes": dead,
            "pitch_range": [min(by_pitch), max(by_pitch)] if by_pitch else None}


def fold_notes(mf: MidiFile, index: int, lo: int = 0, hi: int = 127, transpose: int = 0) -> list[tuple[int, bytes]]:
    """第 index 軌音高先 transpose，再把超出 [lo, hi] 的音以八度摺回範圍內（範圍需 ≥ 12 半音才保證摺得進去）。
    例：sneakybass 以「記譜高八度」對應（MIDI 45 發出 A1 = 55 Hz），要 transpose=+12 才會照科學音高發聲。"""
    out = []
    for t, m in mf.tracks[index]:
        st = m[0] & 0xF0
        if st in (0x80, 0x90):
            n = m[1] + transpose
            while n < lo:
                n += 12
            while n > hi:
                n -= 12
            m = bytes([m[0], n, m[2]])
        out.append((t, m))
    return out


# ───────────────────────── ffmpeg 後製 ─────────────────────────

def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def convolve_reverb(send: np.ndarray, ir: np.ndarray, sr: int = SR, use_ffmpeg: bool = True) -> np.ndarray:
    """send (n,2) 與立體 IR (m,2) 卷積：L→IR_L、R→IR_R。優先 ffmpeg afir，否則 scipy。"""
    ff = _ffmpeg() if use_ffmpeg else None
    n_out = len(send) + len(ir) - 1
    if ff:
        with tempfile.TemporaryDirectory() as td:
            a, b, c = Path(td, "send.wav"), Path(td, "ir.wav"), Path(td, "wet.wav")
            write_float(a, send, sr)
            write_float(b, ir, sr)
            pad = len(ir) / sr + 0.1
            cmd = [ff, "-v", "error", "-y", "-i", str(a), "-i", str(b), "-filter_complex",
                   f"[0:a]apad=pad_dur={pad:.3f}[s];[s][1:a]afir=dry=1:wet=1:irnorm=-1:irgain=1[o]",
                   "-map", "[o]", "-c:a", "pcm_f32le", str(c)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0 and c.exists():
                wet = load_wav(c, sr)
                return _fit(wet, n_out)
    wet = np.stack([signal.fftconvolve(send[:, k], ir[:, k]) for k in range(2)], axis=1)
    return _fit(wet, n_out)


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros((n - len(x), x.shape[1]))])


def bus_process(x: np.ndarray, compressor: str, gain_db: float, limit_db: float, out: Path,
                sr: int = SR) -> np.ndarray:
    """ffmpeg：acompressor → volume → alimiter，輸出 24-bit PCM；無 ffmpeg 時只做增益 + 硬限幅並註記。"""
    ff = _ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    lim = 10 ** (limit_db / 20)
    if ff:
        with tempfile.TemporaryDirectory() as td:
            a = Path(td, "in.wav")
            write_float(a, x, sr)
            chain = ",".join(p for p in (
                f"acompressor={compressor}" if compressor else "",
                f"volume={gain_db:.3f}dB",
                f"alimiter=limit={lim:.4f}:attack=5:release=80:level=disabled",
            ) if p)
            cmd = [ff, "-v", "error", "-y", "-i", str(a), "-af", chain, "-c:a", "pcm_s24le", "-ar", str(sr), str(out)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg bus 失敗：{r.stderr[-1500:]}")
        return load_wav(out, sr)
    y = np.clip(x * 10 ** (gain_db / 20), -lim, lim)
    wavfile.write(str(out), sr, np.round(y * 32767).astype(np.int16))
    return y


# ───────────────────────── 主流程 ─────────────────────────

def render(midi_path: Path, config: dict, out_dir: Path, config_dir: Path | None = None,
           only: list[str] | None = None) -> dict:
    config_dir = config_dir or Path.cwd()
    sr = int(config.get("samplerate", SR))
    mf = read_smf(midi_path)
    sfizz = find_sfizz(config.get("sfizz_render"))
    tail = float(config.get("tail_sec", 4.0))
    rv = config.get("reverb", {})
    report: dict = {"midi": str(midi_path), "samplerate": sr, "sfizz_render": sfizz, "tracks": {}}

    stems, sends = {}, {}
    for tc in config["tracks"]:
        name = tc["name"]
        if only and name not in only:
            continue
        idx = find_track(mf, tc.get("midi_track", name))
        inst = (config_dir / tc["sfz" if "sfz" in tc else "sf2"]).resolve()
        if not inst.exists():
            raise FileNotFoundError(f"[{name}] 音色不存在：{inst}")
        smid = out_dir / "stems_midi" / f"{name}.mid"
        src = mf
        if tc.get("fold_range") or tc.get("transpose"):
            src = MidiFile(tpb=mf.tpb, tracks=list(mf.tracks))
            lo, hi = tc.get("fold_range") or (0, 127)
            src.tracks[idx] = fold_notes(mf, idx, lo, hi, int(tc.get("transpose", 0)))
        write_smf(smid, split_track(src, idx, tail_sec=tail, init_cc=tc.get("init_cc")))
        raw = out_dir / "stems_raw" / f"{name}.wav"
        render_stem(inst, smid, raw, sr, sfizz, tc.get("render_args"))
        x = load_wav(raw, sr)
        x = filt(x, tc.get("hpf_hz", 0), tc.get("lpf_hz", 0), sr)
        x = pan_gain(x, tc.get("pan", 0.0), tc.get("gain_db", 0.0))
        stems[name] = x
        sends[name] = float(tc.get("reverb_send", 0.0))
        write_float(out_dir / "stems" / f"{name}.wav", x, sr)
        report["tracks"][name] = {"instrument": str(inst), "midi_track_index": idx,
                                  **analyze_audio(load_wav(raw, sr), sr, src.notes(idx))}
        report["tracks"][name]["after_gain_peak_dbfs"] = round(db(float(np.max(np.abs(x)))), 2)

    if not stems:
        raise ValueError("沒有任何軌被渲染")
    n = max(len(x) for x in stems.values())
    dry = sum(_fit(x, n) for x in stems.values())
    send = sum(_fit(x, n) * sends[k] for k, x in stems.items())
    ir = _bgm.reverb_ir(np.random.default_rng(int(rv.get("seed", 7))), sr,
                        t60_low=float(rv.get("t60_low", 2.2)), t60_high=float(rv.get("t60_high", 1.0)),
                        predelay=float(rv.get("predelay", 0.025)))
    wet = convolve_reverb(send, ir, sr, use_ffmpeg=rv.get("engine", "ffmpeg") == "ffmpeg")
    wet *= 10 ** (float(rv.get("wet_db", 0.0)) / 20)
    write_float(out_dir / "reverb_wet.wav", wet, sr)
    pre = _fit(dry, len(wet)) + wet
    # 修掉尾端完全無聲的部分（保留 0.5 秒）
    lv = np.max(np.abs(pre), axis=1)
    nz = np.where(lv > 10 ** (-80 / 20))[0]
    if nz.size:
        pre = pre[: min(len(pre), nz[-1] + int(0.5 * sr))]
    l0 = _bgm.integrated_lufs(pre, sr)
    pre *= 10 ** ((-20.0 - l0) / 20)
    write_float(out_dir / "premix.wav", pre, sr)

    bus = config.get("bus", {})
    target = float(config.get("target_lufs", -16.0))
    comp = bus.get("compressor", "threshold=0.125:ratio=2:attack=25:release=300:knee=4")
    limit_db = float(bus.get("limit_db", -1.0))
    mix_path = out_dir / "mix.wav"
    # 兩趟：先以估計增益跑一次，量到的 LUFS 誤差再修正一次（壓縮器非線性）
    g = target - (-20.0)
    y = bus_process(pre, comp, g, limit_db, mix_path, sr)
    err = target - _bgm.integrated_lufs(y, sr)
    if abs(err) > 0.3:
        y = bus_process(pre, comp, g + err, limit_db, mix_path, sr)
    report["mix"] = analyze_audio(y, sr)
    report["mix"]["path"] = str(mix_path)
    report["mix"]["target_lufs"] = target
    report["bus"] = {"compressor": comp, "limit_db": limit_db, "reverb": rv, "sends": sends}
    (out_dir / "render_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--midi", required=True, type=Path)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--only", nargs="*", help="只渲染這些軌名（除錯用）")
    a = ap.parse_args(argv)
    cfg = json.loads(a.config.read_text(encoding="utf-8"))
    rep = render(a.midi, cfg, a.out, a.config.parent.resolve(), a.only)
    m = rep["mix"]
    print(f"mix: {m['lufs_integrated']} LUFS, TP {m['true_peak_dbtp']} dBTP, clipped {m['clipped_samples']}")
    for k, t in rep["tracks"].items():
        print(f"  {k:10s} peak {t['peak_dbfs']:7.2f} dBFS  LUFS {t['lufs_integrated']}  "
              f"dead {len(t.get('dead_notes', []))}/{t.get('notes')}  gap {t['longest_internal_silence_s']}s")


if __name__ == "__main__":
    main()
