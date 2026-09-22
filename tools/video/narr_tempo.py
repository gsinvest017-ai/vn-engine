"""旁白後處理：修掉頭尾靜音、把唸得太慢的行拉回正常語速（音高不變）。

    python tools/video/narr_tempo.py            # 在 Windows 端跑（只需 ffmpeg）

CosyVoice 用老年聲音 prompt 時，短句偶爾會拖到 1.3 字/秒（正常約 2.4）。
重新取樣也不一定救得回來，改用 ffmpeg atempo 加速（保持音高，不會變成快轉的尖聲）。
每次都從 <key>.raw.wav（第一次執行時保存的原始合成）重新處理，可重複執行、參數改了直接重跑。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import NARR_DIR  # noqa: E402

MIN_RATE = 2.1      # 字/秒，低於這個才處理
TARGET_RATE = 2.4   # 拉到這個語速（老人慢慢唸，但不拖）
MAX_TEMPO = 1.6     # 加速上限，再快就不自然


def zh_chars(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿") or len(text)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def process(key: str, rec: dict) -> dict:
    wav, raw = NARR_DIR / f"{key}.wav", NARR_DIR / f"{key}.raw.wav"
    if not raw.exists():
        shutil.copy2(wav, raw)
    # 頭尾靜音：-45 dB 以下超過 0.15 秒的剪掉（句中停頓不動）
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_duration=0.15,"
            "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_duration=0.15,areverse")
    tmp = NARR_DIR / f"{key}.trim.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", trim, str(tmp)], check=True)
    sec = duration(tmp)
    rate = zh_chars(rec["text"]) / sec
    tempo = 1.0
    if rate < MIN_RATE:
        tempo = min(TARGET_RATE / rate, MAX_TEMPO)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-af", f"atempo={tempo:.4f}",
                        str(wav)], check=True)
        tmp.unlink()
    else:
        tmp.replace(wav)
    new_sec = duration(wav)
    return {**rec, "sec": round(new_sec, 3), "raw_sec": rec.get("raw_sec", rec["sec"]),
            "tempo": round(tempo, 3), "rate": round(zh_chars(rec["text"]) / new_sec, 2)}


def main() -> int:
    index_path = NARR_DIR / "narration.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for key, rec in index.items():
        index[key] = process(key, rec)
        r = index[key]
        mark = f" tempo×{r['tempo']}" if r["tempo"] > 1 else ""
        print(f"{key} {r['raw_sec']:5.1f}s → {r['sec']:5.1f}s {r['rate']} 字/秒{mark}")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(r["sec"] for r in index.values())
    print(f"共 {len(index)} 行、{total:.0f} 秒（{total / 60:.1f} 分）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
