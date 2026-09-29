"""旁白後製：頭尾靜音、降調加速、變暗、殘響、音量統一（在 Windows 端跑，只需 ffmpeg）。

    python tools/video/narr_post.py

每段旁白（narration.json 的一個 block）都從 <key>.raw.wav（第一次執行時保存的原始合成）重做，
可重複執行，改了參數直接重跑。處理後的長度寫回 narration.json 的 sec，render.py 的時間軸跟著變。

聲音風格（使用者 2026-09-22 試聽選定 dark_1_C_輕）：
- 旁白：降 ~1 個半音（pitch 0.94，formant 保留，不會變怪獸聲）、快 10%（Common Voice 樣本是
  志工一字一字朗讀，克隆後語氣偏斷，加快讓字連起來），仍太慢的段再補速到 TARGET_RATE
- 刁才弟（對白）：不降調，只套同樣的暗色 EQ，兩個角色聽得出差別
- 共同：壓高頻、補低頻（黯淡壓抑）、輕微密室殘響、壓縮讓音量平穩（像貼耳低語）
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import NARR_DIR  # noqa: E402

TARGET_RATE = 2.4   # 字/秒；降調加速後還低於這個的段落，再補速
MAX_TEMPO = 1.6
MAX_RATE = 4.0      # 字/秒；超過就放慢
MIN_TEMPO = 0.7
PRESETS = {
    "narrator": {"pitch": 0.94, "tempo": 1.10},
    "dialogue": {"pitch": 1.00, "tempo": 1.00},
}
VOICE_PRESET = {"s60_chiayi": "dialogue"}          # 其他聲音都當旁白
DARK = ("highpass=f=60,lowshelf=f=160:g=3,highshelf=f=3200:g=-5,lowpass=f=6500,"
        "aecho=0.85:0.6:70|140:0.22|0.12,"
        "acompressor=threshold=-24dB:ratio=3:attack=20:release=250,"
        "loudnorm=I=-18:TP=-2")
TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_duration=0.15,"
        "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_duration=0.15,areverse")


def zh_chars(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿") or len(text)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def process(key: str, rec: dict) -> dict:
    wav, raw = NARR_DIR / f"{key}.wav", NARR_DIR / f"{key}.raw.wav"
    if not raw.exists():
        shutil.copy2(wav, raw)
    preset = PRESETS[VOICE_PRESET.get(rec.get("voice", ""), "narrator")]
    chars = zh_chars("".join(rec.get("texts", [rec.get("text", "")])))

    trimmed = NARR_DIR / f"{key}.trim.wav"
    ff("-i", str(raw), "-af", TRIM, str(trimmed))
    rate = chars / duration(trimmed) * preset["tempo"]
    tempo = preset["tempo"]
    if rate < TARGET_RATE:          # 太拖：補速
        tempo *= min(TARGET_RATE / rate, MAX_TEMPO / preset["tempo"])
    elif rate > MAX_RATE:           # 太趕（對白聲本來就快，「下面有人？」0.7 秒唸完不像受驚）：放慢
        tempo *= max(MAX_RATE / rate, MIN_TEMPO / preset["tempo"])
    chain = (f"rubberband=pitch={preset['pitch']}:tempo={tempo:.4f}:formant=preserved:pitchq=quality,"
             + DARK)
    ff("-i", str(trimmed), "-af", chain, "-ar", "24000", "-ac", "1", str(wav))
    trimmed.unlink()
    sec = duration(wav)
    return {**rec, "sec": round(sec, 3), "raw_sec": rec.get("raw_sec", rec["sec"]),
            "tempo": round(tempo, 3), "pitch": preset["pitch"], "rate": round(chars / sec, 2)}


def main() -> int:
    index_path = NARR_DIR / "narration.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for key, rec in index.items():
        index[key] = r = process(key, rec)
        print(f"{key} {r['raw_sec']:5.1f}s → {r['sec']:5.1f}s {r['rate']} 字/秒 tempo×{r['tempo']}")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(r["sec"] for r in index.values())
    print(f"共 {len(index)} 段、{total:.0f} 秒（{total / 60:.1f} 分）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
