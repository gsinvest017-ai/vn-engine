"""影片版工具的單元測試（不需 ComfyUI）：python -m pytest tools/video -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import prompts  # noqa: E402
import render  # noqa: E402
from comfy_client import ClipJob, build_prompt, snap_length  # noqa: E402
from vns_shots import MAX_CLIP, parse, split_subtitle  # noqa: E402

STORY = Path(__file__).resolve().parents[2] / "scripts" / "taichung-anqu"


def test_snap_length_matches_workflow_grid():
    for sec in (1, 5, 7.6, 10, 15):
        n = snap_length(sec)
        assert (n - 5) % 17 == 0 and n >= sec * 24
    assert snap_length(5) == 124


def test_every_chapter_parses_into_shots_with_text():
    for ch in (1, 2, 3):
        shots = parse(STORY / f"chapter{ch}.vns")
        assert shots and all(s.lines for s in shots)
        assert all(c <= MAX_CLIP + 1e-6 for s in shots for c in s.clip_lengths())


def test_chapter1_opening_state():
    s0 = parse(STORY / "chapter1.vns")[0]
    assert s0.bg == "old_city_dusk" and s0.rain == "drizzle"
    assert s0.lines[0].text.startswith("黃昏落在舊城區")
    assert s0.lines[1].pause_before == 0.9


def test_dialogue_and_quote_kinds():
    lines = [l for s in parse(STORY / "chapter1.vns") for l in s.lines]
    assert any(l.kind == "dialogue" and l.speaker == "diao_caidi" for l in lines)
    assert any(l.kind == "quote" for l in lines)


def test_split_subtitle_respects_limit_and_keeps_text():
    text = "水泥、香灰、機油、腐爛木頭，以及夏季河水將滿未滿時浮出的土腥味，彼此疊壓，像一段始終沒有真正結束的年代。"
    parts = split_subtitle(text, 26)
    assert "".join(parts) == text
    assert all(len(p) <= 26 for p in parts)


def test_build_prompt_t2v_vs_i2v():
    t2v = build_prompt(ClipJob(prompt="x", first_frame=None))
    assert "6" not in t2v and "first_frame" not in t2v["7"]["inputs"]
    i2v = build_prompt(ClipJob(prompt="x", first_frame="a.png", turbo=False))
    assert i2v["7"]["inputs"]["first_frame"] == ["6", 0]
    assert i2v["9"]["inputs"]["steps"] == 20 and "2" not in i2v


def test_reference_job_uses_reference_node():
    g = build_prompt(ClipJob(prompt="x", first_frame=None, ref_image="r.png"))
    assert g["7"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert g["7"]["inputs"]["ref_images.ref_image_0"] == ["6", 0]
    assert "first_frame" not in g["7"]["inputs"]


def test_long_shots_cut_to_new_angles_short_shots_continue():
    shots = parse(STORY / "chapter1.vns")
    long_shot = next(s for s in shots if len(s.clip_lengths()) >= prompts.CUT_MIN_PARTS)
    n = len(long_shot.clip_lengths())
    assert not prompts.is_cut(long_shot, 0, n)
    texts = [prompts.build(long_shot, k, n) for k in range(1, n)]
    # 換角度段落走 t2v（ReferenceToVideo 會黏在參考圖構圖上），不能帶 <Picture 1>
    assert all("opens directly" in t and "<Picture 1>" not in t and "Continue the same shot" not in t
               for t in texts)
    assert len(set(texts)) == len(texts), "每個換角度的段落鏡頭描述都要不同"
    s0 = shots[0]   # 黃昏巷弄 3 段：維持接續長鏡頭
    assert not any(prompts.is_cut(s0, k, 3) for k in range(3))
    assert "Continue the same shot" in prompts.build(s0, 1, 3)


def test_cut_clips_are_generated_longer_and_trimmed(tmp_path, monkeypatch):
    """換角度段落要多生 CUT_HEAD 秒，組裝時從 CUT_HEAD 開始剪，總長不變。"""
    class FakeClient:
        def __init__(self):
            self.jobs = []

        def upload_image(self, path, name=None):
            return name or path.name

        def run(self, job, dest):
            self.jobs.append(job)
            dest.write_bytes(b"")
            return dest

    monkeypatch.setattr(render, "ff", lambda *a: None)
    planned = [p for p in render.plan([1], None) if len(p.clips) >= prompts.CUT_MIN_PARTS][:1]
    fake = FakeClient()
    segs = render.generate(planned, tmp_path, fake, (64, 64), 1, True)
    n = len(planned[0].clips)
    assert [round(h, 2) for _, h, *_ in segs] == [0.0] + [prompts.CUT_HEAD] * (n - 1)
    assert [round(j.seconds - c, 2) for j, c in zip(fake.jobs, planned[0].clips)] == [0.0] + [prompts.CUT_HEAD] * (n - 1)
    assert all(j.ref_image is None and j.first_frame is None for j in fake.jobs[1:])
    assert sum(secs for _, _, secs, *_ in segs) == sum(planned[0].clips)


def test_revisit_references_first_visit_and_rotates_angles():
    shrine = [s for s in parse(STORY / "chapter1.vns") if s.bg == "shrine_interior"]
    assert len(shrine) >= 2
    a, b = shrine[0], shrine[1]
    na, nb = len(a.clip_lengths()), len(b.clip_lengths())
    assert "Return to the same place as <Picture 1>" in prompts.build(b, 0, nb, revisit=1)
    assert "<Picture 1>" not in prompts.build(a, 0, na, revisit=0)
    assert prompts.build(a, 1, na, revisit=0) != prompts.build(b, 1, nb, revisit=1)


def test_prompts_are_english_and_forbid_onscreen_text():
    for s in parse(STORY / "chapter1.vns"):
        p = prompts.build(s, 0, 1)
        assert "no on-screen text" in p
        assert not any("一" <= ch <= "鿿" for ch in p)


def test_plan_truncates_to_max_seconds():
    planned = render.plan([1], 30)
    total = sum(sum(p.clips) for p in planned)
    assert 30 <= total < 36
    assert planned[0].title and planned[0].title.startswith("第一章")


def test_ass_has_title_and_speaker_name():
    planned = render.plan([1], None)
    ass = render.build_ass(planned, render.speaker_names(), "X")
    assert "Title,,0,0,0,,{\\fad(600,500)}第一章" in ass
    # Events 有 10 欄：Text 前要有空的 Effect 欄，否則 \fad(a,b) 的逗號會被切成欄位、字幕漏出 "500)}"
    for row in ass.splitlines():
        if row.startswith("Dialogue:"):
            assert row.split(",", 9)[9].startswith("{\\fad(")
    assert "刁才弟：你最近是不是又沒睡" in ass


def test_momentary_effects_only_in_first_part():
    s = next(s for s in parse(STORY / "chapter1.vns") if s.flicker and len(s.clip_lengths()) > 1)
    n = len(s.clip_lengths())
    assert "flickers" in prompts.build(s, 0, n)
    assert all("flickers" not in prompts.build(s, k, n) for k in range(1, n))


def test_gradual_dim_only_in_first_part():
    s = next(s for s in parse(STORY / "chapter1.vns") if s.dim >= 0.4 and len(s.clip_lengths()) > 1)
    n = len(s.clip_lengths())
    assert "gradually dims" in prompts.build(s, 0, n)
    assert all("gradually dims" not in prompts.build(s, k, n) and "almost dark" in prompts.build(s, k, n)
               for k in range(1, n))


def test_fit_to_narration_shorter_trims_without_changing_gen_lengths():
    out, speeds, gens = render.fit_to_narration([9.0, 9.0], 12.0)
    assert [round(x, 2) for x in out] == [6.0, 6.0] and speeds == [1.0, 1.0] and gens == [9.0, 9.0]


def test_fit_to_narration_stretches_then_adds_extra_clips():
    out, speeds, gens = render.fit_to_narration([10.0, 10.0], 22.0)     # 1.1 倍放慢就夠
    assert len(out) == 2 and abs(sum(out) - 22.0) < 1e-6 and abs(speeds[0] - 1.1) < 1e-6
    out, speeds, gens = render.fit_to_narration([10.0, 10.0], 40.0)     # 放慢到上限還差 15 秒 → 補 2 段
    assert abs(sum(out) - 40.0) < 1e-6
    assert len(out) == 4 and speeds[:2] == [render.MAX_STRETCH] * 2 and speeds[2:] == [1.0, 1.0]
    assert gens[:2] == [10.0, 10.0]
    # 放慢到上限後只差一點：補段最短 MIN_CLIP，既有 clip 回扣成截短，總長仍要精確
    for base, target in (([10.0], 13.0), ([10.0, 10.0], 26.0), ([9.8] * 7, 90.0), ([5.0], 30.0)):
        out, speeds, gens = render.fit_to_narration(base, target)
        assert abs(sum(out) - target) < 1e-6, (base, target, out)
        assert all(s >= 1.0 for s in speeds)
        assert gens[:len(base)] == base
        assert all(o <= g * s + 1e-6 for o, g, s in zip(out, gens, speeds)), "取用的原始長度不能超過生成長度"


def test_narrated_plan_keeps_base_clips_and_follows_audio():
    base = render.plan([1], None)
    fake = {}
    for p in base:
        for li, ln in enumerate(p.shot.lines):
            fake[render.narr_key(p.shot.chapter, p.shot.index, li)] = {"sec": len(ln.text) / 2.5}
    narrated = render.plan([1], None, fake)
    for b, n in zip(base, narrated):
        assert n.gens[:n.n_base] == b.clips, "原本的 clip 生成長度要不變，快取才用得到"
        assert abs(sum(n.clips) - n.shot.seconds) < 1e-6
    starts = [t for *_, t, _ in render.line_times(narrated)]
    assert starts == sorted(starts)
    ass = render.build_ass(narrated, render.speaker_names(), "X")
    assert "第一章" in ass
