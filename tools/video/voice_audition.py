"""從 Common Voice zh-TW（CC0）挑老年男聲，做成 CosyVoice2 prompt 並合成試聽檔。

在 WSL 執行：
    ~/.venv-cosy/bin/python tools/video/voice_audition.py <候選分析 json> <clips 目錄> [out 目錄]

候選分析 json：{speaker: [{path, sec, snr, text, ...}, ...]}（依 SNR 由高到低）。
每位講者取 SNR 最高的幾段串成 8–15 秒 prompt（段間 0.3 秒靜音），逐字稿用原句串接。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

SAMPLE = ("黃昏落在舊城區時，總有一種潮濕的重量。"
          "從第三市場往東走，穿過幾條被機車與鐵窗占滿的小巷，空氣會慢慢變得不同。")
PROMPT_MIN, PROMPT_MAX = 8.0, 15.0


def build_prompt(items: list[dict], clips: Path, out_dir: Path, max_sec: float = PROMPT_MAX,
                 denoise: bool = False) -> tuple[Path, str]:
    import numpy as np
    import soundfile as sf
    import librosa

    chosen, total = [], 0.0
    for it in items:
        if total >= max(PROMPT_MIN, max_sec - 3):
            break
        if total + it["sec"] > max_sec and chosen:
            continue
        chosen.append(it)
        total += it["sec"]
    pieces, gap = [], np.zeros(int(0.3 * 16000), dtype="float32")
    for it in chosen:
        y, _ = librosa.load(str(clips / it["path"]), sr=16000)
        y, _ = librosa.effects.trim(y, top_db=35)
        pieces += [y, gap]
    wav = np.concatenate(pieces[:-1])
    wav = wav / max(1e-6, float(np.abs(wav).max())) * 0.9
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "prompt.wav"
    sf.write(str(p), wav, 16000)
    if denoise:
        # 原始錄音底噪大（SNR ~15 dB）時先降噪，否則 CosyVoice 會連雜音一起學、合成也不穩
        raw = out_dir / "prompt.raw.wav"
        p.replace(raw)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
                        "-af", "highpass=f=70,afftdn=nr=18:nf=-40,loudnorm=I=-20:TP=-2", "-ar", "16000",
                        str(p)], check=True)
    text = "，".join(it["text"].rstrip("。！？，") for it in chosen) + "。"
    (out_dir / "prompt.txt").write_text(text, encoding="utf-8")
    (out_dir / "source.json").write_text(json.dumps(
        {"license": "CC0-1.0", "corpus": "Mozilla Common Voice 27.0 zh-TW",
         "clips": [it["path"] for it in chosen]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return p, text


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis")
    ap.add_argument("clips")
    ap.add_argument("out", nargs="?", default=str(Path(__file__).resolve().parents[2] / "video_out" / "voices"))
    ap.add_argument("only", nargs="?", default="")
    ap.add_argument("--max-prompt", type=float, default=PROMPT_MAX)
    ap.add_argument("--denoise", action="store_true")
    a = ap.parse_args()
    analysis = json.loads(Path(a.analysis).read_text(encoding="utf-8"))
    clips, out = Path(a.clips), Path(a.out)
    only = set(a.only.split(",")) if a.only else None

    import soundfile as sf
    from cosy_tts import SR_OUT, Narrator

    for spk, items in analysis.items():
        if only and spk not in only:
            continue
        d = out / spk
        wav, text = build_prompt(items, clips, d, a.max_prompt, a.denoise)
        print(f"[{spk}] prompt {sf.info(str(wav)).duration:.1f}s：{text}", flush=True)
        nar = Narrator(wav, text, candidates=3)
        audio, c, _ = nar.synth(SAMPLE)
        dest = d / "sample.wav"
        sf.write(str(dest), audio.squeeze(0).numpy(), SR_OUT)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(dest),
                        "-af", "loudnorm=I=-18:TP=-2", str(d / "sample.mp3")], check=True)
        print(f"[{spk}] sample {audio.shape[1] / SR_OUT:.1f}s CER={c:.2f} → {d / 'sample.mp3'}", flush=True)
        del nar
    return 0


if __name__ == "__main__":
    sys.exit(main())
