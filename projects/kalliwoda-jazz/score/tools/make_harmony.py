"""Build score/harmony.json: per-bar chord symbols + Roman numerals.

* Movement II (Romanze, the ballad source) is hand-read bar by bar from the piano
  reduction page images (IMSLP #907463), cross-checked against the automatic
  OMR chord guess; source = "manual".
* Movements I and III come from piano_omr.py (Audiveris OMR of the piano staves,
  key-corrected, template-matched); source = "auto" (UNVERIFIED except where noted).

Usage:  python score/tools/make_harmony.py score
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
PC = {n: i for i, n in enumerate(NAMES)}
PC.update({"Cb": 11, "Gb": 6, "C#": 1, "D#": 3, "G#": 8, "A#": 10, "Fb": 4, "E#": 5, "B#": 0})
ROMAN = ["I", "bII", "II", "bIII", "III", "IV", "#IV", "V", "bVI", "VI", "bVII", "VII"]

# Romanze (Ab major, 3/8).  One entry per bar; "|" separates two chords in one bar
# (first on beat 1, second on beat 3 / last eighth).  conf: h = clear in print,
# m = inner voices partly ambiguous, l = best guess.
ROMANZE = {
    1: ("Ab", "h"), 2: ("Ab", "h"), 3: ("Ab", "h"), 4: ("Ab7/Gb", "h"), 5: ("Db/Ab", "m"),
    6: ("Ab/Eb | Eb7", "m"), 7: ("Ab", "h"), 8: ("Db/F", "m"), 9: ("Ab/Eb | Eb7", "m"),
    10: ("Ab", "h"), 11: ("Ab", "h"), 12: ("Eb7/Bb", "h"), 13: ("Ab | Adim7", "m"),
    14: ("Eb7/Bb", "h"), 15: ("Ab", "m"), 16: ("Ab/C | Bb7/D", "l"), 17: ("Eb7", "l"),
    18: ("Fm/Ab | Eb7", "l"), 19: ("Eb/Bb", "h"), 20: ("Bb7", "h"), 21: ("Eb", "h"),
    22: ("C7/E", "l"),  # oboe alone; implied by E-natural
    23: ("Bbm7", "l"),  # oboe alone; implied
    24: ("Gb/Bb", "m"), 25: ("Ab7/C", "m"), 26: ("Bbm7", "m"), 27: ("Eb7", "h"), 28: ("Eb7", "h"),
    29: ("Bbm/Db", "h"), 30: ("Ab/Eb", "h"), 31: ("Eb7", "h"), 32: ("Ab | Ab7", "h"), 33: ("F7", "m"),
    34: ("Bbm7 | Eb7", "m"), 35: ("Eb7", "m"), 36: ("Ab", "h"), 37: ("Ab/C", "m"), 38: ("C7", "m"),
    39: ("C7", "m"), 40: ("Fm", "h"), 41: ("Fm", "h"), 42: ("Bbm/F", "h"), 43: ("Bdim7/F", "h"),
    44: ("C", "h"), 45: ("Ebm", "h"), 46: ("Cb/Eb", "m"), 47: ("Adim7/Eb", "h"), 48: ("Bb", "h"),
    49: ("Bbm", "h"), 50: ("C7", "h"), 51: ("Bbm", "h"), 52: ("C7", "h"), 53: ("Fm | C7/G", "h"),
    54: ("Dbmaj7/Ab", "m"), 55: ("Dbmaj7/C", "m"), 56: ("Fm", "m"), 57: ("Fm | C7/G", "h"),
    58: ("Fm | Bbm7", "m"), 59: ("Fm/C | C7", "h"), 60: ("Fm", "h"), 61: ("Db/F", "h"),
    62: ("Bdim7/F", "m"), 63: ("Eb7", "h"), 64: ("Ab", "h"), 65: ("Ab7", "h"), 66: ("Db/Ab", "m"),
    67: ("Ab | Eb7", "m"), 68: ("Ab", "h"), 69: ("Db/F", "h"), 70: ("Ab | Eb7", "m"), 71: ("Ab", "h"),
    72: ("Ab/Eb", "h"), 73: ("Eb7/Bb", "h"), 74: ("Ab | Ab7", "m"), 75: ("Eb7/Db", "m"),
    76: ("Eb7", "h"), 77: ("Ab/Eb", "h"), 78: ("Eb7", "h"), 79: ("Ab/Eb", "m"), 80: ("Eb7/Db", "m"),
    81: ("Ab/C | Bbm7/Db", "m"), 82: ("Db | Eb7", "m"), 83: ("Ab", "h"), 84: ("Ab", "h"),
    85: ("Dbm/Ab", "m"), 86: ("Ab", "h"), 87: ("Db/Ab", "m"), 88: ("Ab", "h"), 89: ("Ab", "h"),
}
LOCAL_KEYS = {  # label ranges -> local tonic (for the Roman numeral column)
    "R": [((1, 40), "Ab"), ((41, 44), "F"), ((45, 48), "Eb"), ((49, 60), "F"), ((61, 89), "Ab")],
}
MINOR_LOCAL = {("R", 41, 44), ("R", 45, 48), ("R", 49, 60)}


def movement_key(label):
    mv, n = label[0], int(label[1:])
    if mv == "A":
        return ("F", "major") if n <= 92 else ("C", "major")
    if mv == "R":
        for (a, b), k in LOCAL_KEYS["R"]:
            if a <= n <= b:
                return (k, "minor" if any(x[1] <= n <= x[2] for x in MINOR_LOCAL) else "major")
    if mv == "V":
        return ("C", "major") if 146 <= n <= 197 else ("F", "major")
    raise ValueError(label)


def roman(symbol, tonic, mode):
    m = re.fullmatch(r"([A-G](?:b|#)?)(m7b5|maj7|dim7|dim|aug|m7|m|7)?(?:/([A-G](?:b|#)?))?", symbol)
    if not m:
        return None
    root, q, bass = m.group(1), m.group(2) or "", m.group(3)
    deg = (PC[root] - PC[tonic]) % 12
    r = ROMAN[deg]
    if mode == "minor":  # spell relative to natural minor for readability
        r = {"bIII": "III", "bVI": "VI", "bVII": "VII", "VII": "#vii"}.get(r, r)
    if q in ("dim", "dim7"):  # leading-tone chords: spell as raised degree (bII -> #I ...)
        r = {"bII": "#I", "bIII": "#II", "bVI": "#V", "bVII": "#VI"}.get(r, r)
    if q in ("m", "m7", "dim", "dim7", "m7b5"):
        r = r.lower()
    suffix = {"": "", "7": "7", "maj7": "maj7", "m7": "7", "m": "", "dim": "°", "dim7": "°7",
              "m7b5": "ø7", "aug": "+"}[q]
    inv = ""
    if bass:
        iv = (PC[bass] - PC[root]) % 12
        inv = {3: "6", 4: "6", 7: "64", 6: "64", 10: "42", 11: "42", 9: "42"}.get(iv, f"/{bass}")
        if suffix in ("7", "°7", "ø7", "maj7") and iv in (3, 4):
            inv = "65"
        if suffix in ("7", "°7", "ø7", "maj7") and iv in (6, 7):
            inv = "43"
        if suffix in ("7", "°7", "ø7", "maj7"):
            suffix = suffix.replace("7", "")
    return f"{r}{suffix}{inv}"


def main(score_dir: Path):
    auto = json.loads((score_dir / "harmony_auto.json").read_text(encoding="utf-8"))
    # index auto by oboe-part label (preferred) and piano label
    by_oboe = {a["oboe_bar"]: a for a in auto if a.get("oboe_bar")}
    by_pf = {a["piano_bar"]: a for a in auto}
    counts = {"A": 167, "R": 89, "V": 308}
    ts = {"A": "4/4", "R": "3/8", "V": "2/4"}
    bars = []
    for mv, cnt in counts.items():
        for n in range(1, cnt + 1):
            lab = f"{mv}{n}"
            tonic, mode = movement_key(lab)
            if mv == "R":
                sym, conf = ROMANZE[n]
                chords = []
                parts = [s.strip() for s in sym.split("|")]
                beats = [1, 3] if len(parts) == 2 else [1]
                for b, s in zip(beats, parts):
                    chords.append(dict(beat=b, symbol=s, roman=roman(s, tonic, mode)))
                auto_guess = [c["name"] if c else None for c in by_oboe.get(lab, by_pf.get(lab, {})).get("chords", [])]
                bars.append(dict(bar=lab, time=ts[mv], key=f"{tonic} {mode}", chords=chords,
                                 source="manual", confidence=conf, auto_guess=auto_guess))
            else:
                a = by_oboe.get(lab) or by_pf.get(lab)
                chords = []
                if a:
                    beats = [1, 3] if mv == "A" else [1, 2]
                    for b, c in zip(beats, a["chords"]):
                        if c:
                            chords.append(dict(beat=b, symbol=c["name"], roman=roman(c["name"], tonic, mode),
                                               fit=c["fit"]))
                bars.append(dict(bar=lab, time=ts[mv], key=f"{tonic} {mode}", chords=chords,
                                 source="auto", piano_score_bar=a["piano_bar"] if a else None))
    out = dict(
        work="J. W. Kalliwoda, Concertino for Oboe and Orchestra in F, Op.110",
        numbering="oboe-part bar numbers per movement: A=I. Allegro con fuoco (1-167), "
                  "R=II. Romanze (1-89), V=III. Vivace (1-308). The piano score has one extra "
                  "tutti bar in mvt I (168 bars); auto labels were aligned via the oboe staff.",
        method=dict(
            manual="Romanze: read bar by bar from the piano reduction images (Alex'Not, IMSLP #907463); "
                   "bass + chord tones of both hands; conf h/m/l. auto_guess = OMR template match for comparison.",
            auto="Allegro/Vivace: Audiveris OMR of the piano staves, pitches re-derived from the true key "
                 "signature, duration-weighted template matching per half bar. NOT hand-verified; "
                 "expect errors where OMR misread chords, tremolos or cue notes. 'fit' ~1.0+ = clean triad/7th.",
        ),
        chord_symbol_format="root[quality][/bass]; quality in '', m, 7, maj7, m7, dim, dim7, m7b5, aug",
        bars=bars,
    )
    (score_dir / "harmony.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    agree = sum(1 for b in bars if b["source"] == "manual" and b["auto_guess"] and
                b["auto_guess"][0] and b["chords"][0]["symbol"].split("/")[0] == b["auto_guess"][0].split("/")[0])
    print("bars", len(bars), "romanze manual/auto root+quality agreement on beat 1:", agree, "/ 89")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
