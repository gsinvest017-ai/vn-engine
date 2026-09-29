"""jazz_render 單元測試（不需網路）：python -m pytest tools/video/test_jazz_render.py -q

- MIDI 讀寫 / 拆軌 / 移調摺疊 / 量測 / 混音主流程：純 CPU，永遠會跑（渲染器用假的正弦波取代）。
- ffmpeg 殘響與 bus：PATH 上沒有 ffmpeg 時 skip。
- 真實音色庫整合測試：sfizz_render 或 projects/kalliwoda-jazz/_assets/lib 下的音色庫不在時 skip。
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).parent))
import jazz_render as J  # noqa: E402

SR = 48000
PROJ = J.REPO / "projects" / "kalliwoda-jazz"
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _song(tmp_path: Path) -> Path:
    b = J.MidiBuilder(bpm=60)
    b.note("trumpet", 0.0, 1.0, 65, 60)
    b.note("trumpet", 1.5, 0.5, 69, 70)
    b.note("bass", 0.0, 1.9, 29, 80)
    b.note("bass", 2.0, 1.9, 36, 80)
    b.cc("bass", 0.0, 64, 0)
    b.end(4)
    b.save(tmp_path / "song.mid")
    return tmp_path / "song.mid"


# ───────────── MIDI ─────────────

def test_roundtrip_notes_and_tempo(tmp_path):
    p = _song(tmp_path)
    mf = J.read_smf(p)
    assert mf.tpb == 480
    assert [mf.track_name(i) for i in range(len(mf.tracks))] == ["conductor", "trumpet", "bass"]
    assert mf.tempo_map() == [(0, 1_000_000)]
    notes = mf.notes(1)
    assert [(round(s, 3), round(d, 3), n, v) for s, d, n, v in notes] == [(0.0, 1.0, 65, 60), (1.5, 0.5, 69, 70)]
    assert mf.end_sec() == pytest.approx(4.0)


def test_running_status_and_tempo_change(tmp_path):
    # 手寫一個 format 0：tempo 120 → 第 480 tick 改 60；note-on 用 running status，note-off 用 vel 0
    trk = bytes([0x00, 0xFF, 0x51, 0x03, 0x07, 0xA1, 0x20,       # 500000 us
                 0x00, 0x90, 60, 100,
                 0x83, 0x60, 60, 0,                             # dt=480，running status note-off
                 0x00, 0xFF, 0x51, 0x03, 0x0F, 0x42, 0x40,       # 1000000 us
                 0x00, 62, 90,                                   # running status note-on
                 0x83, 0x60, 62, 0,
                 0x00, 0xFF, 0x2F, 0x00])
    data = b"MThd" + (6).to_bytes(4, "big") + bytes([0, 0, 0, 1, 0x01, 0xE0]) + b"MTrk" + len(trk).to_bytes(4, "big") + trk
    (tmp_path / "rs.mid").write_bytes(data)
    mf = J.read_smf(tmp_path / "rs.mid")
    n = mf.notes(0)
    assert [(round(s, 3), round(d, 3), p) for s, d, p, _ in n] == [(0.0, 0.5, 60), (0.5, 1.0, 62)]


def test_same_tick_off_before_on(tmp_path):
    b = J.MidiBuilder(bpm=60)
    b.note("x", 0, 1, 60, 80)
    b.note("x", 1, 1, 60, 80)          # 同音連奏：tick 480 同時有 off 與 on
    b.save(tmp_path / "rep.mid")
    n = J.read_smf(tmp_path / "rep.mid").notes(1)
    assert len(n) == 2 and all(d == pytest.approx(1.0) for _, d, _, _ in n)


def test_split_track_init_cc_and_fold(tmp_path):
    mf = J.read_smf(_song(tmp_path))
    idx = J.find_track(mf, "bass")
    assert idx == 2 and J.find_track(mf, "TRUMP") == 1
    with pytest.raises(KeyError):
        J.find_track(mf, "piano")
    st = J.split_track(mf, idx, tail_sec=2.0, init_cc={"64": 0, "7": 100})
    assert len(st.tracks) == 2
    assert any(m[:2] == b"\xff\x51" for _, m in st.tracks[0])
    ccs = [(t, m[1], m[2]) for t, m in st.tracks[1] if m[0] & 0xF0 == 0xB0]
    assert (0, 64, 0) in ccs and (0, 7, 100) in ccs
    assert st.end_sec() == pytest.approx(mf.end_sec() + 2.0, abs=0.01)
    folded = J.MidiFile(mf.tpb, list(mf.tracks))
    folded.tracks[idx] = J.fold_notes(mf, idx, 33, 72, transpose=12)
    assert [n for _, _, n, _ in folded.notes(idx)] == [41, 48]
    folded.tracks[idx] = J.fold_notes(mf, idx, 33, 45)
    assert [n for _, _, n, _ in folded.notes(idx)] == [29 + 12, 36]     # 29 低於 33 → 往上摺一個八度


# ───────────── 音訊工具 / 量測 ─────────────

def test_pan_gain_equal_power():
    x = np.ones((10, 2)) * 0.5
    c = J.pan_gain(x, 0.0, 0.0)
    assert np.allclose(c, 0.5)                       # 置中時兩聲道各保持原值
    left = J.pan_gain(x, -1.0, 0.0)
    assert np.allclose(left[:, 1], 0, atol=1e-12) and np.allclose(left[:, 0], 0.5 * np.sqrt(2))
    assert np.allclose(J.pan_gain(x, 0.0, -6.0206), 0.25, atol=1e-4)


def test_analyze_detects_clip_gap_and_dead_note():
    t = np.arange(4 * SR) / SR
    y = 0.3 * np.sin(2 * np.pi * 220 * t)
    y[int(1.0 * SR):int(2.0 * SR)] = 0.0             # 1 秒空白
    y[int(3.5 * SR):int(3.5 * SR) + 50] = 1.0        # 爆音
    x = np.stack([y, y], axis=1)
    notes = [(0.0, 0.5, 57, 80), (1.2, 0.5, 60, 80), (2.5, 0.5, 62, 80)]
    r = J.analyze_audio(x, SR, notes)
    assert r["clipped_samples"] >= 100
    assert r["longest_internal_silence_s"] == pytest.approx(1.0, abs=0.06)
    assert [d["pitch"] for d in r["dead_notes"]] == [60]
    assert r["pitch_range"] == [57, 62]
    assert r["band_energy_pct"]["low_60_250"] > 90


def test_load_wav_int16_mono_and_resample(tmp_path):
    y = (0.5 * np.sin(2 * np.pi * 440 * np.arange(44100) / 44100) * 32767).astype(np.int16)
    wavfile.write(tmp_path / "m.wav", 44100, y)
    x = J.load_wav(tmp_path / "m.wav", SR)
    assert x.shape[1] == 2 and abs(len(x) - SR) <= 2
    assert np.max(np.abs(x)) == pytest.approx(0.5, abs=0.01)


def test_convolve_reverb_numpy_length():
    send = np.zeros((SR, 2))
    send[0] = 1.0
    ir = np.random.default_rng(0).standard_normal((SR // 2, 2)) * 0.01
    wet = J.convolve_reverb(send, ir, SR, use_ffmpeg=False)
    assert wet.shape == (SR + SR // 2 - 1, 2)
    assert np.allclose(wet[: SR // 2], ir, atol=1e-9)


@pytest.mark.skipif(not HAS_FFMPEG, reason="需要 ffmpeg")
def test_convolve_reverb_ffmpeg_matches_numpy():
    rng = np.random.default_rng(1)
    send = rng.standard_normal((SR // 2, 2)) * 0.05
    ir = rng.standard_normal((SR // 4, 2)) * np.exp(-np.arange(SR // 4) / 2000)[:, None] * 0.05
    a = J.convolve_reverb(send, ir, SR, use_ffmpeg=True)
    b = J.convolve_reverb(send, ir, SR, use_ffmpeg=False)
    corr = np.corrcoef(a[:, 0], b[:, 0])[0, 1]
    assert corr > 0.99
    assert J.db(np.sqrt(np.mean(a ** 2))) == pytest.approx(J.db(np.sqrt(np.mean(b ** 2))), abs=1.0)


@pytest.mark.skipif(not HAS_FFMPEG, reason="需要 ffmpeg")
def test_bus_process_respects_limit(tmp_path):
    t = np.arange(2 * SR) / SR
    x = np.stack([0.9 * np.sin(2 * np.pi * 100 * t)] * 2, axis=1)
    y = J.bus_process(x, "threshold=0.125:ratio=2:attack=25:release=300", 12.0, -1.0, tmp_path / "o.wav")
    assert np.max(np.abs(y)) <= 10 ** (-1.0 / 20) + 0.01


# ───────────── 主流程（假渲染器）─────────────

def _fake_render(instrument, midi, wav, sr, sfizz, extra_args=None):
    mf = J.read_smf(midi)
    n = int((mf.end_sec() + 0.5) * sr)
    y = np.zeros(n)
    for s, d, p, v in mf.notes(1):
        a, b = int(s * sr), int((s + d) * sr)
        tt = np.arange(b - a) / sr
        y[a:b] += (v / 127) * 0.3 * np.sin(2 * np.pi * 440 * 2 ** ((p - 69) / 12) * tt) * np.exp(-tt * 2)
    wav.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(wav), sr, np.stack([y, y], axis=1).astype(np.float32))


def test_render_pipeline_with_fake_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "render_stem", _fake_render)
    mid = _song(tmp_path)
    (tmp_path / "a.sfz").write_text("<region> sample=x.wav\n")
    cfg = {"tail_sec": 1.0,
           "tracks": [{"name": "trumpet", "sfz": "a.sfz", "pan": -0.3, "reverb_send": 0.3},
                      {"name": "bass", "sfz": "a.sfz", "gain_db": -3, "transpose": 12, "fold_range": [33, 72]}],
           "reverb": {"engine": "numpy", "t60_low": 0.8, "t60_high": 0.4},
           "bus": {"compressor": "threshold=0.125:ratio=2:attack=25:release=300", "limit_db": -1.0},
           "target_lufs": -18.0}
    if not HAS_FFMPEG:
        cfg["bus"]["compressor"] = ""
    rep = J.render(mid, cfg, tmp_path / "out", tmp_path)
    out = tmp_path / "out"
    for f in ("stems/trumpet.wav", "stems/bass.wav", "stems_midi/bass.mid", "premix.wav", "mix.wav",
              "render_report.json"):
        assert (out / f).exists(), f
    assert rep["tracks"]["bass"]["pitch_range"] == [41, 48]         # transpose +12 生效
    assert rep["tracks"]["trumpet"]["dead_notes"] == []
    assert rep["mix"]["clipped_samples"] == 0
    if HAS_FFMPEG:
        assert rep["mix"]["lufs_integrated"] == pytest.approx(-18.0, abs=0.6)
    json.loads((out / "render_report.json").read_text(encoding="utf-8"))


def test_missing_instrument_raises(tmp_path):
    mid = _song(tmp_path)
    cfg = {"tracks": [{"name": "trumpet", "sfz": "nope.sfz"}]}
    with pytest.raises(FileNotFoundError):
        J.render(mid, cfg, tmp_path / "out", tmp_path)


# ───────────── 真實音色庫整合（缺庫就 skip）─────────────

REAL_CFG = PROJ / "sound" / "render_config.json"


def _real_available():
    if not REAL_CFG.exists() or not J.find_sfizz():
        return False
    cfg = json.loads(REAL_CFG.read_text(encoding="utf-8"))
    return all((REAL_CFG.parent / t["sfz"]).exists() for t in cfg["tracks"])


@pytest.mark.skipif(not _real_available(), reason="缺 sfizz_render 或 _assets/lib 音色庫")
def test_real_libraries_short_render(tmp_path):
    cfg = json.loads(REAL_CFG.read_text(encoding="utf-8"))
    cfg["tail_sec"] = 2.0
    b = J.MidiBuilder(bpm=60)
    b.note("trumpet", 0.05, 1.5, 65, 60)
    for n in (57, 60, 64, 67):
        b.note("piano", 0, 2, n, 50)
    b.note("bass", 0, 1.8, 29, 80)
    b.note("brush", 0, 1.9, 24, 70)
    b.note("brush", 1, 0.3, 38, 50)
    b.note("hihat", 1, 0.2, 44, 55)
    b.note("hihat", 0, 0.3, 51, 40)
    b.end(2.5)
    mid = tmp_path / "t.mid"
    b.save(mid)
    rep = J.render(mid, cfg, tmp_path / "out", REAL_CFG.parent)
    for name, t in rep["tracks"].items():
        assert t["dead_notes"] == [], name
        assert t["clipped_samples"] == 0, name
        assert t["peak_dbfs"] > -70, name
    assert rep["mix"]["clipped_samples"] == 0
    assert rep["mix"]["true_peak_dbtp"] <= -0.5
