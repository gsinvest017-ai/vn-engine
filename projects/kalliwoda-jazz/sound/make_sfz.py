"""從 VSCO-2-CE（CC0）的 wav 檔名自動產生 SFZ：Chet 風小號（open / harmon / straight）與低音提琴撥奏（備案）。

VSCO2 的檔名音名採「C3 = MIDI 60」慣例（已用頻譜 HPS 量測驗證：Trumpet sus A#3 → 466 Hz = MIDI 70，
Contrabass Pizz E0 → 41.2 Hz = MIDI 28），所以 midi = (八度 + 2) * 12 + 音級。

用法：python projects/kalliwoda-jazz/sound/make_sfz.py   （輸出到 sound/sfz/）
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parent / "_assets" / "lib" / "VSCO-2-CE"
OUT = HERE / "sfz"
PC = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
PAT = re.compile(r"_([A-G]#?)(-?\d)_v(\d)(?:_rr(\d))?\.wav$")


def midi_of(name: str, octave: int) -> int:
    return (octave + 2) * 12 + PC[name]


def scan(folder: Path) -> dict[int, dict[int, list[str]]]:
    """{midi: {vel_layer: [檔名(依 rr 排序)]}}"""
    m: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for f in sorted(folder.glob("*.wav")):
        r = PAT.search(f.name)
        if r:
            m[midi_of(r.group(1), int(r.group(2)))][int(r.group(3))].append(f.name)
    return m


def key_ranges(notes: list[int], ext_lo: int, ext_hi: int) -> dict[int, tuple[int, int]]:
    """每個取樣音負責到與鄰居的中點；最低/最高再往外延 ext 個半音。"""
    out = {}
    for i, n in enumerate(notes):
        lo = notes[i - 1] + (n - notes[i - 1]) // 2 + 1 if i else n - ext_lo
        hi = n + (notes[i + 1] - n) // 2 if i + 1 < len(notes) else n + ext_hi
        out[n] = (lo, hi)
    return out


def vel_splits(layers: list[int]) -> dict[int, tuple[int, int]]:
    """層數 → 力度區間。兩層時把分界放高（84），讓 ballad 的中弱力度多半落在柔的一層。"""
    if len(layers) == 1:
        return {layers[0]: (1, 127)}
    if len(layers) == 2:
        return {layers[0]: (1, 84), layers[1]: (85, 127)}
    step = 127 / len(layers)
    return {v: (int(i * step) + 1, int((i + 1) * step)) for i, v in enumerate(layers)}


def build(folder: Path, out: Path, header: str, globals_: str, ext=(3, 3), rel_prefix: str = "") -> dict:
    m = scan(folder)
    notes = sorted(m)
    kr = key_ranges(notes, *ext)
    rel = Path("..") / ".." / "_assets" / "lib" / "VSCO-2-CE" / folder.relative_to(LIB)
    lines = [f"// {header}", "// 自動產生：projects/kalliwoda-jazz/sound/make_sfz.py；樣本 VSCO-2-CE（CC0）",
             "<control>", f"default_path={rel.as_posix()}/", "", "<global>", globals_.strip(), ""]
    layers_all = set()
    for n in notes:
        layers = sorted(m[n])
        layers_all.update(layers)
        vs = vel_splits(layers)
        for v in layers:
            files = m[n][v]
            lo, hi = kr[n]
            lines.append(f"<group> lokey={lo} hikey={hi} pitch_keycenter={n} lovel={vs[v][0]} hivel={vs[v][1]}"
                         + (f" seq_length={len(files)}" if len(files) > 1 else ""))
            for k, f in enumerate(files, 1):
                lines.append(f"<region> sample={f}" + (f" seq_position={k}" if len(files) > 1 else ""))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"sfz": out.name, "sample_notes": notes, "key_lo": kr[notes[0]][0], "key_hi": kr[notes[-1]][1],
            "vel_layers": sorted(layers_all), "files": sum(len(f) for d in m.values() for f in d.values())}


# Chet 風：軟起音、較長釋放、velocity 帶動的低通（弱奏更暗更氣）、力度動態範圍稍收
TRUMPET_GLOBAL = """
ampeg_attack=0.045
ampeg_release=0.32
amp_veltrack=80
fil_type=lpf_2p
cutoff=2200
fil_veltrack=2400
resonance=0
"""
BASS_GLOBAL = """
ampeg_release=0.18
amp_veltrack=70
"""


def main():
    info = {}
    T = LIB / "Brass" / "Trumpet"
    info["trumpet_chet_open"] = build(T / "sus", OUT / "trumpet_chet_open.sfz",
                                      "小號 open、無抖音 sustain，Chet 風柔化", TRUMPET_GLOBAL, ext=(4, 3))
    info["trumpet_chet_harmon"] = build(T / "harmonM-sus", OUT / "trumpet_chet_harmon.sfz",
                                        "小號 harmon mute sustain", TRUMPET_GLOBAL.replace("cutoff=2200", "cutoff=3200"),
                                        ext=(4, 5))
    info["trumpet_chet_straight"] = build(T / "straightM-sus", OUT / "trumpet_chet_straight.sfz",
                                          "小號 straight mute sustain", TRUMPET_GLOBAL, ext=(4, 5))
    info["bass_pizz_vsco"] = build(LIB / "Strings" / "Solo Contrabass" / "Pizz", OUT / "bass_pizz_vsco.sfz",
                                   "低音提琴撥奏（VSCO2 Solo Contrabass Pizz）", BASS_GLOBAL, ext=(0, 4))
    for k, v in info.items():
        print(k, v)
    return info


if __name__ == "__main__":
    main()
