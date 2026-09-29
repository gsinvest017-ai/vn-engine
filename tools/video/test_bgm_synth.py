"""bgm_synth 單元測試（純 CPU、約數秒）：python -m pytest tools/video/test_bgm_synth.py -q"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import bgm_synth as B  # noqa: E402

DUR = 48.0


def fake_shots():
    """兩章、含標題卡、旁白、停頓與停電台詞的迷你分鏡（結構同 anqu_narrated.shots.json）。"""
    return [
        {"chapter": "第一章　測試", "title": "第一章　測試", "start": 0.0, "use_clips": [10.0, 10.0], "dim": 0.0,
         "sfx": [], "lines": [
             {"text": "黃昏落在舊城區。", "pause_before": 3.5, "audio_sec": 5.0, "narr_wav": "a"},
             {"text": "空氣很濕。", "pause_before": 3.0, "audio_sec": 4.0, "narr_wav": "b"}]},
        {"chapter": "第三章　夜行", "title": "第三章　夜行", "start": 20.0, "use_clips": [14.0, 14.0], "dim": 1.0,
         "sfx": ["power_failure"], "lines": [
             {"text": "暴雨來得極快。", "pause_before": 4.1, "audio_sec": 2.5, "narr_wav": "c"},
             {"text": "停電發生時，我正站在門口。", "pause_before": 0.0, "audio_sec": 6.0, "narr_wav": "d"},
             {"text": "是櫓聲。", "pause_before": 2.0, "audio_sec": 1.0, "narr_wav": "e"},
             {"text": "它只是被埋在腳下。", "pause_before": 1.0, "audio_sec": 4.0, "narr_wav": "f"}]},
    ]


@pytest.fixture(scope="module")
def rendered():
    tl = B.load_timeline(fake_shots(), DUR)
    mix, events, info = B.render(tl, seed=3)
    return tl, mix, events, info


def test_timeline_matches_render_line_rules():
    tl = B.load_timeline(fake_shots(), DUR)
    assert tl.speech[0] == pytest.approx((3.5, 8.5))
    assert tl.speech[1] == pytest.approx((8.5 + B.LINE_GAP + 3.0, 8.5 + B.LINE_GAP + 3.0 + 4.0))
    assert [n for _, n in tl.titles] == [1, 3]
    assert tl.dark_start == pytest.approx(20.0 + 4.1 + 2.5 + B.LINE_GAP)   # 「停電」那一行開口時
    assert len(tl.deep_cues) == 1
    assert tl.chapters[-1][1] == DUR


def test_length_and_format(rendered):
    tl, mix, _, _ = rendered
    assert mix.shape == (int(round(DUR * B.SR)), 2)
    assert mix.dtype == np.float32


def test_no_nan_no_clipping(rendered):
    _, mix, _, _ = rendered
    assert np.isfinite(mix).all()
    assert np.max(np.abs(mix)) < 0.9
    assert B.true_peak_db(mix.astype(np.float64)) < -1.0


def test_loudness_near_target(rendered):
    _, mix, _, _ = rendered
    lufs = B.integrated_lufs(mix.astype(np.float64))
    assert -33.0 <= lufs <= -27.0, lufs


def test_speech_is_quieter_than_gaps(rendered):
    tl, mix, events, _ = rendered
    st = B.analyze(mix, tl, events)
    assert st["rms_db_speech"] < st["rms_db_non_speech"]


def test_power_cut_is_silent(rendered):
    tl, mix, _, _ = rendered
    a = int((tl.dark_start + 0.2) * B.SR)
    b = int((tl.dark_start + 13.0) * B.SR)
    assert np.max(np.abs(mix[a:b])) < 1e-6


def test_only_three_instrument_families(rendered):
    _, _, events, _ = rendered
    assert {e.kind for e in events} <= {"bell", "bell_far", "chime", "celesta"}
    assert all(0 <= e.t < DUR for e in events)


def test_reproducible_with_seed():
    tl = B.load_timeline(fake_shots(), 20.0)
    a, ea, _ = B.render(tl, seed=11)
    b, eb, _ = B.render(tl, seed=11)
    c, _, _ = B.render(tl, seed=12)
    assert np.array_equal(a, b) and [e.t for e in ea] == [e.t for e in eb]
    assert not np.array_equal(a, c)


def test_k_weighting_reference_level():
    # BS.1770：0 dBFS 峰值的 997 Hz 正弦（單聲道放在一個聲道）約 -3.01 LUFS
    t = np.arange(B.SR * 5) / B.SR
    x = np.sin(2 * np.pi * 997 * t)
    st = np.stack([x, np.zeros_like(x)], axis=1)
    assert B.integrated_lufs(st) == pytest.approx(-3.01, abs=0.1)
