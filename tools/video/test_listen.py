"""listen.py 單元測試：不需網路、不需 GPU；模型或重型套件不在時自動 skip。

    python -m pytest tools/video/test_listen.py -q                 # Windows：只跑純 numpy 部分
    wsl ~/.venv-listen/bin/python -m pytest tools/video/test_listen.py -q   # WSL：含 librosa / basic-pitch / essentia
"""
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
os.environ["LISTEN_NO_WSL"] = "1"
import listen as L  # noqa: E402


def has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def notes(pitches, dur=0.5, gap=0.0, t0=0.0):
    out, t = [], t0
    for p in pitches:
        out.append({"pitch": p, "onset": t, "end": t + dur, "velocity": 80})
        t += dur + gap
    return out


MELODY = [67, 69, 71, 72, 74, 72, 71, 69, 67, 64, 65, 67]


# ---------------- 對齊 / DTW ----------------

def test_dtw_identical_is_zero():
    c, path = L.dtw(np.array([60, 62, 64]), np.array([60, 62, 64]))
    assert c == 0 and path == [(0, 0), (1, 1), (2, 2)]


def test_dtw_time_stretch_is_cheap():
    a = np.array([60, 62, 64, 65])
    b = np.repeat(a, 3)
    c, _ = L.dtw(a, b)
    assert c == 0


def test_dtw_transposed_costs_interval():
    c, _ = L.dtw(np.array([60, 60, 60]), np.array([62, 62, 62]))
    assert c == pytest.approx(2.0)


def test_compare_melody_perfect():
    r = L.compare_melody(notes(MELODY), notes(MELODY, t0=1.3))
    assert r["note_f1"] == 1.0
    assert r["time_offset_s"] == pytest.approx(1.3)
    assert not r["missing"] and not r["wrong_pitch"] and not r["extra"]
    assert r["contour_similarity"] == 1.0


def test_compare_melody_finds_wrong_missing_extra():
    est = notes(MELODY)
    est[3] = dict(est[3], pitch=73)            # 72 → 73 走音（半音）
    del est[7]                                 # 漏掉第 8 個音（69）
    est.append({"pitch": 90, "onset": 20.0, "end": 20.3, "velocity": 50})  # 多一個音
    r = L.compare_melody(notes(MELODY), est)
    assert [w["ref"] for w in r["wrong_pitch"]] == ["C5"] and r["wrong_pitch"][0]["semitones"] == 1
    assert [m["ref"] for m in r["missing"]] == ["A4"]
    assert [e["heard"] for e in r["extra"]] == ["F#6"]
    assert r["note_recall"] == pytest.approx(10 / 12, abs=1e-3)


def test_compare_melody_octave_error_flagged_separately():
    est = notes(MELODY)
    est[0] = dict(est[0], pitch=MELODY[0] - 12)
    r = L.compare_melody(notes(MELODY), est)
    assert len(r["octave_errors"]) == 1 and not r["wrong_pitch"]


def test_compare_melody_auto_transpose():
    est = [dict(n, pitch=n["pitch"] + 2) for n in notes(MELODY)]  # 降 B 調樂器記譜差大二度
    r = L.compare_melody(notes(MELODY), est, transpose="auto")
    assert r["transpose_semitones"] == 2 and r["note_f1"] == 1.0


def test_skyline_takes_top_voice_and_range():
    chord = [{"pitch": p, "onset": 0.0, "end": 1.0, "velocity": 60} for p in (48, 55, 64, 72)]
    assert [n["pitch"] for n in L.skyline(chord)] == [72]
    assert [n["pitch"] for n in L.skyline(chord, pitch_range=(40, 66))] == [64]


# ---------------- 節奏 ----------------

def _grid(bpm=60, bars=8, ratio=2.0, jitter=0.0, seed=0):
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    beats = np.arange(bars * 4 + 1) * beat
    p = ratio / (1 + ratio)
    on = np.sort(np.concatenate([beats, beats[:-1] + p * beat]) + rng.normal(0, jitter, 2 * len(beats) - 1))
    return on, beats


@pytest.mark.parametrize("ratio", [1.0, 1.5, 2.0, 3.0])
def test_swing_ratio_recovers(ratio):
    on, beats = _grid(ratio=ratio)
    r = L.swing_ratio(on, beats)
    assert r["swing_ratio"] == pytest.approx(ratio, rel=0.03)


def test_swing_ratio_straight_sixteenths_not_swung():
    beats = np.arange(33.0) * (60 / 140)
    T = 60 / 140
    on = np.sort(np.concatenate([beats + f * T for f in (0, 0.25, 0.5, 0.75)]))
    assert L.swing_ratio(on, beats)["swing_ratio"] == pytest.approx(1.0, abs=0.05)


def test_swing_ratio_mixed_phases_unreliable():
    beats = np.arange(21.0)
    on = np.sort(np.concatenate([beats, beats[:-1] + np.where(np.arange(20) % 2, 0.5, 0.75)]))
    assert L.swing_ratio(on, beats)["reliable"] is False


def test_tempo_stats_not_stuck_on_frame_grid():
    beats = np.round(np.arange(60) * (60 / 140) / 0.02) * 0.02  # 50 fps 量化
    assert L.tempo_stats(beats)["bpm"] == pytest.approx(140, abs=0.5)


def test_swing_ratio_needs_offbeats():
    beats = np.arange(10.0)
    assert L.swing_ratio(beats, beats)["swing_ratio"] is None


def test_tempo_stats_steady_and_drift():
    s = L.tempo_stats(np.arange(40) * 1.0)
    assert s["bpm"] == 60.0 and s["tempo_stability"] == "穩" and abs(s["drift_bpm_per_min"]) < 1e-6
    ibi = np.linspace(1.0, 0.8, 40)  # 越來越快
    d = L.tempo_stats(np.concatenate([[0], np.cumsum(ibi)]))
    assert d["drift_bpm_per_min"] > 0


# ---------------- DSP ----------------

def test_dsp_bright_vs_dark():
    sr = 44100
    t = np.arange(sr * 2) / sr
    dark = 0.3 * np.sin(2 * np.pi * 150 * t)
    bright = 0.3 * np.sin(2 * np.pi * 5000 * t)
    fd, fb = L.dsp_features(dark, sr), L.dsp_features(bright, sr)
    assert fd["spectral_centroid_hz"] < 400 < 4000 < fb["spectral_centroid_hz"]
    assert fd["band_energy_pct"]["low_60_250"] > 90 and fb["band_energy_pct"]["high_2k_8k"] > 90


def test_dsp_hihat_transient_higher_for_edm():
    edm = L.synth_edm(44100, 6.0)
    mel = L.synth_melody(notes(MELODY, dur=0.5), sr=44100)
    assert L.dsp_features(edm, 44100)["hihat_band_pct"] > 10 * L.dsp_features(mel, 44100)["hihat_band_pct"]


# ---------------- brief / 評語規則 ----------------

BRIEF = "Chet Baker 風爵士三重奏：小號、鋼琴、低音提琴、刷子小鼓加 hi-hat，慵懶抒情寂寥的慢板 ballad"


def test_parse_brief():
    b = L.parse_brief(BRIEF)
    assert {"小號", "鋼琴", "低音提琴", "刷子", "hi-hat"} <= set(b["instruments"])
    assert "melancholic" in b["moods"] and "relaxing" in b["moods"] and "jazz" in b["genres"]
    assert b["bpm_range"] == (48.0, 72.0)
    assert "muted jazz trumpet" in b["clap_prompt"]
    assert L.parse_brief("快一點 72 BPM")["target_bpm"] == 72.0


def test_critique_flags_edm_like_result():
    b = L.parse_brief(BRIEF)
    res = {"dsp": {"spectral_centroid_hz": 3200, "band_energy_pct": {"high_2k_8k": 30, "air_8k_20k": 10}},
           "rhythm": {"tempo": {"bpm": 140.0, "ibi_cv": 0.01}, "swing": {"swing_ratio": 1.0},
                      "onset_rate_per_s": 9.0},
           "essentia": {"instrument": {"drummachine": 0.8, "synthesizer": 0.7, "trumpet": 0.01},
                        "mood": {"energetic": 0.6, "party": 0.5, "sad": 0.01},
                        "genre_discogs400_top": [("Electronic---Techno", 0.9)]},
           "clap": {"brief_vs_anti": {"brief": 0.05, "anti_best": "fast edm", "anti_max": 0.4, "margin": -0.35}},
           "aesthetics": {"PQ": 5.1, "CE": 4.0}}
    c = L.build_critique(b, res)
    txt = " ".join(c["mismatches"])
    assert "140 BPM" in txt
    assert "drummachine" in txt and "swing" in txt and "偏亮" in txt and "CLAP" in txt
    assert any("BPM" in s for s in c["suggestions"])
    assert not any("drummachine" in m for m in c["matches"])


def test_critique_half_time_accepted_for_ballad():
    b = L.parse_brief(BRIEF)
    c = L.build_critique(b, {"rhythm": {"tempo": {"bpm": 120.0, "ibi_cv": 0.02}, "onset_rate_per_s": 2.5}})
    assert any("60 BPM" in m for m in c["matches"])


def test_critique_target_bpm_too_fast():
    b = L.parse_brief(BRIEF + "，目標 60 BPM")
    c = L.build_critique(b, {"rhythm": {"tempo": {"bpm": 72.0, "ibi_cv": 0.02}}})
    assert any("72 BPM" in m and "高於" in m for m in c["mismatches"])


def test_critique_stems_hihat_too_loud_and_trumpet_bright():
    b = L.parse_brief(BRIEF)
    stems = {"trumpet": {"rms_dbfs": -20.0, "band_energy_pct": {"high_2k_8k": 30.0, "air_8k_20k": 5.0}},
             "hihat": {"rms_dbfs": -23.0, "band_energy_pct": {}},
             "bass": {"rms_dbfs": -40.0, "band_energy_pct": {}}}
    c = L.build_critique(b, {"stems": stems})
    txt = " ".join(c["mismatches"])
    assert "hihat 太前面" in txt and "trumpet 高頻太亮" in txt and "低音提琴太小聲" in txt
    assert any("2 kHz" in s for s in c["suggestions"])


def test_markdown_has_sections():
    md = L.critique_markdown("x.wav", BRIEF, {"matches": ["a"], "mismatches": [], "suggestions": ["s"],
                                              "notes": ["n"]}, llm="模型說")
    for h in ("符合目標之處", "不符之處", "具體調整建議", "音訊語言模型", "備註"):
        assert h in md


def test_wsl_path_conversion():
    assert L._to_wsl_path(r"C:\Users\User\a b.wav") == "/mnt/c/Users/User/a b.wav"


# ---------------- 需要重型套件 / 模型（不在就 skip）----------------

@pytest.mark.skipif(not (has("librosa") and __import__("shutil").which("ffmpeg")), reason="需要 librosa + ffmpeg")
def test_beat_track_swing_on_synth(tmp_path):
    p = tmp_path / "sw.wav"
    L.write_wav(p, L.synth_swing_hats(22050, 20.0, 90.0, 2.0), 22050)
    r = L.beat_track(str(p))
    bpm = r["tempo"]["bpm"]
    assert min(abs(bpm - 90), abs(bpm - 180), abs(bpm - 45)) < 4
    if abs(bpm - 90) < 4:
        assert r["swing"]["swing_ratio"] == pytest.approx(2.0, rel=0.15)


@pytest.mark.skipif(not has("basic_pitch") or not has("onnxruntime"), reason="需要 basic-pitch + onnxruntime")
def test_transcribe_synth_melody(tmp_path):
    p = tmp_path / "m.wav"
    L.write_wav(p, L.synth_melody(notes(MELODY, dur=0.45, gap=0.05)), 22050)
    est = L.skyline(L.transcribe(str(p)), pitch_range=(60, 80))
    r = L.compare_melody(notes(MELODY, dur=0.45, gap=0.05), est)
    assert r["note_f1"] >= 0.8


@pytest.mark.skipif(not (has("essentia") and (L.DEFAULT_ESSENTIA / "discogs-effnet-bs64-1.pb").exists()),
                    reason="需要 essentia-tensorflow 與模型檔")
def test_essentia_edm_is_electronic(tmp_path):
    p = tmp_path / "edm.wav"
    L.write_wav(p, L.synth_edm(44100, 15.0), 44100)
    r = L.essentia_predict(str(p))
    assert r["genre_discogs400_top"][0][0].startswith("Electronic")


def test_critique_instrument_votes_and_llm_false_alarm():
    b = L.parse_brief(BRIEF)
    res = {"essentia": {"instrument": {"trumpet": 0.02, "brass": 0.01, "piano": 0.7}},
           "llm": {"probes": {"小號": {"yes": True, "expected": True},
                              "鋼琴": {"yes": True, "expected": True},
                              "electric guitar": {"yes": True, "expected": False}}}}
    c = L.build_critique(b, res)
    assert any("聽得到「鋼琴」" in m for m in c["matches"])
    assert any("「小號」兩個模型意見不一" in n for n in c["notes"])
    assert any("electric guitar" in m for m in c["mismatches"])


def test_critique_mood_rank_based():
    b = L.parse_brief("寂寥詭異的配樂")
    mood = {"relaxing": 0.10, "film": 0.10, "dark": 0.088, "meditative": 0.087, "happy": 0.01}
    c = L.build_critique(b, {"essentia": {"mood": mood}})
    assert any("dark" in m for m in c["matches"])


def test_yes_parser():
    assert L._yes("Yes.") is True and L._yes("no") is False and L._yes("沒有") is False and L._yes("maybe") is None


def test_brightness_db_and_baseline_rule():
    sr = 44100
    t = np.arange(sr * 2) / sr
    dull = 0.3 * np.sin(2 * np.pi * 440 * t)
    bright = dull + 0.1 * np.sin(2 * np.pi * 4000 * t)
    assert L.dsp_features(bright, sr)["brightness_db"] > L.dsp_features(dull, sr)["brightness_db"] + 20
    b = L.parse_brief(BRIEF)
    c = L.build_critique(b, {"baseline_diff": [{"name": "trumpet", "metric": "brightness_db", "delta": 7.0}]})
    assert any("trumpet 高頻比上一版亮 7.0 dB" in m for m in c["mismatches"])
    assert any("high-shelf −7 dB" in s_ for s_ in c["suggestions"])
