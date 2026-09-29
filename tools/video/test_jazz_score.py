"""jazz_score.py 的測試：量化、拼寫、移調、時值拼寫、整份樂譜的 MusicXML 結構與「樂譜 ↔ 編曲 MIDI」一致性。

整份樂譜的測試需要 projects/kalliwoda-jazz/score 與 arrangement（沒有就 skip）；music21 讀回只在有 music21 時跑。
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from fractions import Fraction as Fr
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import jazz_score as js  # noqa: E402

ARR = js.PROJ / "arrangement"
HAVE_INPUTS = (js.PROJ / "score" / "solo_romanze.mid").exists() and (ARR / "leadsheet.json").exists() \
    and (ARR / "sections.json").exists()
SW = 0.63


# ───────── 量化 ─────────

@pytest.mark.parametrize("x,exp", [
    (1.63, Fr(3, 2)), (0.315, Fr(1, 4)), (0.815, Fr(3, 4)), (2.0, Fr(2)),
    (0.33, Fr(1, 3)), (0.67, Fr(2, 3)), (0.8333333, Fr(5, 6)), (0.125, Fr(1, 8)),
    (0.12, Fr(0)), (9.3, Fr(19, 2)), (5.64, Fr(11, 2)),          # 前奏手寫微偏移 → 半拍
])
def test_snap(x, exp):
    assert js.snap(x, SW) == exp


def test_snap_end_is_stricter():
    assert js.snap(150.63 + 1.2, SW, end=True) == 152           # 0.83 不是 5/6，量化到下一拍
    assert js.snap(0.63 + 0.37, SW, end=True) == 1
    assert js.snap(25.26, SW, Fr(1, 4)) == Fr(101, 4)            # 經過音用 1/4 拍格


def test_beat_grid():
    assert js.beat_grid({Fr(0), Fr(1, 2), Fr(3, 4)}) == "bin"
    assert js.beat_grid({Fr(0), Fr(1, 3), Fr(2, 3)}) == "trip"
    assert js.beat_grid({Fr(0), Fr(1, 6), Fr(1, 2)}) == "sext"


def test_harmonize_grid_lone_sextuplet_and_conflict():
    a = js.NE(Fr(0), Fr(5, 6), 60)
    b = js.NE(Fr(5, 6), Fr(1), 62)
    js.harmonize_grid([a, b])
    assert a.end == Fr(3, 4) and b.start == Fr(3, 4)               # 孤立的 5/6 → 附點八分＋十六分
    c = js.NE(Fr(10), Fr(10) + Fr(1, 4), 60)
    d = js.NE(Fr(10) + Fr(1, 3), Fr(11), 62)
    js.harmonize_grid([c, d])
    assert all((t - 10) * 6 == int((t - 10) * 6) for t in (c.end, d.start))   # 1/4 與 1/3 混用 → 1/6 格


# ───────── 拼寫、移調、和弦 ─────────

def test_parse_chord():
    c = js.parse_chord("Abm6/9/Eb")
    assert (c["root"], c["suffix"], c["bass"], c["root_pc"]) == ("Ab", "m6/9", "Eb", 8)
    c = js.parse_chord("Eb6/9")
    assert (c["suffix"], c["bass"]) == ("6/9", None)
    assert js.parse_chord("C7(b9,b13)")["suffix"] == "7(b9,b13)"


def test_spell_in_key_and_chord_context():
    eb = js.parse_chord("Ebmaj9")
    assert js.spell(63, eb) == ("E", -1, 4)
    assert js.spell(70, eb) == ("B", -1, 4)
    e13 = js.parse_chord("E13")
    assert js.spell(68, e13) == ("G", 1, 4)                       # E13 的三度是 G♯，不是 A♭
    assert js.spell(66, None, nxt=67) == ("F", 1, 4)              # 半音上行 → 升記號
    assert js.spell(66, None, nxt=65) == ("G", -1, 4)
    assert js.spell(71, js.parse_chord("G7(b9,b13)")) == ("B", 0, 4)


def test_trumpet_transposition_eb_to_f():
    """實音 E♭ 大調 → B♭ 小號記譜 F 大調：每個音上移大二度（音名 +1）。"""
    part = js.PartSpec("P1", "Tpt", "T", 1, [("G", 2)], [], transpose=(-1, -2, 0))
    for p, want in ((63, ("F", 0, 4)), (67, ("A", 0, 4)), (70, ("C", 0, 5)), (68, ("B", -1, 4)), (74, ("E", 0, 5))):
        assert js._written(js.spell(p, None), p, part) == want
    bass = js.PartSpec("P3", "DB", "DB", 1, [("F", 4)], [], transpose=(0, 0, -1))
    assert js._written(("E", -1, 2), 39, bass) == ("E", -1, 3)    # 低音高八度記譜


def test_harmony_xml_kinds_and_transpose():
    x = js.harmony_xml(js.parse_chord("Bb9sus4"), 1, 0, (1, 2))
    assert "<root-step>C</root-step>" in x and 'text="9sus4">other<' in x
    x = js.harmony_xml(js.parse_chord("Ebmaj9/G"), 1, 48, (0, 0))
    assert "major-ninth" in x and "<bass-step>G</bass-step>" in x and "<offset>48</offset>" in x


# ───────── 切片與時值拼寫 ─────────

def _sum(els):
    return sum(e.dur for e in els)


def test_syncopation_and_rests():
    n = js.NE(Fr(1, 2), Fr(2), 60)
    segs = js.slice_voice([n], Fr(0), Fr(3))
    els = js.spell_durations(segs, Fr(0))
    assert _sum(els) == 3
    notes = [e for e in els if e.seg.notes]
    assert [(e.start, e.dur) for e in notes] == [(Fr(1, 2), Fr(3, 2))]   # 反拍上的附點四分音符
    for e in els:
        js.dur_type(e)


def test_triplet_and_chord_ties():
    a = js.NE(Fr(1, 3), Fr(4, 3), 60)
    b = js.NE(Fr(4, 3), Fr(2), 62)
    els = js.spell_durations(js.slice_voice([a, b], Fr(0), Fr(3)), Fr(0))
    assert _sum(els) == 3 and any(e.tmod == (3, 2, "eighth") for e in els)
    assert sum(1 for e in els if e.tuplet in ("start", "start-stop")) == 2
    # 內聲部移動：兩個音延續（連結線），一個音換掉
    c1 = [js.NE(Fr(0), Fr(3), p) for p in (60, 64, 67)]
    c1[2].end = Fr(2)
    inner = js.NE(Fr(2), Fr(3), 69)
    segs = js.slice_voice(c1 + [inner], Fr(0), Fr(3))
    assert len(segs) == 2
    assert [(n.pitch, att, cont) for n, att, cont in segs[1].notes] == [(60, False, False), (64, False, False),
                                                                         (69, True, False)]


def test_whole_beats_merge_to_dotted_half():
    els = js.spell_durations(js.slice_voice([js.NE(Fr(3), Fr(6), 60)], Fr(3), Fr(6)), Fr(3))
    assert [(e.dur, js.dur_type(e)) for e in els] == [(Fr(3), ("half", 1))]


def test_tempo_conversion_roundtrip():
    tempo = [(0.0, 58.0), (264.0, 57.0), (270.0, 47.0)]
    b2s, s2b = js.beat_to_sec_fn(tempo), js.sec_to_beat_fn(tempo)
    assert b2s(24) == pytest.approx(24 * 60 / 58)
    for b in (0, 24, 263.5, 266.2, 280):
        assert s2b(b2s(b)) == pytest.approx(b, abs=1e-6)


# ───────── 整份樂譜 ─────────

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not HAVE_INPUTS:
        pytest.skip("缺編曲輸入（score/、arrangement/）")
    out = tmp_path_factory.mktemp("notation")
    return js.build(7, out), out


def _measure_totals(path: Path):
    root = ET.parse(path).getroot()
    bad, n_meas = [], {}
    for part in root.iter("part"):
        ms = list(part.iter("measure"))
        n_meas[part.get("id")] = len(ms)
        for m in ms:
            tot = defaultdict(int)
            cur = mx = 0
            for el in m:
                if el.tag == "note":
                    if el.find("grace") is not None or el.find("chord") is not None:
                        continue
                    d = int(el.find("duration").text)
                    st = el.find("staff").text if el.find("staff") is not None else "1"
                    tot[(st, el.find("voice").text)] += d
                    cur += d
                    mx = max(mx, cur)
                elif el.tag == "backup":
                    cur -= int(el.find("duration").text)
            if any(v != js.MEAS for v in tot.values()) or mx > js.MEAS:
                bad.append((part.get("id"), m.get("number"), dict(tot)))
    return root, bad, n_meas


def test_all_files_written_and_every_voice_fills_3_4(built):
    res, out = built
    names = {str(Path(k)).replace("\\", "/") for k in res["files"]}
    assert names == {"full_score.musicxml", "parts/trumpet_bb.musicxml", "parts/piano.musicxml",
                     "parts/piano_comp_slash.musicxml", "parts/bass.musicxml", "parts/drums.musicxml",
                     "lead_sheet_C.musicxml", "lead_sheet_Bb.musicxml"}
    for f in res["files"].values():
        root, bad, n_meas = _measure_totals(f)
        assert not bad, (f.name, bad[:3])
        assert set(n_meas.values()) == {96}, (f.name, n_meas)
        assert root.find("identification/creator[@type='composer']").text.startswith("Johann Wenzel Kalliwoda")
        assert "Alex'Not" in root.find("identification/rights").text


def test_part_attributes(built):
    res, out = built
    root = ET.parse(out / "full_score.musicxml").getroot()
    parts = root.findall("part")
    assert len(parts) == 4
    tp, pno, db, dr = parts
    first = lambda p, q: p.find("measure/attributes/" + q)  # noqa: E731
    assert first(tp, "key/fifths").text == "-1" and first(tp, "transpose/chromatic").text == "-2"
    assert first(pno, "key/fifths").text == "-3" and first(pno, "staves").text == "2"
    assert first(db, "transpose/octave-change").text == "-1"
    assert first(dr, "clef/sign").text == "percussion"
    assert first(tp, "time/beats").text == "3" and first(tp, "time/beat-type").text == "4"
    # 排練記號只在總譜最上面一個聲部；9 個段落
    assert len(tp.findall(".//rehearsal")) == 9 and not pno.findall(".//rehearsal")
    # 最後一小節有延長記號、終止線
    last = pno.findall("measure")[-1]
    assert last.find(".//fermata") is not None and last.find(".//arpeggiate") is not None
    assert tp.findall("measure")[-1].find("barline/bar-style").text == "light-heavy"
    words = " ".join(w.text for w in tp.iter("words"))
    assert "harmon mute" in words and "open" in words and "Slow jazz waltz" in words and "rit." in words
    assert tp.find(".//metronome/per-minute").text == "58"


def test_chord_symbols_match_leadsheet(built):
    res, out = built
    ls = json.loads((ARR / "leadsheet.json").read_text(encoding="utf-8"))
    n = sum(len(b["chords"]) for b in ls["bars"])
    root = ET.parse(out / "parts" / "piano.musicxml").getroot()
    assert len(root.findall(".//harmony")) == n
    bb = ET.parse(out / "lead_sheet_Bb.musicxml").getroot().find(".//harmony")
    assert bb.find("root/root-step").text == "F" and bb.find("kind").get("text") == "6/9"   # E♭6/9 → F6/9


def test_drum_notation(built):
    res, out = built
    root = ET.parse(out / "parts" / "drums.musicxml").getroot()
    notes = root.findall(".//note")
    heads = defaultdict(set)
    for n in notes:
        u = n.find("unpitched")
        if u is None:
            continue
        pos = u.find("display-step").text + u.find("display-octave").text
        nh = n.find("notehead")
        heads[pos].add(nh.text if nh is not None else "normal")
    assert heads["C4"] == {"x"}                 # hi-hat 腳踩：下加一線的 x
    assert heads["B4"] == {"slash"}             # 只有掃刷的小節：斜線
    assert heads["F5"] == {"x"}                 # ride
    assert "normal" in heads["C5"]              # 刷子輕拍
    words = " ".join(w.text for w in root.iter("words"))
    assert "Brushes" in words and "sweep" in words
    ev = res["events"]
    ride_bars = {n["bar"] for n in ev["parts"]["drums"] if n["inst"] == "ride"}
    solo = next(s for s in json.loads((ARR / "sections.json").read_text(encoding="utf-8"))["sections"]
                if s["name"] == "piano_solo")["bars"]
    assert ride_bars and all(solo[0] <= b <= solo[1] for b in ride_bars)   # ride 只在鋼琴獨奏


def test_score_matches_rendered_midi(built):
    """記譜音 ↔ 定稿 MIDI（人性化後）：每個音都找得到同音高、半拍內的記譜音。"""
    res, out = built
    ev = res["events"]
    assert ev["midi_matches_arrangement"] is True
    cmp = js.compare_midi(ev)
    for part in ("trumpet", "bass", "piano"):
        assert cmp[part]["match_rate"] == 1.0, (part, cmp[part])
        assert cmp[part]["within_half_beat"] >= 0.98, (part, cmp[part])
    assert 0.05 < cmp["trumpet"]["median_humanize_offset_beats"] < 0.25      # 小號 lay-back 在 MIDI，不在譜上


def test_music21_readback(built):
    m21 = pytest.importorskip("music21")
    res, out = built
    s = m21.converter.parse(str(out / "parts" / "trumpet_bb.musicxml"))
    snd = s.parts[0].toSoundingPitch()
    got = sorted((round(float(n.getOffsetInHierarchy(snd)), 3), n.pitch.midi) for n in snd.recurse().notes
                 if not isinstance(n, m21.harmony.ChordSymbol) and not n.duration.isGrace
                 and not (n.tie is not None and n.tie.type in ("stop", "continue")))
    want = sorted((round(e["start"], 3), e["pitch"]) for e in res["events"]["parts"]["trumpet"])
    assert got == want
