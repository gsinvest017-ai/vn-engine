"""jazz_arrange.py 的測試：和聲解析／重配、voicing、小號改寫、整份編曲的結構與可重現性、SFZ 產生、EQ。"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import jazz_arrange as ja  # noqa: E402
import jazz_render as jr  # noqa: E402

SCORE = ja.PROJ / "score"
HAVE_SCORE = (SCORE / "solo_romanze.mid").exists() and (SCORE / "harmony.json").exists()


# ───────── 樂理小工具 ─────────

@pytest.mark.parametrize("sym,exp", [
    ("Ab", (8, "", None)), ("Ab7/Gb", (8, "7", 6)), ("Bbm7/Db", (10, "m7", 1)), ("Adim7", (9, "dim7", None)),
    ("Dbmaj7/C", (1, "maj7", 0)), ("F#m7b5", (6, "m7b5", None)), ("Cb/Eb", (11, "", 3)),
])
def test_parse_symbol(sym, exp):
    assert ja.parse_symbol(sym) == exp


def test_parse_symbol_rejects_garbage():
    with pytest.raises(ValueError):
        ja.parse_symbol("H7")


def test_swing_pos():
    assert ja.swing_pos(1.5, 0.63) == pytest.approx(1.63)
    assert ja.swing_pos(2.0, 0.63) == 2.0
    assert ja.swing_pos(0.25, 0.6) == pytest.approx(0.3)
    assert ja.swing_pos(0.333, 0.63) == 0.333          # 三連音不動


def test_nearest_respects_range():
    assert ja.nearest(3, 40, 31, 50) == 39
    assert ja.nearest(3, 60, 31, 50) == 39
    assert ja.nearest(0, 10, 31, 50) == 36


def test_base_quality_rules():
    eb = (3, False)
    assert ja._base_quality(3, "", eb, None, False) == "maj7"          # I
    assert ja._base_quality(8, "", eb, None, False) == "maj7#11"       # IV → lydian
    assert ja._base_quality(10, "", eb, 3, False) == "dom"             # V 三和弦 → 屬七
    assert ja._base_quality(8, "m", eb, None, False) == "m6"           # 借用 iv
    assert ja._base_quality(7, "7", eb, 0, True) == "alt"              # 往小和弦解決 → altered
    assert ja._base_quality(7, "7", (0, True), 0, True) == "alt"       # 小調 V


# ───────── voicing ─────────

@pytest.mark.parametrize("qual", ["maj7", "69", "dom", "alt", "m7", "m6", "sus"])
def test_voicing_rootless_and_in_range(qual):
    rng = random.Random(0)
    prev = None
    for root in range(12):
        ch = ja.Chord(root, qual, root)
        v = ja.voicing(ch, prev, rng)
        prev = v
        assert len(v) == 4
        assert 50 <= min(v) <= 61 and max(v) <= 72
        if qual != "sus":
            assert root not in {p % 12 for p in v}, (qual, root, v)   # 左手不彈根音


def test_voicing_voice_leading_small():
    rng = random.Random(1)
    a = ja.voicing(ja.Chord(5, "m7", 5), None, rng, allow_q=False)       # Fm7
    b = ja.voicing(ja.Chord(10, "dom", 10), a, rng)                       # Bb13
    moved = sum(abs(x - y) for x, y in zip(sorted(a), sorted(b)))
    assert moved <= 8, (a, b)


# ───────── 小號 ─────────

def test_skeletonize_keeps_run_ends():
    run = [(0.0, 1.0, 60), (1.0, 0.25, 62), (1.25, 0.25, 64), (1.5, 0.25, 65), (1.75, 0.25, 67), (2.0, 1.0, 69)]
    sk = ja.skeletonize(run)
    assert [p for _, _, p in sk] == [60, 62, 67, 69]
    assert sk[1] == (1.0, 0.75, 62)


def test_rewrite_rhythm_swings_offbeats_and_keeps_order():
    notes = [ja.Note(0.0, 0.5, 60), ja.Note(0.5, 0.5, 62), ja.Note(1.0, 2.0, 64)]
    ja.rewrite_rhythm(notes, 0.63, random.Random(0), p_variant=1.0)
    assert notes[1].start == pytest.approx(0.63)
    assert [n.pitch for n in notes] == [60, 62, 64]


def test_ornament_keeps_skeleton_order():
    rng = random.Random(3)
    base = [ja.Note(0.0, 2.0, 67), ja.Note(2.0, 2.0, 70), ja.Note(4.0, 2.0, 67), ja.Note(6.0, 2.0, 63)]
    out = ja.ornament([ja.Note(n.start, n.dur, n.pitch) for n in base], ja.key_scale(3, False), rng, 1.0, 1.0)
    assert [n.pitch for n in out if not n.tag] == [n.pitch for n in base]
    assert any(n.tag == "grace" for n in out) and any(n.tag == "passing" for n in out)
    s = sorted(out, key=lambda n: n.start)
    for a, b in zip(s, s[1:]):
        assert a.end <= b.start + 1e-6


def test_dedupe_overlaps():
    ns = [ja.Note(0, 2, 60), ja.Note(1, 1, 60), ja.Note(0, 3, 62)]
    ja.dedupe_overlaps(ns)
    assert ns[0].end <= 1.0 and ns[2].dur == 3


# ───────── 整份編曲 ─────────

@pytest.fixture(scope="module")
def built():
    if not HAVE_SCORE:
        pytest.skip("缺 score/solo_romanze.mid 或 harmony.json")
    return ja.build(seed=7)


def test_build_structure_and_length(built, tmp_path):
    meta = ja.write_outputs(built, tmp_path)
    secs = meta["sections"]
    assert [s["name"] for s in secs] == [s["name"] for s in ja.PLAN]
    for a, b in zip(secs, secs[1:]):
        assert a["end_s"] == pytest.approx(b["start_s"])
        assert b["bars"][0] == a["bars"][1] + 1
    assert 300 <= meta["total_s"] <= 360, meta["total_s"]
    for s in secs:
        assert s["visual_keywords"] and s["mood"]
    mf = jr.read_smf(tmp_path / "kalliwoda_ballad.mid")
    names = [mf.track_name(i) for i in range(len(mf.tracks))]
    for t in ("trumpet", "piano", "bass", "brush", "hihat"):
        assert t in names
    ref = jr.read_smf(tmp_path / "trumpet_ref.mid")
    assert len(ref.notes(1)) == len(built["parts"]["trumpet"])
    assert (tmp_path / "leadsheet.json").exists()


def test_build_deterministic(built, tmp_path):
    a = ja.build(seed=7)
    a["builder"].save(tmp_path / "a.mid")
    built["builder"].save(tmp_path / "b.mid")
    assert (tmp_path / "a.mid").read_bytes() == (tmp_path / "b.mid").read_bytes()
    c = ja.build(seed=8)
    c["builder"].save(tmp_path / "c.mid")
    assert (tmp_path / "c.mid").read_bytes() != (tmp_path / "a.mid").read_bytes()


def test_trumpet_monophonic_in_range_and_melody_kept(built):
    tr = sorted(built["parts"]["trumpet"], key=lambda n: n.start)
    for a, b in zip(tr, tr[1:]):
        assert a.end <= b.start + 1e-6, (a, b)
    lo, hi = ja.DEFAULT_PARAMS["trumpet"]["range"]
    assert all(lo - 1 <= n.pitch <= hi for n in tr)
    # 主旋律骨幹：R3–R10 的音高順序（移到 E♭）必須原樣出現在小號（去掉裝飾音）開頭
    mel = ja.load_source_melody(SCORE / "solo_romanze.mid")
    want = [p + ja.TRANSPOSE for r in range(3, 11) for _, _, p in mel[r]]
    got = [n.pitch for n in tr if not n.tag][:len(want)]
    assert got == want


def test_clean_events_are_unhumanized(built):
    """記譜用 q_start：小號 lay-back 之前的位置（落在 swing 格上）；鼓／低音沒有抖動。"""
    ev = ja.clean_events(built)
    sw = ev["swing"]
    grid = {sw, sw / 2, sw + (1 - sw) / 2, 0.33, 0.67} | {k / 8 for k in range(9)} | {k / 6 for k in range(7)}

    def on_grid(x):
        f = x - np.floor(x + 1e-9)
        return any(abs(f - g) < 1e-3 for g in grid)

    tr = [n for n in ev["parts"]["trumpet"] if n["tag"] == ""]
    assert tr and all(on_grid(n["q_start"]) for n in tr)
    lag = [n["start"] - n["q_start"] for n in tr]
    assert 0.04 < float(np.median(lag)) < 0.25                     # 人性化只在 start，q_start 是乾淨的
    for part in ("bass", "brush", "hihat"):
        ns = [n for n in ev["parts"][part] if n["tag"] == ""]
        assert all(on_grid(n["q_start"]) for n in ns), part
    assert sum(n["mark"] == "phrase_end" for n in ev["parts"]["trumpet"]) >= 10
    assert len(ev["bars"]) == 96 and list(ev["tempo"][0]) == [0.0, 58.0]
    assert any(n["mark"] == "inner_src" for n in ev["parts"]["piano"])


def test_clean_events_do_not_change_midi(built, tmp_path):
    """加記錄欄位後，同 seed 的 MIDI 必須與既有定稿位元組相同（記錄不消耗亂數）。"""
    final = ja.PROJ / "arrangement" / "kalliwoda_ballad.mid"
    if not final.exists():
        pytest.skip("缺定稿 MIDI")
    built["builder"].save(tmp_path / "x.mid")
    assert (tmp_path / "x.mid").read_bytes() == final.read_bytes()


def test_trumpet_laid_back_on_average(built):
    tr = [n for n in built["parts"]["trumpet"] if not n.tag]
    frac = [n.start - round(n.start * 3) / 3 for n in tr]      # 相對最近三連音格
    assert np.mean(frac) > 0.02


def test_piano_comp_leaves_root_to_bass(built):
    bars = [b for b in built["bars"] if b.section == "head_ab"]
    lh = [n for n in built["parts"]["piano"] if bars[0].start <= n.start < bars[-1].start + 3 and n.pitch < 66
          and not n.tag]    # 內聲部線條（9→1）與提前彈的下一和弦除外
    hits = 0
    for n in lh:
        ch = ja.chord_at(built["bars"], n.start + 0.05)
        if ch.qual in ("maj7", "dom", "m7", "alt", "69") and n.pitch % 12 == ch.root:
            hits += 1
    assert hits <= 0.05 * len(lh)


def test_bass_in_range_and_roots_on_downbeats(built):
    bass = [n for n in built["parts"]["bass"] if not n.tag]
    lo, hi = ja.DEFAULT_PARAMS["bass"]["range"]
    assert all(lo <= n.pitch <= hi for n in bass)
    down = [n for n in bass if abs(n.start - round(n.start / 3) * 3) < 0.05]
    ok = sum(1 for n in down if n.pitch % 12 == ja.chord_at(built["bars"], n.start + 0.05).bass)
    assert ok >= 0.9 * len(down)


def test_drums_ride_only_in_piano_solo(built):
    solo = [b for b in built["bars"] if b.section == "piano_solo"]
    a, z = solo[0].start, solo[-1].start + 3
    rides = [n for n in built["parts"]["hihat"] if n.pitch == ja.KEY_RIDE]
    assert rides and all(a - 0.1 <= n.start <= z for n in rides)
    intro = [b for b in built["bars"] if b.section == "intro"]
    early = [n for n in built["parts"]["brush"] if n.start < intro[-1].start + 3]
    assert early and all(n.pitch in (ja.KEY_SWEEP, ja.KEY_SWEEP2) for n in early)   # 前奏只有掃刷


def test_tempo_map_ritardando(built):
    tm = ja.tempo_map(built["bars"], built["params"])
    assert tm[0] == (0.0, 58.0)
    bpms = [b for _, b in tm[1:]]
    assert bpms == sorted(bpms, reverse=True) and bpms[-1] < 45


# ───────── SFZ 產生 ─────────

def _touch(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def test_trumpet_combo_sfz(tmp_path):
    for n in ("C3", "G3"):
        for v in (1, 3):
            _touch(tmp_path / "sus" / f"Sum_SHTrumpet_sus_{n}_v{v}_rr1.wav")
    _touch(tmp_path / "harmonM-sus" / "Sum_SHTrumpet_harmonM-sus_C3_v1_rr1.wav")
    txt = ja.trumpet_combo_sfz(tmp_path, "x/")
    assert "hicc110=63" in txt and "locc110=64" in txt and "sample=*noise" in txt
    assert txt.count("xfin_lovel") == 2 and txt.count("xfout_lovel") == 2
    assert "pitch_keycenter=60" in txt and "pitch_keycenter=67" in txt


def test_brush_sfz_sustained_sweep(tmp_path):
    for k in (1, 2):
        _touch(tmp_path / "oh" / f"stir_dl3_rr{k}.wav")
        _touch(tmp_path / "oh" / f"stir_dl4_rr{k}.wav")
        for v in (1, 2):
            _touch(tmp_path / "oh" / f"sb_vl{v}_rr{k}.flac")
    txt = ja.brush_sfz(tmp_path, "x/")
    assert "ampeg_sustain=100" in txt and "loop_mode=no_loop" in txt
    assert f"lokey={ja.KEY_SWEEP} hikey={ja.KEY_SWEEP2}" in txt
    assert txt.count(f"key={ja.KEY_TAP} ") == 2


# ───────── jazz_render EQ ─────────

def test_highshelf_boosts_highs_only():
    sr = 48000
    t = np.arange(sr) / sr
    lo = np.sin(2 * np.pi * 200 * t)
    hi = np.sin(2 * np.pi * 6000 * t)
    x = np.stack([lo + hi, lo + hi], axis=1)
    y = jr.apply_eq(x, [{"type": "highshelf", "f": 3000, "gain_db": 6.0}], sr)
    f = np.abs(np.fft.rfft(y[sr // 2:, 0]))
    f0 = np.abs(np.fft.rfft(x[sr // 2:, 0]))
    k = lambda hz: int(hz * (sr // 2) / sr)  # noqa: E731
    assert 20 * np.log10(f[k(6000)] / f0[k(6000)]) == pytest.approx(6.0, abs=0.7)
    assert abs(20 * np.log10(f[k(200)] / f0[k(200)])) < 0.5


def test_peak_eq_and_bad_type():
    sos = jr.biquad("peak", 1000, 0.0)
    assert np.allclose(sos[0, :3], sos[0, 3:])          # 0 dB → 直通
    with pytest.raises(ValueError):
        jr.biquad("notch", 1000, 3.0)
