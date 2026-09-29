import jazz_visual as jv
from comfy_client import build_prompt as graph_of, ClipJob, snap_length


def test_storyboard_shape():
    sb = jv.build_storyboard()
    shots = sb["shots"]
    assert 26 <= len(shots) <= 32
    for sec in sb["sections"]:
        assert 2 <= sec["n_shots"] <= 6
    ids = [s["id"] for s in shots]
    assert len(set(ids)) == len(ids)
    assert len({s["seed"] for s in shots}) == len(shots)
    # 分鏡總長對齊編曲計畫（~5 分鐘）
    assert 280 <= sb["total_music_sec"] <= 360


def test_music_timeline_contiguous():
    shots = jv.build_storyboard()["shots"]
    t = 0.0
    for s in shots:
        assert abs(s["music_start"] - t) < 0.05
        t += s["music_sec"]


def test_prompt_has_guards():
    for s in jv.build_storyboard()["shots"]:
        p = s["prompt"]
        assert "Never show any face" in p
        assert s["people"] in jv.PEOPLE and jv.PEOPLE[s["people"]] in p
        assert "no text" in p.lower() and "plain unmarked signs" in p
        assert "No music, no speech" in p
        assert "The shot opens directly on this framing." in p


def test_t2v_graph_and_length():
    s = jv.build_storyboard()["shots"][0]
    g = graph_of(ClipJob(prompt=s["prompt"], first_frame=None, seconds=s["gen_sec"], seed=s["seed"]))
    assert g["7"]["class_type"] == "MiniMaxH3ImageToVideo"
    assert "first_frame" not in g["7"]["inputs"]
    n = snap_length(s["gen_sec"])
    assert n % 17 == 5 and n / 24 >= jv.CLIP_SEC + jv.HEAD


def test_seed_for_attempts_distinct():
    s = {"seed": 7101}
    assert [jv.seed_for(s, a) for a in range(3)] == [7101, 8101, 9101]


def test_sample_times_skip_head():
    ts = jv.sample_times(12.96, 2.5)
    assert len(ts) == 3 and ts[0] == 2.5 and ts[-1] <= 12.66
    assert jv.sample_times(1.0, 2.5)[0] == 0.5


def test_ocr_hits_filter():
    items = [["A", 0.99], ["BAR", 0.9], ["~", 0.95], ["JAZZ", 0.3]]
    assert jv.ocr_hits(items) == [["BAR", 0.9]]


def test_verdict_priority():
    assert jv.verdict({}, {}) == ("ok", [])
    q, iss = jv.verdict({"ocr_hits": [["BAR", 0.9]]}, {})
    assert q == "review" and "BAR" in iss[0]
    q, iss = jv.verdict({"face_flag": True}, {"verdict": "ok", "issues": []})
    assert q == "ok" and iss == []
    q, _ = jv.verdict({}, {"verdict": "reject", "issues": ["face"]})
    assert q == "reject"


def test_ocr_hits_mirror_tag_not_counted():
    assert jv.ocr_hits([["[mirror] A", 0.9]]) == []
    assert jv.ocr_hits([["[mirror] EXIT", 0.9]]) == [["[mirror] EXIT", 0.9]]
