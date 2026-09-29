"""v2.2：重生 3 段有假漢字的換角度 t2v clip（不覆寫 video_out/clips/）。

用法：python regen.py [名稱前綴…]   逐一送出（一次只一個工作），已存在的候選跳過。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "video"))
from comfy_client import ClipJob, ComfyClient, snap_length  # noqa: E402

OUT = Path(__file__).resolve().parent
SECONDS = 294 / 24          # snap_length → 294f，與原檔一致
SEEDS = [2201, 2202, 2203]
# 第三章_00_7 與 00_1 提示詞相同：同 seed 會生出一模一樣的影片，所以另給 seed
SEEDS_BY_CLIP = {"第三章_00_7_294f_t": [2204, 2205, 2206]}

NO_TEXT = ("Absolutely no text anywhere in the frame: no writing, no Chinese characters, no calligraphy, "
           "no letters, no numbers, no symbols, no signage, no logos.")

LANTERN = """Slow-burn Taiwanese folk horror film, 35mm film grain, muted desaturated palette, low-key lighting, underexposed, deep shadows, damp humid air. Slow deliberate camera, no fast cuts. No people visible, no faces, no on-screen text, no subtitles, no watermark. {no_text}

The shot opens directly on this framing. The entrance of a small old Taiwanese temple at night: stone lions, plain red lanterns swaying, wet stone steps, a flooded alley gutter where black water flows into a grate. The scene is almost dark, only faint highlights remain. Heavy dark vignette at the frame edges.

Close-up of plain blank red paper lanterns swaying violently in the wind and rain, light flickering. The lanterns are completely plain: smooth faded red paper with only thin black ribs and tassels, no characters, no writing, no painted patterns, no gold lettering on them.

Audio: heavy rain, wind, lantern creaking, heavy rain drumming on tin roofs, an electrical buzz then a sudden power cut, a wooden oar creaking in dark water, a distant thunder crack. No music, no speech, no voices."""

ALTAR = """Slow-burn Taiwanese folk horror film, 35mm film grain, muted desaturated palette, low-key lighting, underexposed, deep shadows, damp humid air. Slow deliberate camera, no fast cuts. No people visible, no faces, no on-screen text, no subtitles, no watermark. {no_text}

The shot opens directly on this framing. Inside a cramped old Taoist altar room in a Taiwanese back alley: low ceiling, red altar table with incense burner and thin smoke, faded deity paintings, a fluorescent tube light, walls stained with pale salt efflorescence spreading up from damp corners like old scars, a wooden table with an old swollen paper file. Light rain falls outside, drops sliding down the window. The scene is almost dark, only faint highlights remain.

Extreme close-up of the plain bronze incense burner on the altar, thin smoke curling upward. Very slow push-in. The burner has no inscriptions. Any red paper strips beside the altar are blank, faded plain red paper with no calligraphy and no characters, and they stay dark and out of focus in the background.

Audio: quiet room tone, incense crackle, faint dripping water, the low rumble of water flowing somewhere beneath the floor, old damp paper pages rustling, soft rain. No music, no speech, no voices."""

CLIPS = {
    "第三章_00_1_294f_t": LANTERN,
    "第一章_03_5_294f_t": ALTAR,
    "第三章_00_7_294f_t": LANTERN,
}


def main(names: list[str]) -> int:
    assert snap_length(SECONDS) == 294
    cl = ComfyClient()
    if not cl.ping():
        print("ComfyUI 沒回應", flush=True)
        return 2
    todo = [n for n in CLIPS if not names or any(n.startswith(x) for x in names)]
    for name in todo:
        prompt = CLIPS[name].format(no_text=NO_TEXT)
        for seed in SEEDS_BY_CLIP.get(name, SEEDS):
            dest = OUT / f"{name}_s{seed}.mp4"
            dest.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
            if dest.exists():
                print(f"[skip] {dest.name}", flush=True)
                continue
            job = ClipJob(prompt=prompt, first_frame=None, seconds=SECONDS, width=1056, height=608,
                          seed=seed, turbo=True, prefix=f"video/anqu_v22_{name}_s{seed}")
            t0 = time.time()
            print(f"[gen] {dest.name} …", flush=True)
            try:
                pid = cl.submit(__import__("comfy_client").build_prompt(job))
                cl.download_outputs(cl.wait(pid, timeout=900), dest)
            except Exception as e:  # OOM / 逾時：停下來，不重試
                print(f"[FAIL] {dest.name}: {e}", flush=True)
                return 1
            print(f"      done in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
