"""合成《暗渠之書》全片旁白（在 WSL 的 ~/.venv-cosy 執行）。

    ~/.venv-cosy/bin/python tools/video/narrate.py [--voice s70_C] [--dialogue-voice s60_chiayi]

合成單位是「段」（block）：同一個 shot、同一個聲音的相鄰台詞，湊到 BLOCK_MIN 字以上才合成一次。
CosyVoice 單獨唸短句（「是櫓聲。」「雨愈下愈大。」）常常只吐出底噪，接著前後文一起唸就穩。
字幕仍逐行出現：render.load_narration 依字數把段落音檔的時間分給每一行。

輸出：video_out/narration/<段首行 key>.wav 與 narration.json（{段首 key: {lines, texts, sec, cer, ...}}）。
段落文字沒變且 wav 存在就跳過；段落組成改了會自動重合成，併進別段的舊檔會被清掉。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import NARR_DIR, ROOT, narr_key, plan  # noqa: E402

VOICES = ROOT / "video_out" / "voices"
OUT = NARR_DIR
CER_FLAG = 0.20
BLOCK_MIN = 16       # 段落最少字數
SHORT_LINE = 10      # 比這短的台詞一律往前一段併（除非換聲音或換 shot）
BLOCK_MAX = 80


def zh(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def build_blocks(chapters: list[int], voice: str, dialogue_voice: str) -> list[dict]:
    blocks: list[dict] = []
    for p in plan(chapters, None):
        cur: dict | None = None
        for i, ln in enumerate(p.shot.lines):
            v = dialogue_voice if ln.kind == "dialogue" else voice
            key = narr_key(p.shot.chapter, p.shot.index, i)
            n = zh(ln.text)
            joinable = (cur is not None and cur["voice"] == v
                        and cur["chars"] + n <= BLOCK_MAX
                        and (cur["chars"] < BLOCK_MIN or n < SHORT_LINE))
            if joinable:
                cur["lines"].append(key)
                cur["texts"].append(ln.text)
                cur["chars"] += n
            else:
                cur = {"voice": v, "lines": [key], "texts": [ln.text], "chars": n}
                blocks.append(cur)
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="s70_C")
    ap.add_argument("--dialogue-voice", default="s60_chiayi", help="角色對白（刁才弟）用的聲音")
    ap.add_argument("--chapters", default="1,2,3")
    ap.add_argument("--candidates", type=int, default=5)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    blocks = build_blocks([int(c) for c in a.chapters.split(",")], a.voice, a.dialogue_voice)
    OUT.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "narration.json"
    old = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}

    # 段首以外的行不再有自己的 wav：清掉舊的逐行檔，避免之後被誤用
    heads = {b["lines"][0] for b in blocks}
    for b in blocks:
        for k in b["lines"][1:]:
            for f in (OUT / f"{k}.wav", OUT / f"{k}.raw.wav"):
                f.unlink(missing_ok=True)

    index: dict = {k: v for k, v in old.items() if k in heads}
    for k, v in index.items():          # 舊版逐行格式 → 單行段落
        v.setdefault("lines", [k])
        v.setdefault("texts", [v.pop("text", "")])
    todo = []
    for b in blocks:
        head, text = b["lines"][0], "".join(b["texts"])
        prev = index.get(head, {})
        prev_text = "".join(prev.get("texts", [prev.get("text", "")]))
        if a.force or not (OUT / f"{head}.wav").exists() or prev_text != text:
            todo.append(b)
    merged = sum(1 for b in blocks if len(b["lines"]) > 1)
    print(f"{len(blocks)} 段（{merged} 段由多行併成），需合成 {len(todo)} 段", flush=True)

    import soundfile as sf
    from cosy_tts import SR_OUT, Narrator

    for voice in sorted({b["voice"] for b in todo}):
        vd = VOICES / voice
        nar = Narrator(vd / "prompt.wav", (vd / "prompt.txt").read_text(encoding="utf-8"),
                       candidates=a.candidates)
        for b in [b for b in todo if b["voice"] == voice]:
            head, text = b["lines"][0], "".join(b["texts"])
            audio, c, slow = nar.synth(text)
            sf.write(str(OUT / f"{head}.wav"), audio.squeeze(0).numpy(), SR_OUT)
            (OUT / f"{head}.raw.wav").unlink(missing_ok=True)   # narr_post 的原始備份已過期
            dur = audio.shape[1] / SR_OUT
            index[head] = {"voice": voice, "lines": b["lines"], "texts": b["texts"],
                           "sec": round(dur, 3), "cer": round(c, 3), "rate_flags": slow}
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
            flag = "  ⚠" if c > CER_FLAG or slow else ""
            print(f"  {head} ×{len(b['lines'])} {dur:5.1f}s CER={c:.2f}{flag} {text[:24]}", flush=True)
        del nar

    total = sum(v["sec"] for v in index.values())
    bad = [k for k, v in index.items() if v["cer"] > CER_FLAG]
    print(f"DONE 共 {len(index)} 段、{total:.0f} 秒；CER>{CER_FLAG}：{bad or '無'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
