"""渲染後音高抽查：每個音色送幾個單音進 sfizz_render，比對發出的音高是否等於 MIDI 音高（檢查取樣命名 / 八度慣例）。

方法：候選 n-12 / n / n+12，各算「諧波梳 (k·f0, k=1..8) 能量平均 − 半諧波 ((k+½)·f0) 能量平均」，取分數最高者。
已知限制：撥奏低音衰減很快，梳狀法偶爾誤判八度（VSCO pizz 的 45/52 在此法下報 -12，
但 HPS 法與原始檔頻譜峰列都顯示正確）；sneakybass 則兩種方法一致顯示「整體低一個八度」→ 設定檔用 transpose=+12。

用法：python projects/kalliwoda-jazz/sound/verify_pitch.py   （暫存檔寫到系統 temp）
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "tools" / "video"))
import jazz_render as J  # noqa: E402

P = HERE.parent
CASES = [
    ("sneakybass", P / "_assets/lib/sneakybass/Programs/02-sneakybass_pluck.sfz", [33, 40, 45, 52, 57]),
    ("vsco_pizz", HERE / "sfz/bass_pizz_vsco.sfz", [28, 33, 40, 45, 52]),
    ("trumpet_open", HERE / "sfz/trumpet_chet_open.sfz", [55, 60, 65, 69, 74, 79]),
    ("trumpet_harmon", HERE / "sfz/trumpet_chet_harmon.sfz", [60, 65, 70, 77]),
    ("piano", P / "_assets/lib/SalamanderGrandPiano/Salamander Grand Piano V3.sfz", [36, 48, 60, 72]),
]


def sounding(x: np.ndarray, sr: int, n: int) -> int:
    seg = x[int(0.08 * sr):int(0.6 * sr)].mean(1)
    seg = seg * np.hanning(len(seg))
    N = 1 << 20
    sp = np.abs(np.fft.rfft(seg, N))
    df = sr / N

    def at(f):
        k = int(round(f / df))
        return sp[max(0, k - 3):k + 4].max()

    best = None
    for c in (n - 12, n, n + 12):
        f = 440 * 2 ** ((c - 69) / 12)
        on = np.mean([at(k * f) for k in range(1, 9) if k * f < sr / 2])
        off = np.mean([at((k + 0.5) * f) for k in range(1, 9) if (k + 0.5) * f < sr / 2])
        if best is None or on - off > best[0]:
            best = (on - off, c)
    return best[1]


def main() -> dict:
    sfizz = J.find_sfizz()
    if not sfizz:
        raise SystemExit("找不到 sfizz_render")
    td = Path(tempfile.mkdtemp())
    out = {}
    for name, sfz, notes in CASES:
        res = {}
        for n in notes:
            b = J.MidiBuilder(bpm=60)
            b.note("x", 0, 1.0, n, 90)
            b.end(2)
            b.save(td / "pc.mid")
            subprocess.run([sfizz, "--sfz", str(sfz), "--midi", str(td / "pc.mid"), "--wav", str(td / "pc.wav"),
                            "-s", "48000"], capture_output=True)
            res[n] = sounding(J.load_wav(td / "pc.wav"), 48000, n)
        out[name] = res
        print(name, " ".join(f"{k}->{v}" for k, v in res.items()))
    return out


if __name__ == "__main__":
    main()
