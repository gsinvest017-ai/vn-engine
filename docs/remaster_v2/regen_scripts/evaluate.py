"""v2.2 候選評估：CUT_HEAD 之後 2 fps 抽幀 → PaddleOCR（CPU）文字框數與面積＋亮度色調統計，
再抽 6 幀做對照圖。以 autogo venv 執行：
  C:\\Users\\User\\autogo\\.venv\\Scripts\\python.exe evaluate.py <mp4>...   → 寫 eval/<stem>.json、eval/<stem>/f*.jpg
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

HEAD = 2.5          # prompts.CUT_HEAD
OUT = Path(__file__).resolve().parent / "eval"
_ocr = None


def ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(lang="ch", device="cpu", enable_mkldnn=False,
                         use_doc_orientation_classify=False, use_doc_unwarping=False,
                         use_textline_orientation=True, text_det_thresh=0.2, text_det_box_thresh=0.4,
                         text_rec_score_thresh=0.0, text_det_limit_side_len=1280, text_det_limit_type="max")
    return _ocr


def frames(path: Path, head: float, fps_s: float = 2.0):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    idx = list(range(int(round(head * fps)), n, int(round(fps / fps_s))))
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, im = cap.read()
        if ok:
            yield i, i / fps, im
    cap.release()


def evaluate(path: Path, head: float = HEAD, do_ocr: bool = True) -> dict:
    key = path.stem + ("_fixed" if {"clips_fixed", "fixed"} & set(path.parts) else "")
    d = OUT / key
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, t, im in frames(path, head):
        h, w = im.shape[:2]
        lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
        row = {"frame": i, "t": round(t, 2),
               "luma": round(float(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).mean()), 2),
               "lab": [round(float(x), 2) for x in lab.mean(0)],
               "p95": round(float(np.percentile(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), 95)), 1)}
        if do_ocr:
            r = ocr().predict(im)[0]
            boxes = []
            for txt, s, p in zip(r["rec_texts"], r["rec_scores"], r["rec_polys"]):
                p = np.asarray(p, np.float32)
                boxes.append({"text": txt, "score": round(float(s), 3),
                              "area": round(float(cv2.contourArea(p)) / (w * h) * 100, 3),
                              "poly": [[int(x), int(y)] for x, y in p]})
            row["boxes"] = boxes
        rows.append(row)
    # 6 幀代表幀（均分使用區間）
    sel = np.linspace(0, len(rows) - 1, 6).round().astype(int)
    cap = cv2.VideoCapture(str(path))
    for k, j in enumerate(sel):
        cap.set(cv2.CAP_PROP_POS_FRAMES, rows[j]["frame"])
        ok, im = cap.read()
        cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tofile(str(d / f"f{k}_{rows[j]['t']:05.2f}.jpg"))
    cap.release()
    summ = {"key": key, "file": str(path), "head": head, "n_frames": len(rows),
            "luma_mean": round(float(np.mean([r["luma"] for r in rows])), 2),
            "lab_mean": [round(float(x), 2) for x in np.mean([r["lab"] for r in rows], 0)],
            "p95_mean": round(float(np.mean([r["p95"] for r in rows])), 1),
            "luma_first": rows[0]["luma"], "luma_last": rows[-1]["luma"],
            "lab_first": rows[0]["lab"], "lab_last": rows[-1]["lab"],
            "sample_t": [rows[j]["t"] for j in sel]}
    if do_ocr:
        allb = [b for r in rows for b in r["boxes"]]
        strong = [b for b in allb if b["score"] >= 0.5]
        summ.update({
            "ocr_boxes": len(allb), "ocr_boxes_s50": len(strong),
            "frames_with_text": sum(1 for r in rows if r["boxes"]),
            "frames_with_text_s50": sum(1 for r in rows if any(b["score"] >= 0.5 for b in r["boxes"])),
            "area_sum_per_frame_max": round(max((sum(b["area"] for b in r["boxes"]) for r in rows), default=0), 3),
            "area_box_max": round(max((b["area"] for b in allb), default=0), 3),
            "area_mean_per_frame": round(float(np.mean([sum(b["area"] for b in r["boxes"]) for r in rows])), 3),
            "texts": sorted({b["text"] for b in allb if b["text"].strip()})[:40],
        })
    json.dump({"summary": summ, "rows": rows}, open(OUT / f"{key}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return summ


if __name__ == "__main__":
    args = sys.argv[1:]
    no_ocr = "--no-ocr" in args
    heads = {}
    paths = [Path(a) for a in args if not a.startswith("--")]
    for p in paths:
        head = HEAD if p.stem.split("_s")[0].endswith("_t") or "_t_s" in p.stem or p.stem.endswith("_t") else 0.0
        s = evaluate(p, head, do_ocr=not no_ocr)
        print(json.dumps({k: v for k, v in s.items() if k != "texts"}, ensure_ascii=False), flush=True)
