"""Merge the OMR draft with hand fixes, validate, and emit MusicXML / MIDI.

Run (WSL venv with music21):
    ~/.venv-jazz/bin/python score/tools/build_score.py <draft.txt> <fixes.txt> <out_dir>

Outputs in <out_dir>:
    oboe_transcription.txt   merged per-measure text (source of truth, reviewable)
    solo.musicxml / solo.mid full oboe part, 3 movements, continuous numbering
    solo_romanze.musicxml / solo_romanze.mid   movement II only (printed numbering)
    measure_map.json         continuous measure no. -> printed label, provenance
    validation.json          bar-length / range checks
"""
from __future__ import annotations

import json
import re
import sys
from fractions import Fraction as F
from pathlib import Path

from music21 import (bar, clef, duration, expressions, key, meter, metadata,
                     note, stream, tempo, tie)

MOVEMENTS = {
    "A": dict(title="I. Allegro con fuoco", ts="4/4", bar=F(4), key=-1,
              tempo=(132, "quarter"), text="Allegro con fuoco", count=167),
    "R": dict(title="II. Romanze. Adagio", ts="3/8", bar=F(3, 2), key=-4,
              tempo=(58, "eighth"), text="Romanze. Adagio", count=89),
    "V": dict(title="III. Vivace", ts="2/4", bar=F(2), key=-1,
              tempo=(144, "quarter"), text="Vivace", count=308),
}
# printed key changes inside movements (label -> fifths)
KEY_CHANGES = {"A93": 0, "V146": 0, "V198": -1}
# oboe written range check (sounding = written for oboe)
RANGE_LO, RANGE_HI = 58, 93  # Bb3 .. A6


COMMENT = re.compile(r"(?:^|\s)#(?:\s|$)")


def split_comment(raw: str):
    m = COMMENT.search(raw)
    return (raw[:m.start()], raw[m.end():].strip()) if m else (raw, "")


def parse_line(line: str):
    line = split_comment(line)[0].strip()
    if not line:
        return None
    parts = line.split()
    return parts[0], parts[1:]


def load(path: Path):
    out = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        p = parse_line(raw)
        if p:
            comment = split_comment(raw)[1]
            out[p[0]] = (p[1], comment)
    return out


def expand(tokens):
    res = []
    for t in tokens:
        if t == "CADENZA":
            continue
        m = re.fullmatch(r"trem(\d):(.+)", t)
        if m:
            n = int(m.group(1))
            res += [f"{m.group(2)}:1/4"] * n
            continue
        res.append(t)
    return res


def dur_of(tokens):
    return sum(F(t.split(":")[1].rstrip("~")) for t in tokens if not t.startswith("g:"))


def midi_of(name: str) -> int:
    m = re.fullmatch(r"([A-G])(bb|b|##|#)?(-?\d)", name)
    step, acc, octv = m.group(1), m.group(2) or "", int(m.group(3))
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step]
    alt = {"": 0, "#": 1, "##": 2, "b": -1, "bb": -2}[acc]
    return 12 * (octv + 1) + base + alt


def m21_name(name: str) -> str:
    return name.replace("b", "-") if len(name) > 2 else name  # Bb4 -> B-4 ; B4 stays


def to_m21_pitch(name: str) -> str:
    m = re.fullmatch(r"([A-G])(bb|b|##|#)?(-?\d)", name)
    acc = {"": "", "#": "#", "##": "##", "b": "-", "bb": "--"}[m.group(2) or ""]
    return f"{m.group(1)}{acc}{m.group(3)}"


def main(draft_p: Path, fixes_p: Path, out: Path):
    draft = load(draft_p)
    fixes = load(fixes_p)
    labels = [f"{mv}{i}" for mv, meta in MOVEMENTS.items() for i in range(1, meta["count"] + 1)]
    merged = []
    problems = []
    for lab in labels:
        cadenza = False
        if lab in fixes:
            toks, com = fixes[lab]
            cadenza = "CADENZA" in toks
            prov = "hand-fixed"
        elif lab in draft:
            toks, com = draft[lab]
            prov = "rest/cue" if "rest/cue" in com else "omr"
        else:
            raise SystemExit(f"missing measure {lab}")
        toks = expand(toks)
        d = dur_of(toks)
        want = MOVEMENTS[lab[0]]["bar"]
        if d != want and not cadenza:
            problems.append(f"{lab}: sum {d} != {want}")
        merged.append(dict(label=lab, tokens=toks, prov=prov, cadenza=cadenza, dur=d, comment=com))

    # range
    pitches = [(m["label"], t.split(":")[0] if not t.startswith("g:") else t[2:])
               for m in merged for t in m["tokens"] if not t.startswith("r:")]
    midis = [(lab, p, midi_of(p)) for lab, p in pitches]
    out_of_range = [(l, p) for l, p, n in midis if n < RANGE_LO or n > RANGE_HI]
    lo = min(midis, key=lambda x: x[2]); hi = max(midis, key=lambda x: x[2])

    out.mkdir(parents=True, exist_ok=True)
    with (out / "oboe_transcription.txt").open("w", encoding="utf-8") as fh:
        fh.write("# Kalliwoda Op.110 oboe part, merged transcription (draft OMR + hand fixes)\n")
        fh.write("# label tokens   (PITCH:DUR in quarter notes, ~ = tie to next, g: = grace, r: = rest)\n")
        for m in merged:
            fh.write(f"{m['label']} {' '.join(m['tokens'])}   # {m['prov']}"
                     f"{'; CADENZA' if m['cadenza'] else ''}{'; ' + m['comment'] if m['comment'] and m['prov'] == 'hand-fixed' else ''}\n")

    def build(sel_labels, title, renumber_printed=False):
        sc = stream.Score()
        sc.insert(0, metadata.Metadata(title=title, composer="Johann Wenzel Kalliwoda (1801-1866)"))
        part = stream.Part(); part.partName = "Oboe"; part.id = "Oboe"
        prev_note = None
        mv_prev = None
        mno = 0
        for m in merged:
            if m["label"] not in sel_labels:
                continue
            lab = m["label"]; mv = lab[0]; meta = MOVEMENTS[mv]
            mno += 1
            meas = stream.Measure(number=int(lab[1:]) if renumber_printed else mno)
            if mv != mv_prev:
                if mno == 1:
                    meas.insert(0, clef.TrebleClef())
                meas.insert(0, meter.TimeSignature(meta["ts"]))
                meas.insert(0, key.KeySignature(meta["key"]))
                ref = duration.Duration(type=meta["tempo"][1])
                meas.insert(0, tempo.MetronomeMark(text=meta["text"], number=meta["tempo"][0], referent=ref))
                if mv_prev is not None:
                    meas.leftBarline = bar.Barline("double")
                mv_prev = mv
            if lab in KEY_CHANGES:
                meas.insert(0, key.KeySignature(KEY_CHANGES[lab]))
            if m["cadenza"]:
                meas.insert(0, expressions.TextExpression("cadenza a piacere"))
            pending_graces = []
            for t in m["tokens"]:
                if t.startswith("g:"):
                    g = note.Note(to_m21_pitch(t[2:]), quarterLength=0.5).getGrace()
                    g.duration.slash = True
                    meas.append(g)
                    continue
                name, d = t.split(":")
                tied = d.endswith("~")
                ql = F(d.rstrip("~"))
                if name == "r":
                    n = note.Rest(quarterLength=ql)
                    prev_note = None
                else:
                    n = note.Note(to_m21_pitch(name), quarterLength=ql)
                    if prev_note is not None and prev_note.tie is not None and \
                            prev_note.tie.type in ("start", "continue") and prev_note.pitch.midi == n.pitch.midi:
                        n.tie = tie.Tie("continue" if tied else "stop")
                    elif tied:
                        n.tie = tie.Tie("start")
                    prev_note = n
                meas.append(n)
            part.append(meas)
        sc.insert(0, part)
        return sc

    full = build(set(labels), "Oboe Concertino Op.110 - oboe solo part (transcribed)")
    full.write("musicxml", fp=str(out / "solo.musicxml"))
    full.write("midi", fp=str(out / "solo.mid"))
    rom = build({l for l in labels if l[0] == "R"}, "Romanze (Op.110/II) - oboe solo", renumber_printed=True)
    rom.write("musicxml", fp=str(out / "solo_romanze.musicxml"))
    rom.write("midi", fp=str(out / "solo_romanze.mid"))

    mm = [dict(n=i + 1, label=m["label"], prov=m["prov"], cadenza=m["cadenza"]) for i, m in enumerate(merged)]
    (out / "measure_map.json").write_text(json.dumps(mm, ensure_ascii=False, indent=0), encoding="utf-8")
    prov_count = {}
    for m in merged:
        prov_count[m["prov"]] = prov_count.get(m["prov"], 0) + 1
    val = dict(measures=len(merged), per_movement={k: v["count"] for k, v in MOVEMENTS.items()},
               bar_length_problems=problems, provenance=prov_count,
               note_count=len(midis), lowest=dict(label=lo[0], pitch=lo[1], midi=lo[2]),
               highest=dict(label=hi[0], pitch=hi[1], midi=hi[2]),
               out_of_range_Bb3_A6=out_of_range,
               above_A5=[(l, p) for l, p, n in midis if n > 81])
    (out / "validation.json").write_text(json.dumps(val, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in val.items() if k != "above_A5"}, ensure_ascii=False)[:2000])
    print("notes above A5:", len(val["above_A5"]))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
