"""Convert per-page Audiveris MusicXML output into a printed-measure-numbered draft
transcription (text format consumed by build_score.py).

The OMR pages come from the Alex'Not oboe part (IMSLP #1006130, CC BY-SA 4.0),
rendered at 400 dpi.  Audiveris misreads some key signatures and multi-rest
counts, so this script:
  * maps OMR measure indices to printed measure numbers via a hand-made table
    (read off the page images),
  * re-derives every pitch alteration from the *true* key signature plus the
    explicit accidentals printed in the measure (OMR key misreads are ignored),
  * turns cue-note measures / multi-rests into whole-bar rests.

Output lines:  <label> <tokens...>   where a token is  PITCH:DUR[~]  or r:DUR
or g:PITCH (grace).  DUR is in quarter notes, written as a fraction.
"""
from __future__ import annotations

import sys
import zipfile
import xml.etree.ElementTree as ET
from fractions import Fraction as F
from pathlib import Path

STEPS = "CDEFGAB"
SHARP_ORDER = "FCGDAEB"
FLAT_ORDER = "BEADGCF"


def key_alter(fifths: int, step: str) -> int:
    if fifths > 0 and step in SHARP_ORDER[:fifths]:
        return 1
    if fifths < 0 and step in FLAT_ORDER[:-fifths]:
        return -1
    return 0


ACC = {"sharp": 1, "flat": -1, "natural": 0, "double-sharp": 2, "flat-flat": -2, "sharp-sharp": 2}


def true_key(label: str) -> int:
    mv, n = label[0], int(label[1:])
    if mv == "A":
        return -1 if n <= 92 else 0
    if mv == "R":
        return -4
    if mv == "V":
        if 146 <= n <= 197:
            return 0
        return -1
    raise ValueError(label)


def bar_len(label: str) -> F:
    return {"A": F(4), "R": F(3, 2), "V": F(2)}[label[0]]


# page -> list of (omr_idx_from, omr_idx_to, action)
#   action = ("map", first_label)  -> consecutive printed labels
#   action = ("rest", first_label, last_label)  -> whole-bar rests for printed range (consumes idx range)
#   action = ("drop",)
MAP = {
    "02": [
        (1, 8, ("rest", "A1", "A8")),        # cue notes (Cor./Clar.)
        (9, 11, ("rest", "A9", "A38")),      # "30" multirest (OMR read 3)
        (12, 17, ("rest", "A39", "A44")),    # Viol.1 cue
        (18, 55, ("map", "A45")),
        (56, 61, ("rest", "A83", "A88")),    # "6" multirest
        (62, 65, ("rest", "A89", "A92")),    # Viol.1 cue + tutti cue chords
        (66, 66, ("drop",)),                 # spurious split at double bar
        (67, 83, ("map", "A93")),
    ],
    "03": [
        (1, 35, ("map", "A110")),
        (36, 37, ("rest", "A145", "A165")),  # "21" multirest (OMR read 2)
        (38, 41, ("rest", "A166", "R2")),    # Viol.1 cue + Viola cue
        (42, 75, ("map", "R3")),
        (76, 79, ("rest", "R37", "R40")),
    ],
    "04": [
        (1, 20, ("map", "R41")),
        (21, 23, ("rest", "R61", "R63")),
        (24, 49, ("map", "R64")),
        (50, 59, ("rest", "V1", "V20")),     # Cor. cue, "14" multirest, Viol.1 cue
        (60, 98, ("map", "V21")),
    ],
    "05": [
        (1, 4, ("map", "V60")),
        (5, 11, ("rest", "V64", "V88")),     # "20" multirest + Viol./Clar. cue
        (12, 32, ("map", "V89")),
        (33, 33, ("map", "V110")),           # OMR merged V110+V111 -> fixed by hand
        (34, 39, ("map", "V112")),
        (40, 40, ("map", "V118")),           # OMR merged V118+V119 -> fixed by hand
        (41, 98, ("map", "V120")),
        (99, 115, ("rest", "V178", "V204")),  # "18" multirest, Cor. cue, "7" multirest
    ],
    "06": [
        (1, 104, ("map", "V205")),
    ],
}


def label_seq(first: str, count: int):
    mv, n = first[0], int(first[1:])
    return [f"{mv}{n + i}" for i in range(count)]


def label_range(a: str, b: str):
    if a[0] == b[0]:
        return label_seq(a, int(b[1:]) - int(a[1:]) + 1)
    # crosses movement boundary A->R
    out = []
    if a[0] == "A":
        out += label_seq(a, 167 - int(a[1:]) + 1)
        out += label_seq("R1", int(b[1:]))
    return out


def fmt(d: F) -> str:
    return str(d.numerator) if d.denominator == 1 else f"{d.numerator}/{d.denominator}"


def measure_tokens(m, div, key):
    toks = []
    carried = {}
    for n in m.findall("note"):
        grace = n.find("grace") is not None
        if n.find("chord") is not None:
            # oboe is monophonic; keep only top note of a chord -> skip chord members
            continue
        if n.find("rest") is not None:
            toks.append(f"r:{fmt(F(int(n.findtext('duration', '0')), div))}")
            continue
        p = n.find("pitch")
        step, octv = p.findtext("step"), int(p.findtext("octave"))
        acc = n.findtext("accidental")
        if acc in ACC:
            alt = ACC[acc]
            carried[(step, octv)] = alt
        elif (step, octv) in carried:
            alt = carried[(step, octv)]
        else:
            alt = key_alter(key, step)
        name = step + {-2: "bb", -1: "b", 0: "", 1: "#", 2: "##"}[alt] + str(octv)
        if grace:
            toks.append(f"g:{name}")
            continue
        d = F(int(n.findtext("duration", "0")), div)
        tie = any(t.get("type") == "start" for t in n.findall("tie"))
        toks.append(f"{name}:{fmt(d)}{'~' if tie else ''}")
    return toks


def main(omr_dir: Path, out: Path):
    lines = []
    for page, spec in MAP.items():
        z = zipfile.ZipFile(omr_dir / f"ao_{page}.mxl")
        name = [x for x in z.namelist() if not x.startswith("META")][0]
        root = ET.fromstring(z.read(name))
        meas = root.find("part").findall("measure")
        div = 1
        divs = []
        for m in meas:
            a = m.find("attributes")
            if a is not None and a.find("divisions") is not None:
                div = int(a.findtext("divisions"))
            divs.append(div)
        for lo, hi, act in spec:
            if act[0] == "drop":
                continue
            if act[0] == "rest":
                for lab in label_range(act[1], act[2]):
                    lines.append(f"{lab} r:{fmt(bar_len(lab))}   # rest/cue (not oboe)")
                continue
            labs = label_seq(act[1], hi - lo + 1)
            for i, lab in zip(range(lo, hi + 1), labs):
                toks = measure_tokens(meas[i - 1], divs[i - 1], true_key(lab))
                tot = sum(F(t.split(":")[1].rstrip("~")) for t in toks if not t.startswith("g:"))
                flag = "" if tot == bar_len(lab) else f"   # OMR-BAD sum={fmt(tot)}"
                lines.append(f"{lab} {' '.join(toks)}{flag}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(len(lines), "measures written;", sum("OMR-BAD" in l for l in lines), "flagged")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
