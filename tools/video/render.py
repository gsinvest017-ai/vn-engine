"""《暗渠之書》影片版渲染器：.vns → 分鏡 → ComfyUI MiniMax H3 → ffmpeg 串接 + 字幕。

用法（在 vn-engine 根目錄）：
    python tools/video/render.py --plan                         # 只印分鏡與提示詞，不生成
    python tools/video/render.py --chapters 1 --max-seconds 30  # 第一章開頭 30 秒試片
    python tools/video/render.py                                # 全三章

已生成的 clip 會快取在 <out>/clips/，重跑會跳過（改提示詞後要換 --seed 或刪檔）。
需要 ComfyUI（>= v0.37，含 MiniMax H3 節點）在 --comfy 位址運行，以及 PATH 上的 ffmpeg。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import prompts  # noqa: E402
from comfy_client import FPS, ClipJob, ComfyClient, snap_length  # noqa: E402
from vns_shots import Shot, parse, split_subtitle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "scripts" / "taichung-anqu"
BG_DIR = ROOT / "assets" / "backgrounds"
TITLE_SEC = 3.5
FADE_SEC = 0.5
# 統一恐怖片調色：H3 產出偏亮偏飽和，壓中間調、降飽和、加暗角
GRADE = "eq=saturation=0.72:gamma=0.82:contrast=1.06,vignette=angle=PI/4.5"

RES = {"low": (864, 480), "mid": (1056, 608), "high": (1280, 736)}


@dataclass
class Planned:
    shot: Shot
    title: str | None          # 章節標題卡（該章第一個 shot 才有）
    clips: list[float]         # 每段 clip 的實際使用秒數
    start: float = 0.0         # 在總時間軸上的起點


def plan(chapters: list[int], max_seconds: float | None) -> list[Planned]:
    out: list[Planned] = []
    t = 0.0
    for ch in chapters:
        shots = parse(STORY / f"chapter{ch}.vns")
        for i, s in enumerate(shots):
            title = s.chapter if i == 0 else None
            if title:
                s.lines[0].pause_before += TITLE_SEC
            clips = s.clip_lengths()
            if max_seconds is not None:
                remain = max_seconds - t
                if remain <= 0.5:
                    return out
                kept, acc = [], 0.0
                for c in clips:
                    if acc >= remain:
                        break
                    kept.append(min(c, max(remain - acc, 5.0)))
                    acc += kept[-1]
                clips = kept
            out.append(Planned(s, title, clips, t))
            t += sum(clips)
    return out


def _ts(sec: float) -> str:
    h, rem = divmod(max(sec, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Narr,{font},54,&H00E6E6E6,&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,2,0,1,2.5,1.5,2,160,160,90,1
Style: Dlg,{font},54,&H00B8E0FF,&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,2,0,1,2.5,1.5,2,160,160,90,1
Style: Quote,{font},56,&H00A0C8D8,&H000000FF,&H00000000,&H96000000,0,1,0,0,100,100,4,0,1,2.5,1.5,5,200,200,0,1
Style: Title,{font},84,&H00F0F0F0,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,8,0,1,3,0,5,100,100,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(planned: list[Planned], speakers: dict[str, str], font: str) -> str:
    rows = []
    end_all = planned[-1].start + sum(planned[-1].clips) if planned else 0
    for p in planned:
        t = p.start
        shot_end = p.start + sum(p.clips)
        if p.title:
            rows.append(f"Dialogue: 1,{_ts(t + 0.3)},{_ts(t + TITLE_SEC - 0.2)},Title,,0,0,0,,"
                        f"{{\\fad(600,500)}}{p.title}")
        for ln in p.shot.lines:
            t += ln.pause_before
            chunks = split_subtitle(ln.text)
            total_chars = sum(len(c) for c in chunks)
            for c in chunks:
                dur = ln.seconds * len(c) / total_chars
                if t >= shot_end - 0.3:
                    break
                style = {"dialogue": "Dlg", "quote": "Quote"}.get(ln.kind, "Narr")
                text = c
                if ln.kind == "dialogue" and c is chunks[0]:
                    text = f"{speakers.get(ln.speaker, ln.speaker)}：{c}"
                end = min(t + dur, shot_end, end_all)
                rows.append(f"Dialogue: 0,{_ts(t)},{_ts(end - 0.05)},{style},,0,0,0,,"
                            f"{{\\fad(250,250)}}{text}")
                t += dur
    return ASS_HEADER.format(font=font) + "\n".join(rows) + "\n"


def speaker_names() -> dict[str, str]:
    names = {}
    cur = None
    for line in (STORY / "config.yaml").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if line.startswith("  ") and not line.startswith("    ") and s.endswith(":"):
            cur = s[:-1]
        elif cur and s.startswith("name:"):
            names[cur] = s.split(":", 1)[1].strip()
    return names


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def last_frame(video: Path, dest: Path) -> Path:
    ff("-sseof", "-0.1", "-i", str(video), "-update", "1", "-frames:v", "1", str(dest))
    return dest


def generate(planned: list[Planned], out: Path, client: ComfyClient, size: tuple[int, int],
             seed: int, turbo: bool) -> list[tuple[Path, float, float, bool, bool]]:
    """逐段生成 clip；回傳 (檔案, 開頭剪掉秒數, 使用秒數, 是否 shot 開頭, 是否 shot 結尾)。"""
    clip_dir = out / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    segs = []
    place_ref: dict[str, str] = {}      # 場景 → 第一次出現時 establishing 畫面（已上傳檔名）
    visits: dict[str, int] = {}
    for p in planned:
        s = p.shot
        revisit = visits.get(s.bg, 0)
        visits[s.bg] = revisit + 1
        prev: Path | None = None
        for part, secs in enumerate(p.clips):
            cut = prompts.is_cut(s, part, len(p.clips))
            # 幀數進檔名：同一段被 --max-seconds 截短時，才不會誤用錯長度的快取；
            # 換角度（c）與接續（無後綴）的 clip 內容不同，也要分開快取
            # 重回同一場景的第一段：用第一次的全景當參考圖，房間才一致（這裡黏著原構圖反而正好）
            use_ref = part == 0 and revisit > 0 and s.bg in place_ref
            head = prompts.CUT_HEAD if cut else 0.0
            gen_secs = secs + head
            suffix = "_t" if cut else "_c" if use_ref else ""
            tag = f"{s.chapter[:3]}_{s.index:02d}_{part}_{snap_length(gen_secs)}f{suffix}"
            dest = clip_dir / f"{tag}.mp4"
            ptxt = prompts.build(s, part, len(p.clips), revisit)
            (clip_dir / f"{tag}.prompt.txt").write_text(ptxt, encoding="utf-8")
            if not dest.exists():
                first = ref = None
                if use_ref and s.bg in place_ref:
                    ref = place_ref[s.bg]
                elif part > 0 and prev is not None and not cut:
                    first = client.upload_image(last_frame(prev, clip_dir / f"{tag}.first.png"),
                                                f"anqu_{tag}_first.png")
                elif prompts.source_of(s) == "bg" and (BG_DIR / f"{s.bg}.png").exists():
                    first = client.upload_image(BG_DIR / f"{s.bg}.png", f"anqu_bg_{s.bg}.png")
                job = ClipJob(prompt=ptxt, first_frame=first, ref_image=ref, seconds=gen_secs, width=size[0],
                              height=size[1], seed=seed + s.index * 100 + part, turbo=turbo,
                              prefix=f"video/anqu_{tag}")
                t0 = time.time()
                print(f"[gen] {tag} {gen_secs:.1f}s ({snap_length(gen_secs)}f) src={'ref' if ref else 'i2v' if first else 't2v'} …", flush=True)
                client.run(job, dest)
                print(f"      done in {time.time() - t0:.0f}s", flush=True)
            else:
                print(f"[cache] {tag}", flush=True)
            segs.append((dest, head, secs, part == 0, part == len(p.clips) - 1))
            prev = dest
            if part == 0 and s.bg not in place_ref:
                ref_png = clip_dir / f"ref_{s.bg}.png"
                if not ref_png.exists():
                    ff("-i", str(dest), "-vf", r"select=eq(n\,60)", "-frames:v", "1", str(ref_png))
                place_ref[s.bg] = client.upload_image(ref_png, f"anqu_ref_{s.bg}.png")
    return segs


def assemble(segs, ass: Path, out_file: Path, size: tuple[int, int], font_dir: str | None) -> None:
    work = out_file.parent / "norm"
    work.mkdir(exist_ok=True)
    listing = []
    for i, (src, head, secs, is_first, is_last) in enumerate(segs):
        vf = [f"scale={size[0]}:{size[1]}:flags=lanczos", "setsar=1", f"fps={FPS}"]
        af = ["aresample=48000", "aformat=channel_layouts=stereo"]
        if is_first:
            vf.append(f"fade=t=in:st=0:d={FADE_SEC}")
            af.append(f"afade=t=in:st=0:d={FADE_SEC}")
        if is_last:
            vf.append(f"fade=t=out:st={secs - FADE_SEC:.3f}:d={FADE_SEC}")
            af.append(f"afade=t=out:st={secs - FADE_SEC:.3f}:d={FADE_SEC}")
        dst = work / f"{i:03d}.mp4"
        ff("-ss", f"{head:.3f}", "-i", str(src), "-t", f"{secs:.3f}", "-vf", ",".join(vf), "-af", ",".join(af),
           "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", str(dst))
        listing.append(f"file '{dst.name}'")
    (work / "list.txt").write_text("\n".join(listing), encoding="utf-8")
    joined = work / "joined.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(work / "list.txt"), "-c", "copy", str(joined))

    # 字幕燒錄 + 音量標準化（H3 環境音普遍偏小聲，約 -50 dB）
    ass_arg = ass.as_posix().replace(":", r"\:")
    sub = f"{GRADE},subtitles='{ass_arg}'" + (f":fontsdir='{font_dir}'" if font_dir else "")
    ff("-i", str(joined), "-vf", sub, "-af", "loudnorm=I=-20:TP=-2:LRA=11",
       "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_file))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapters", default="1,2,3")
    ap.add_argument("--max-seconds", type=float)
    ap.add_argument("--res", choices=RES, default="mid", help="生成解析度（輸出另外放大到 --out-res）")
    ap.add_argument("--out-res", default="1920x1080")
    ap.add_argument("--seed", type=int, default=20260921)
    ap.add_argument("--no-turbo", action="store_true", help="改用原生 20 步（慢約 2.5 倍）")
    ap.add_argument("--out", type=Path, default=ROOT / "video_out")
    ap.add_argument("--name", default="anqu")
    ap.add_argument("--font", default="Microsoft JhengHei")
    ap.add_argument("--comfy", default="http://127.0.0.1:8188")
    ap.add_argument("--plan", action="store_true", help="只輸出分鏡 JSON 與提示詞")
    a = ap.parse_args()

    chapters = [int(x) for x in a.chapters.split(",")]
    planned = plan(chapters, a.max_seconds)
    total = sum(sum(p.clips) for p in planned)
    a.out.mkdir(parents=True, exist_ok=True)

    shotlist = [{**p.shot.to_dict(), "title": p.title, "use_clips": [round(c, 2) for c in p.clips],
                 "start": round(p.start, 2),
                 "prompts": [prompts.build(p.shot, i, len(p.clips)) for i in range(len(p.clips))]}
                for p in planned]
    (a.out / f"{a.name}.shots.json").write_text(json.dumps(shotlist, ensure_ascii=False, indent=2), encoding="utf-8")
    ass = a.out / f"{a.name}.ass"
    ass.write_text(build_ass(planned, speaker_names(), a.font), encoding="utf-8")
    n_clips = sum(len(p.clips) for p in planned)
    print(f"{len(planned)} shots / {n_clips} clips / {total:.1f}s → {a.out / (a.name + '.shots.json')}")
    if a.plan:
        return 0

    client = ComfyClient(a.comfy)
    if not client.ping():
        print(f"ComfyUI 沒有回應：{a.comfy}", file=sys.stderr)
        return 2
    segs = generate(planned, a.out, client, RES[a.res], a.seed, not a.no_turbo)
    w, h = (int(x) for x in a.out_res.split("x"))
    final = a.out / f"{a.name}.mp4"
    assemble(segs, ass, final, (w, h), None)
    print(f"完成：{final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
