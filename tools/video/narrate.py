"""合成《暗渠之書》全片旁白（在 WSL 的 ~/.venv-cosy 執行）。

    ~/.venv-cosy/bin/python tools/video/narrate.py [--voice s70] [--dialogue-voice s60_chiayi]

每一行台詞（旁白 / 對白 / 引文）合成一個 wav，存在 video_out/narration/<key>.wav，
時長與發音 CER 寫進 video_out/narration/narration.json，render.py 依此排時間軸。
已存在的 wav 會跳過（改稿或換聲音要刪檔或 --force）。

聲音 prompt 由 voice_audition.py 產生在 video_out/voices/<voice>/prompt.{wav,txt}。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import ROOT, plan  # noqa: E402

VOICES = ROOT / "video_out" / "voices"
OUT = ROOT / "video_out" / "narration"
CER_FLAG = 0.20


def line_key(chapter: str, shot_index: int, line_index: int) -> str:
    return f"{chapter[:3]}_{shot_index:02d}_{line_index:02d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="s70")
    ap.add_argument("--dialogue-voice", default="s60_chiayi", help="角色對白（刁才弟）用的聲音")
    ap.add_argument("--chapters", default="1,2,3")
    ap.add_argument("--candidates", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    import soundfile as sf
    from cosy_tts import SR_OUT, Narrator

    OUT.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "narration.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}

    jobs: dict[str, list[tuple[str, str]]] = {}   # voice -> [(key, text)]
    for p in plan([int(c) for c in a.chapters.split(",")], None):
        for i, ln in enumerate(p.shot.lines):
            voice = a.dialogue_voice if ln.kind == "dialogue" else a.voice
            jobs.setdefault(voice, []).append((line_key(p.shot.chapter, p.shot.index, i), ln.text))

    for voice, items in jobs.items():
        todo = [(k, t) for k, t in items if a.force or not (OUT / f"{k}.wav").exists()]
        print(f"[{voice}] {len(items)} 行，需合成 {len(todo)} 行", flush=True)
        if not todo:
            continue
        vd = VOICES / voice
        nar = Narrator(vd / "prompt.wav", (vd / "prompt.txt").read_text(encoding="utf-8"),
                       candidates=a.candidates)
        for k, text in todo:
            audio, c, slow = nar.synth(text)
            sf.write(str(OUT / f"{k}.wav"), audio.squeeze(0).numpy(), SR_OUT)
            (OUT / f"{k}.raw.wav").unlink(missing_ok=True)   # narr_tempo 的原始備份已過期
            dur = audio.shape[1] / SR_OUT
            index[k] = {"voice": voice, "text": text, "sec": round(dur, 3), "cer": round(c, 3),
                        "rate_flags": slow}
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
            flag = "  ⚠" if c > CER_FLAG or slow else ""
            print(f"  {k} {dur:5.1f}s CER={c:.2f}{flag} {text[:24]}", flush=True)
        del nar

    total = sum(v["sec"] for v in index.values())
    bad = [k for k, v in index.items() if v["cer"] > CER_FLAG]
    print(f"DONE 共 {len(index)} 行、{total:.0f} 秒；CER>{CER_FLAG} 的行：{bad or '無'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
