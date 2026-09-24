"""候選對照 contact sheet：每列一個版本（6 幀，OCR 框紅＝score>=0.5、黃＝<0.5），列頭標 OCR 數字與亮度。
  python contact.py <輸出.png> <eval key>...   （key = evaluate.py 產生的 eval/<key>.json）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

EVAL = Path(__file__).resolve().parent / "eval"
TW, TH = 352, 203
FONT = ImageFont.truetype("C:/Windows/Fonts/msjh.ttc", 18)


def row_img(key: str) -> Image.Image:
    data = json.load(open(EVAL / f"{key}.json", encoding="utf-8"))
    s, rows = data["summary"], data["rows"]
    by_t = {r["t"]: r for r in rows}
    frames = sorted((EVAL / key).glob("f*.jpg"))
    canvas = Image.new("RGB", (TW * 6, TH + 30), (20, 20, 20))
    d = ImageDraw.Draw(canvas)
    head = (f"{key}   OCR 框 {s.get('ocr_boxes', '-')}（score>=0.5：{s.get('ocr_boxes_s50', '-')}）"
            f"  有字幀 {s.get('frames_with_text', '-')}/{s['n_frames']}  單幀面積最大 {s.get('area_sum_per_frame_max', '-')}%"
            f"  亮度 {s['luma_mean']}（首 {s['luma_first']} 尾 {s['luma_last']}）  a/b {s['lab_mean'][1]:.0f}/{s['lab_mean'][2]:.0f}")
    d.text((6, 4), head, font=FONT, fill=(235, 235, 235))
    for k, f in enumerate(frames[:6]):
        im = Image.open(f).convert("RGB")
        t = float(f.stem.split("_")[1])
        sx, sy = TW / im.width, TH / im.height
        im = im.resize((TW, TH))
        di = ImageDraw.Draw(im)
        for b in by_t.get(t, {}).get("boxes", []):
            pts = [(x * sx, y * sy) for x, y in b["poly"]]
            di.polygon(pts, outline=(255, 40, 40) if b["score"] >= 0.5 else (255, 220, 0))
        di.text((4, TH - 22), f"{t:.1f}s", font=FONT, fill=(255, 255, 255))
        canvas.paste(im, (k * TW, 30))
    return canvas


def main(out: str, keys: list[str]) -> None:
    rows = [row_img(k) for k in keys]
    sheet = Image.new("RGB", (TW * 6, sum(r.height for r in rows) + 4 * len(rows)), (0, 0, 0))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 4
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
