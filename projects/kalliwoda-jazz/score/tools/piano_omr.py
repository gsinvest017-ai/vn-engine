"""Read the Audiveris output of the Alex'Not oboe+piano score (IMSLP #907463,
CC BY-SA 4.0), align its oboe staff to the verified oboe transcription, and
derive per-bar / per-half-bar chord labels from the piano staves.

Run in the WSL venv (needs music21 only for MIDI export of the reduction):
    ~/.venv-jazz/bin/python score/tools/piano_omr.py <omr_pf_dir> <score_dir>

Writes:
    <score_dir>/harmony_auto.json   automatic chord labels for every bar (unverified)
    <score_dir>/alignment.json      piano-score bar <-> oboe-part bar mapping + melody agreement
    <score_dir>/reduction.mid       piano reduction (OMR, key-corrected) as MIDI
"""
from __future__ import annotations

import difflib
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from fractions import Fraction as F
from pathlib import Path

STEP_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARPS, FLATS = "FCGDAEB", "BEADGCF"
ACC = {"sharp": 1, "flat": -1, "natural": 0, "double-sharp": 2, "flat-flat": -2, "sharp-sharp": 2}
NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
QUAL = {  # intervals above root
    "": (0, 4, 7), "m": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8),
    "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10),
    "m7b5": (0, 3, 6, 10), "dim7": (0, 3, 6, 9),
}


def key_alter(fifths, step):
    if fifths > 0 and step in SHARPS[:fifths]:
        return 1
    if fifths < 0 and step in FLATS[:-fifths]:
        return -1
    return 0


def load_pages(d: Path):
    """Return list of piano-score measures: dict(oboe=[(step,oct,alter_expl,dur,onset)], piano=[...])."""
    out = []
    for p in range(3, 23):
        z = zipfile.ZipFile(d / f"an_{p:02d}.mxl")
        name = [n for n in z.namelist() if not n.startswith("META")][0]
        root = ET.fromstring(z.read(name))
        parts = root.findall("part")
        per_part = []
        for part in parts:
            div = 1
            ms = []
            for m in part.findall("measure"):
                a = m.find("attributes")
                if a is not None and a.find("divisions") is not None:
                    div = int(a.findtext("divisions"))
                t = F(0)
                last_on = F(0)
                notes = []
                for el in m:
                    if el.tag == "backup":
                        t -= F(int(el.findtext("duration")), div)
                        continue
                    if el.tag == "forward":
                        t += F(int(el.findtext("duration")), div)
                        continue
                    if el.tag != "note":
                        continue
                    if el.find("grace") is not None:
                        continue
                    dur = F(int(el.findtext("duration", "0")), div)
                    chord = el.find("chord") is not None
                    on = last_on if chord else t
                    if el.find("rest") is None:
                        pt = el.find("pitch")
                        acc = el.findtext("accidental")
                        notes.append(dict(step=pt.findtext("step"), octv=int(pt.findtext("octave")),
                                          acc=ACC.get(acc) if acc in ACC else None,
                                          dur=dur, on=on, staff=el.findtext("staff", "1")))
                    if not chord:
                        last_on = t
                        t += dur
                ms.append(notes)
            per_part.append(ms)
        for i in range(len(per_part[0])):
            out.append(dict(page=p, idx=i + 1, oboe=per_part[0][i], piano=per_part[1][i] if len(per_part) > 1 else []))
    return out


def realize(notes, fifths):
    """Apply true key + explicit accidentals (carried per step/octave within the bar)."""
    carried = {}
    res = []
    for n in sorted(notes, key=lambda n: n["on"]):
        k = (n["step"], n["octv"], n.get("staff"))
        if n["acc"] is not None:
            alt = n["acc"]; carried[(n["step"], n["octv"])] = alt
        elif (n["step"], n["octv"]) in carried:
            alt = carried[(n["step"], n["octv"])]
        else:
            alt = key_alter(fifths, n["step"])
        midi = 12 * (n["octv"] + 1) + STEP_PC[n["step"]] + alt
        res.append(dict(midi=midi, dur=n["dur"], on=n["on"]))
    return res


def diat(notes):
    return [f"{n['step']}{n['octv']}" for n in sorted(notes, key=lambda n: n["on"])]


def best_chord(seg, prefer_bass=True):
    if not seg:
        return None
    w = [0.0] * 12
    for n in seg:
        w[n["midi"] % 12] += float(n["dur"])
    bass = min(seg, key=lambda n: (n["midi"]))["midi"] % 12
    tot = sum(w) or 1
    best = None
    for r in range(12):
        for q, iv in QUAL.items():
            tones = {(r + i) % 12 for i in iv}
            cover = sum(w[pc] for pc in tones)
            miss = sum(1 for pc in tones if w[pc] == 0)
            score = cover / tot - 0.12 * miss - (0.04 * (len(iv) - 3))
            if r == bass:
                score += 0.08
            if best is None or score > best[0]:
                best = (score, r, q)
    score, r, q = best
    name = NAMES[r] + q
    if bass != r:
        name += "/" + NAMES[bass]
    return dict(name=name, root=NAMES[r], quality=q, bass=NAMES[bass], fit=round(score, 3))


def main(pf_dir: Path, score_dir: Path):
    pages = load_pages(pf_dir)
    # verified oboe transcription
    oboe = []
    for raw in (score_dir / "oboe_transcription.txt").read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        body = re.split(r"\s#\s", raw, 1)[0].split()
        lab, toks = body[0], body[1:]
        steps = []
        for t in toks:
            if t.startswith("r:") or t.startswith("g:"):
                continue
            nm = t.split(":")[0]
            m = re.fullmatch(r"([A-G])(?:bb|b|##|#)?(-?\d)", nm)
            steps.append(m.group(1) + m.group(2))
        oboe.append((lab, steps))

    # label piano-score measures: A1..A168, R1..R89, V1..V308 (from page anchors)
    pf_labels = [f"A{i}" for i in range(1, 169)] + [f"R{i}" for i in range(1, 90)] + [f"V{i}" for i in range(1, 309)]
    assert len(pf_labels) == len(pages), (len(pf_labels), len(pages))

    # align movement by movement on the oboe staff (diatonic step sequences, robust to key misreads)
    align = {}
    agree = []
    for mv in "ARV":
        pf_idx = [i for i, l in enumerate(pf_labels) if l[0] == mv]
        ob_idx = [i for i, (l, _) in enumerate(oboe) if l[0] == mv]
        a = ["|".join(diat(pages[i]["oboe"])) for i in pf_idx]
        b = ["|".join(s) for _, s in (oboe[i] for i in ob_idx)]
        sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("equal", "replace") and (i2 - i1) == (j2 - j1):
                for k in range(i2 - i1):
                    align[pf_labels[pf_idx[i1 + k]]] = oboe[ob_idx[j1 + k]][0]
            elif tag == "replace":
                for k in range(min(i2 - i1, j2 - j1)):
                    align[pf_labels[pf_idx[i1 + k]]] = oboe[ob_idx[j1 + k]][0]
        # melody agreement per aligned bar with notes
    ob_map = dict(oboe)
    n_cmp = n_eq = 0
    per_bar = []
    for pl, ol in align.items():
        a = diat(pages[pf_labels.index(pl)]["oboe"])
        b = ob_map[ol]
        if not b:
            continue
        r = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        ratio = r.ratio()
        n_cmp += 1
        n_eq += ratio == 1.0
        per_bar.append(dict(piano_bar=pl, oboe_bar=ol, ratio=round(ratio, 3)))

    # true key per oboe label
    def fifths_for(lab):
        mv, n = lab[0], int(lab[1:])
        if mv == "A":
            return -1 if n <= 92 else 0
        if mv == "R":
            return -4
        return 0 if 146 <= n <= 197 else -1

    inv = {pl: ol for pl, ol in align.items()}
    harmony = []
    red_events = []
    t_q = F(0)
    for i, pl in enumerate(pf_labels):
        ol = inv.get(pl)
        fx = fifths_for(ol) if ol else fifths_for(pl)
        pn = realize(pages[i]["piano"], fx)
        bar_len = {"A": F(4), "R": F(3, 2), "V": F(2)}[pl[0]]
        halves = [(F(0), bar_len / 2), (bar_len / 2, bar_len)] if pl[0] != "R" else [(F(0), bar_len)]
        chords = []
        for s, e in halves:
            seg = [n for n in pn if s <= n["on"] < e]
            chords.append(best_chord(seg))
        harmony.append(dict(piano_bar=pl, oboe_bar=ol, key_fifths=fx, chords=chords))
        for n in pn:
            red_events.append((t_q + n["on"], n["dur"], n["midi"]))
        t_q += bar_len

    (score_dir / "harmony_auto.json").write_text(json.dumps(harmony, ensure_ascii=False, indent=0, default=str), encoding="utf-8")
    (score_dir / "alignment.json").write_text(json.dumps(dict(
        piano_score_bars=len(pf_labels), aligned=len(align), compared_bars_with_notes=n_cmp,
        exact_melody_match=n_eq, per_bar=per_bar), ensure_ascii=False, indent=0), encoding="utf-8")

    # reduction MIDI (piano OMR, key-corrected), constant tempo per movement
    import mido
    mf = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack(); mf.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name="Piano reduction (OMR)", time=0))
    tr.append(mido.Message("program_change", program=0, time=0))
    evs = []
    for on, dur, midi in red_events:
        evs.append((on, 1, midi)); evs.append((on + dur, 0, midi))
    # tempo changes at movement boundaries (quarter-note positions)
    A_len, R_len = F(168 * 4), F(89 * 3, 2)
    tempos = [(F(0), 132), (A_len, 29), (A_len + R_len, 144)]  # R: eighth=58 -> quarter=29
    for pos, bpm in tempos:
        evs.append((pos, -1, bpm))
    evs.sort(key=lambda e: (e[0], e[1]))
    last = F(0)
    for pos, kind, val in evs:
        dt = int(round((pos - last) * 480)); last = pos
        if kind == -1:
            tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(val), time=dt))
        elif kind == 1:
            tr.append(mido.Message("note_on", note=val, velocity=64, time=dt))
        else:
            tr.append(mido.Message("note_off", note=val, velocity=0, time=dt))
    mf.save(score_dir / "reduction.mid")
    print("aligned", len(align), "compared", n_cmp, "exact", n_eq)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
