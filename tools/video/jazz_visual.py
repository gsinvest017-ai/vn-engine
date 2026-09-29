"""Kalliwoda 爵士三重奏影片：分鏡 → MiniMax H3 文生影片 → 品質檢查 → clips.json / contact sheet。

用法（在 WT 根目錄）：
    python tools/video/jazz_visual.py storyboard          # 寫 P/visual/storyboard.json
    python tools/video/jazz_visual.py generate [--only intro_01 ...]   # 逐段生成，已存在就跳過
    python tools/video/jazz_visual.py qc                  # 抽幀 + OCR + 人臉偵測 → P/_render/qc/
    python tools/video/jazz_visual.py report              # 合併自動 QC + 人工判定 → clips.json、contact.png

生成規則（沿用 prompts.py / remaster.py 學到的做法）：
- 全部走 t2v（H3 的 ReferenceToVideo 會整段黏在參考圖構圖上，換角度反而做不到）。
- H3 t2v 開頭約 2.5 秒會先給一個全景再移到指定構圖，所以每段多生 HEAD 秒，剪接時從 head 之後取用；
  clips.json 的 head / usable_sec 就是給剪接端用的。
- 重生換 seed：seed = base_seed + 1000 * attempt，attempt 記在 <id>.meta.json。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

WT = Path(__file__).resolve().parents[2]
P = WT / "projects" / "kalliwoda-jazz"
VISUAL = P / "visual"
CLIPS = P / "_render" / "clips"
QC_DIR = P / "_render" / "qc"
OCR_PY = Path(r"C:\Users\User\autogo\.venv\Scripts\python.exe")

WIDTH, HEIGHT = 1056, 608
CLIP_SEC = 10.0        # 剪接端要用的長度
HEAD = 2.5             # 多生、之後剪掉的開頭
MAX_ATTEMPTS = 3

STYLE = ("Late-night lonely jazz ballad mood, like a 1950s cool-jazz record session. Shot on 35mm film, "
         "heavy film grain, almost monochrome: faded, strongly desaturated colors, only a faint hint of amber "
         "and cold teal, deep blacks, soft halation. Shallow depth of field, soft haze of smoke. Very slow, "
         "gentle camera movement, no fast cuts. Never show any face. No text, no letters, no numbers, no logos, "
         "plain unmarked signs, no neon lettering, no exit signs, no writing on windows or glass, no posters, "
         "no watermark, no subtitles.")

# 人物防線：H3 看到 "jazz bar" 會自己塞滿客人（實測 intro_01 v0 出現三四張清楚人臉），所以每鏡明講
PEOPLE = {
    "none": "Completely empty: no people anywhere in the frame, no customers, no musicians.",
    "hands": ("Tight framing on the hands only: the person's head, face and shoulders stay outside the frame "
              "for the whole shot."),
    "feet": "Only the foot and lower leg are in frame; no body above the knee, no face.",
    "silhouette": ("The only person is a small dark featureless silhouette seen from behind, face never "
                   "visible, no other people."),
}

AUDIO = {
    "bar": "quiet room tone of an empty small jazz bar, soft rain against the window, a faint glass clink",
    "street": "soft rain on wet pavement, distant city hum, a car passing far away",
    "dawn": "near silence of an empty room at dawn, a few birds far outside, distant early traffic",
}

# 每段的音樂秒數取自 score/report.json arrangement_plan（3/4 版、主題後半用刪 R22–R28 的 33 秒）
SECTIONS: list[dict] = [
    {"id": "intro", "zh": "前奏（鋼琴）", "music_sec": 30, "src": "R3-R4 motif + R84-R89 harmony",
     "mood": "夜深、雨、還沒開口的酒吧；從窗外推進室內，最後落在琴鍵",
     "shots": [
         ("street", "Night rain streaks down the large window of a small empty jazz bar seen from the street, "
          "warm amber lamps glowing inside, soft out-of-focus red and blue city lights reflected in the wet "
          "glass and in puddles below. The window glass is clear with no signs, no neon tubes, no lettering.",
          "Very slow push-in toward the window."),
         ("bar", "Wide view from a corner of a tiny empty jazz club late at night, facing the low stage and a dark "
          "back wall: a few small round tables, a black upright bass leaning in the corner, a grand piano under "
          "one amber lamp, smoke hanging in the light. No doors, no windows and no signs in view", "Slow lateral dolly across the room."),
         ("bar", "Close-up of a grand piano keyboard in dim amber light, a pair of hands resting gently on the "
          "keys and pressing a soft chord, only hands and wrists visible.", "Static, extremely slow drift.", "hands"),
     ]},
    {"id": "head_ab", "zh": "小號主題 a+b", "music_sec": 48, "src": "R3-R18",
     "mood": "小號進來；主角是那支小號與昏黃燈光，溫暖但寂寞",
     "shots": [
         ("bar", "A brass trumpet resting on an empty wooden chair on a small stage, a single warm spotlight "
          "from above, dust floating in the beam; behind the chair only a heavy dark velvet curtain fills the "
          "background, no windows, no lights with signs", "Slow push-in toward the trumpet."),
         ("bar", "Macro close-up of the trumpet bell, its polished brass reflecting the amber lamp and the "
          "blurred room, fine scratches on the metal.", "Very slow orbit around the bell."),
         ("bar", "From behind and far away, the out-of-focus dark silhouette of a musician's back and shoulder "
          "against hazy stage light, holding a trumpet, face never visible.", "Static, soft focus breathing.", "silhouette"),
         ("street", "Rain-covered bar window at night seen from inside, droplets sliding down, blurred warm and "
          "cold city lights behind the glass, a plain unmarked awning outside.", "Very slow rack focus."),
         ("bar", "A half-empty glass of whiskey on the black lid of a grand piano, ice slowly melting, a ring "
          "of water on the lacquer, lamp light glinting.", "Slow push-in."),
     ]},
    {"id": "head_a2", "zh": "主題後半 a'", "music_sec": 33, "src": "R19-R36 (cut R22-R28)",
     "mood": "三重奏的另外兩位：低音提琴與刷子；節奏感但仍然慵懶",
     "shots": [
         ("bar", "Close-up of the thick strings of an upright double bass, fingers plucking slowly, the "
          "wooden body glowing amber, shallow depth of field, only the hand visible.", "Slow tilt down along the strings.", "hands"),
         ("bar", "Wire jazz brushes sweeping slow circles on the white coated head of a snare drum, a hi-hat "
          "blurred in the background, only hands and brushes visible.", "Static low angle.", "hands"),
         ("bar", "Looking straight up at a slowly turning ceiling fan and a single hanging amber lamp, cigarette "
          "smoke drifting through the light; the dark wooden ceiling fills the whole frame, no walls in view", "Slow upward tilt."),
     ]},
    {"id": "piano_solo", "zh": "鋼琴獨奏", "music_sec": 48, "src": "changes of R3-R18",
     "mood": "聚焦琴鍵、手與琴槌；內省、流動",
     "shots": [
         ("bar", "Top-down view of piano keys, two hands playing slowly and softly, fingers moving across ivory "
          "and black keys, warm lamp light, only hands visible.", "Slow glide along the keyboard.", "hands"),
         ("bar", "Inside an open grand piano: felt hammers rising and striking the steel strings, brass tuning "
          "pins, the golden cast-iron frame, dim warm light.", "Macro, very slow push along the hammers."),
         ("bar", "Low angle along the keyboard from its end, fingers in soft focus pressing keys, the lamp "
          "glowing behind, smoke in the air.", "Static, slow rack focus from keys to hands.", "hands"),
         ("bar", "Close-up of the brass sustain pedal of a grand piano and a dark leather shoe pressing it "
          "slowly, dark wooden floor.", "Static.", "feet"),
         ("bar", "Tight close-up of the glossy black lacquer fallboard of a piano, mirror-like, reflecting two "
          "slowly moving hands above the keys; only the black lacquer, keys and hands fill the frame, "
          "the room behind is pure black", "Very slow drift.", "hands"),
     ]},
    {"id": "theme2", "zh": "小號第二主題（R49–R60 骨幹）", "music_sec": 48, "src": "R41-R44 + R49-R60",
     "mood": "小調段落：更暗、更冷，藍色街燈與雨",
     "shots": [
         ("street", "A single cold blue-white street lamp on a rainy night, seen from below beside a bare dark brick "
          "wall, rain streaking through the cone of light, a trembling puddle on the ground; no shops, no "
          "storefronts, no signs anywhere", "Slow push-in down the street."),
         ("bar", "Close-up of trumpet valves and fingers pressing them slowly, lit only by cold blue light "
          "from a window, deep shadows, only the hand visible.", "Static, slow focus pull.", "hands"),
         ("street", "Far down a rainy street, the blurred silhouette of a lone figure with an umbrella walking "
          "away from camera under cold streetlights, back view only.", "Static long lens.", "silhouette"),
         ("bar", "Close view along an empty wooden bar counter in cold blue light, a row of empty glasses, wet "
          "reflections on the wood, everything beyond the counter lost in darkness, no bottles with labels", "Slow lateral dolly along the counter."),
         ("bar", "A cigarette resting on a glass ashtray in darkness, a thin line of smoke curling upward, "
          "cold blue backlight.", "Static macro."),
     ]},
    {"id": "return", "zh": "回到主題", "music_sec": 39, "src": "R64-R76",
     "mood": "燈光回暖，但人更少了；溫柔的回憶",
     "shots": [
         ("bar", "The brass trumpet lying on top of the closed grand piano beside a lamp, warm amber light "
          "returning, dust in the air.", "Slow push-in."),
         ("bar", "Close-up of a hand sliding slowly along the neck of an upright double bass, warm amber "
          "light, only the hand visible.", "Static, soft focus.", "hands"),
         ("street", "Rain slowing down on the bar window, fewer droplets, warm interior lights reflected in "
          "the glass, blurred street outside.", "Very slow rack focus."),
         ("bar", "Medium shot of two small empty tables after hours, coats left on the chairs and half-finished "
          "drinks, heavy haze, warm lamp glow, the background dark and out of focus", "Slow pull-back."),
     ]},
    {"id": "coda", "zh": "尾聲（漸慢）", "music_sec": 45, "src": "R77-R89",
     "mood": "黎明前、空場、燈一盞一盞熄",
     "shots": [
         ("dawn", "Chairs turned upside down on small round tables, pale grey-blue dawn light falling across them "
          "from the side, dust floating in the light, the background soft and dark", "Slow lateral dolly."),
         ("dawn", "A grand piano with its lid and fallboard closed, an empty piano bench, grey dawn light on "
          "the black lacquer.", "Very slow push-in."),
         ("dawn", "A trumpet lying in an open case lined with worn velvet, soft morning light falling across "
          "the brass.", "Static top-down, slow drift."),
         ("street", "An empty city street just before dawn, wet asphalt, the streetlights switching off one by one, "
          "a pale sky, blank building facades with no shop signs, no people", "Static wide."),
         ("dawn", "A quiet city skyline before sunrise in thin fog, low grey clouds, windows dark, the last "
          "street lamps fading, a faint pale glow on the horizon.", "Very slow pull-back, fading toward white."),
     ]},
]


def shot_id(section: str, idx: int) -> str:
    return f"{section}_{idx:02d}"


def build_prompt(look: str, camera: str, audio_key: str, people: str = "none") -> str:
    look = look.rstrip()
    look = look if look.endswith(".") else look + "."
    visual = "The shot opens directly on this framing. " + look + " " + PEOPLE[people]
    audio = f"Audio: {AUDIO[audio_key]}. No music, no speech, no voices."
    return "\n\n".join([STYLE, visual, camera, audio])


def base_seed(sec_idx: int, idx: int) -> int:
    return 7100 + sec_idx * 100 + idx


def build_storyboard() -> dict:
    shots, t = [], 0.0
    for si, sec in enumerate(SECTIONS):
        n = len(sec["shots"])
        per = sec["music_sec"] / n
        for i, (akey, look, camera, *rest) in enumerate(sec["shots"], 1):
            people = rest[0] if rest else "none"
            shots.append({
                "id": shot_id(sec["id"], i), "section": sec["id"], "section_zh": sec["zh"],
                "music_start": round(t, 2), "music_sec": round(per, 2),
                "look": look, "camera": camera, "audio": akey, "people": people,
                "seed": base_seed(si, i), "gen_sec": CLIP_SEC + HEAD, "head": HEAD,
                "prompt": build_prompt(look, camera, akey, people),
            })
            t += per
    return {
        "project": "kalliwoda-jazz", "resolution": [WIDTH, HEIGHT], "model": "MiniMax H3 t2v turbo",
        "total_music_sec": round(t, 2), "clip_sec": CLIP_SEC, "head": HEAD,
        "sections": [{k: s[k] for k in ("id", "zh", "music_sec", "src", "mood")} | {"n_shots": len(s["shots"])}
                     for s in SECTIONS],
        "shots": shots,
        "notes": ["全部 t2v；剪接時從 head 秒之後取用。",
                  "H3 會一起生環境音（Audio 行），可混入極低音量的酒吧環境聲。",
                  "畫面禁止可辨識人臉與文字；片頭片尾字卡另外合成，不交給 H3。"],
    }


# ---------- 生成 ----------

def meta_path(sid: str) -> Path:
    return CLIPS / f"{sid}.meta.json"


def load_meta(sid: str) -> dict:
    try:
        return json.loads(meta_path(sid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"attempt": 0, "history": []}


def seed_for(shot: dict, attempt: int) -> int:
    return shot["seed"] + 1000 * attempt


def generate(shots: list[dict], only: set[str] | None = None, force: set[str] | None = None) -> list[dict]:
    from comfy_client import ClipJob, ComfyClient
    cl = ComfyClient()
    if not cl.ping():
        raise SystemExit("ComfyUI 沒有回應（http://127.0.0.1:8188）")
    CLIPS.mkdir(parents=True, exist_ok=True)
    log = []
    for sh in shots:
        sid = sh["id"]
        if only and sid not in only:
            continue
        mp4 = CLIPS / f"{sid}.mp4"
        meta = load_meta(sid)
        if force and sid in force and mp4.exists():
            if meta["attempt"] + 1 >= MAX_ATTEMPTS:
                print(f"[skip] {sid} 已達 {MAX_ATTEMPTS} 次上限", flush=True)
                continue
            old = CLIPS / f"{sid}.a{meta['attempt']}.mp4"
            mp4.replace(old)
            meta["history"].append({"attempt": meta["attempt"], "file": old.name, "reason": "regen"})
            meta["attempt"] += 1
        if mp4.exists():
            continue
        seed = seed_for(sh, meta["attempt"])
        (CLIPS / f"{sid}.prompt.txt").write_text(sh["prompt"] + f"\n\n# seed={seed}\n", encoding="utf-8")
        job = ClipJob(prompt=sh["prompt"], first_frame=None, seconds=sh["gen_sec"], width=WIDTH, height=HEIGHT,
                      seed=seed, turbo=True, prefix=f"video/kalliwoda/{sid}")
        t0 = time.time()
        for tries in range(3):
            try:
                cl.run(job, mp4)
                break
            except Exception as e:  # noqa: BLE001 — OOM / 暫時性錯誤：等一下再試，同一錯誤最多 3 次
                print(f"[err] {sid} try {tries + 1}: {str(e)[:300]}", flush=True)
                if tries == 2:
                    raise
                time.sleep(60)
        dt = time.time() - t0
        meta.update({"seed": seed, "gen_time_s": round(dt, 1)})
        meta_path(sid).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        log.append({"id": sid, "seed": seed, "sec": round(dt, 1)})
        print(f"[ok] {sid} seed={seed} {dt:.0f}s", flush=True)
    return log


# ---------- QC ----------

def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def sample_times(duration: float, head: float = HEAD, n: int = 3) -> list[float]:
    """head 之後的區間均勻取 n 幀（避開最後 0.3 秒）。"""
    a, b = min(head, duration * 0.5), max(duration - 0.3, head)
    if n == 1:
        return [round((a + b) / 2, 2)]
    return [round(a + (b - a) * k / (n - 1), 2) for k in range(n)]


def extract_frames(mp4: Path, times: list[float], dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    outs = []
    for k, t in enumerate(times):
        out = dest_dir / f"{mp4.stem}_f{k}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t}", "-i", str(mp4), "-frames:v", "1",
                        "-q:v", "3", str(out)], check=True)
        outs.append(out)
    return outs


def detect_faces(img_path: Path) -> list[list[int]]:
    """OpenCV Haar 正臉＋側臉；只是輔助旗標，最後以人工看圖為準。"""
    import cv2
    img = cv2.imread(str(img_path))
    if img is None:
        return []
    g = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    boxes = []
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        cc = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        for (x, y, w, h) in cc.detectMultiScale(g, scaleFactor=1.1, minNeighbors=8, minSize=(48, 48)):
            boxes.append([int(x), int(y), int(w), int(h)])
    return boxes


OCR_SCRIPT = r'''
import json, sys, os
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
from paddleocr import PaddleOCR
ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
                enable_mkldnn=False, device="cpu", lang="en")
import cv2
res = {}
for p in sys.argv[1:]:
    items = []
    img = cv2.imread(p)
    # 左右翻轉也掃一次：窗玻璃上的假字常是鏡像，正向 OCR 讀不到
    # 放大兩倍再掃：背景裡的小招牌（EXIT、霓虹字）原尺寸常漏抓
    big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    for tag, im in (("", img), ("[2x] ", big), ("[mirror] ", cv2.flip(big, 1))):
        for r in ocr.predict(im):
            for t, s in zip(r["rec_texts"], r["rec_scores"]):
                items.append([tag + t, round(float(s), 3)])
    res[p] = items
print("@@JSON@@" + json.dumps(res, ensure_ascii=False))
'''


def run_ocr(images: list[Path]) -> dict[str, list]:
    if not images:
        return {}
    script = QC_DIR / "_ocr.py"
    QC_DIR.mkdir(parents=True, exist_ok=True)
    script.write_text(OCR_SCRIPT, encoding="utf-8")
    out = subprocess.run([str(OCR_PY), str(script), *map(str, images)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=3600)
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("@@JSON@@")), None)
    if line is None:
        raise RuntimeError(f"OCR 失敗：{out.stderr[-2000:]}")
    return {Path(k).name: v for k, v in json.loads(line[8:]).items()}


def ocr_hits(items: list, min_score: float = 0.5, min_len: int = 2) -> list:
    """OCR 結果裡算「假字」的：信心夠、至少兩個英數字元。"""
    hits = []
    for t, s in items:
        alnum = sum(c.isalnum() for c in t.split("] ", 1)[-1])
        if s >= min_score and alnum >= min_len:
            hits.append([t, s])
    return hits


def qc(shots: list[dict]) -> dict:
    frames_dir = QC_DIR / "frames"
    per, imgs = {}, []
    for sh in shots:
        mp4 = CLIPS / f"{sh['id']}.mp4"
        if not mp4.exists():
            continue
        dur = probe_duration(mp4)
        fr = extract_frames(mp4, sample_times(dur, sh["head"]), frames_dir)
        imgs += fr
        per[sh["id"]] = {"duration": round(dur, 3), "frames": [f.name for f in fr],
                         "faces": {f.name: detect_faces(f) for f in fr}}
    ocr = run_ocr(imgs)
    for sid, d in per.items():
        d["ocr"] = {f: ocr.get(f, []) for f in d["frames"]}
        d["ocr_hits"] = [h for f in d["frames"] for h in ocr_hits(ocr.get(f, []))]
        d["face_flag"] = any(d["faces"].values())
    path = QC_DIR / "auto_qc.json"
    merged = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged.update(per)   # --only 只重檢部分段落時保留其他段的結果
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    return per


# ---------- 報告 ----------

def verdict(auto: dict, manual: dict) -> tuple[str, list[str]]:
    """人工判定優先；沒有人工判定時，自動旗標 → review，否則 ok。"""
    issues = list(manual.get("issues", []))
    if auto.get("ocr_hits"):
        issues.append("OCR: " + ", ".join(t for t, _ in auto["ocr_hits"]))
    if auto.get("face_flag") and not manual:
        issues.append("Haar 偵測到疑似人臉（待人工確認）")
    if manual.get("verdict"):
        return manual["verdict"], issues
    return ("review" if issues else "ok"), issues


def contact_sheet(rows: list[dict], dest: Path, cols: int = 5, tw: int = 352) -> None:
    import cv2
    import numpy as np
    th = round(tw * HEIGHT / WIDTH)
    cells = []
    for r in rows:
        f = QC_DIR / "frames" / r["frames"][len(r["frames"]) // 2] if r.get("frames") else None
        img = cv2.imread(str(f)) if f else None
        img = np.zeros((th, tw, 3), np.uint8) if img is None else cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        lab = np.full((24, tw, 3), 20, np.uint8)
        col = {"ok": (120, 200, 120), "fix": (60, 180, 230), "reject": (80, 80, 230)}.get(r["quality"], (200, 200, 200))
        cv2.putText(lab, f"{r['id']}  {r['quality']}", (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
        cells.append(np.vstack([lab, img]))
    while len(cells) % cols:
        cells.append(np.zeros_like(cells[0]))
    grid = np.vstack([np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)])
    dest.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", grid)
    dest.write_bytes(buf.tobytes())


def report(shots: list[dict]) -> list[dict]:
    auto = json.loads((QC_DIR / "auto_qc.json").read_text(encoding="utf-8"))
    mpath = VISUAL / "review_notes.json"
    manual = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    rows = []
    for sh in shots:
        sid = sh["id"]
        a = auto.get(sid)
        if a is None:
            continue
        meta = load_meta(sid)
        q, issues = verdict(a, manual.get(sid, {}))
        head = manual.get(sid, {}).get("head", sh["head"])
        rows.append({
            "id": sid, "file": f"_render/clips/{sid}.mp4", "section": sh["section"], "section_zh": sh["section_zh"],
            "desc": sh["look"], "camera": sh["camera"], "duration": a["duration"], "head": head,
            "usable_sec": round(a["duration"] - head, 2), "music_start": sh["music_start"],
            "music_sec": sh["music_sec"], "seed": meta.get("seed"), "attempts": meta.get("attempt", 0) + 1,
            "gen_time_s": meta.get("gen_time_s"), "quality": q, "issues": issues,
            "note": manual.get(sid, {}).get("note", ""), "frames": a["frames"],
        })
    (VISUAL / "clips.json").write_text(json.dumps({"clips": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    contact_sheet(rows, VISUAL / "contact.png")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["storyboard", "generate", "qc", "report"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--regen", nargs="*", help="換 seed 重生（舊檔改名保留）")
    a = ap.parse_args(argv)
    sb = build_storyboard()
    if a.cmd == "storyboard":
        VISUAL.mkdir(parents=True, exist_ok=True)
        (VISUAL / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(sb['shots'])} shots, {sb['total_music_sec']}s")
    elif a.cmd == "generate":
        only = set(a.only or []) | set(a.regen or []) or None
        generate(sb["shots"], only, set(a.regen or []))
    elif a.cmd == "qc":
        shots = [s for s in sb["shots"] if not a.only or s["id"] in a.only]
        qc(shots)
    else:
        report(sb["shots"])
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())
