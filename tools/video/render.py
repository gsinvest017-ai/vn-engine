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
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import prompts  # noqa: E402
from comfy_client import FPS, ClipJob, ComfyClient, snap_length  # noqa: E402
from vns_shots import LINE_GAP, MAX_CLIP, MIN_CLIP, Shot, parse, split_subtitle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "scripts" / "taichung-anqu"
BG_DIR = ROOT / "assets" / "backgrounds"
TITLE_SEC = 3.5
FADE_SEC = 0.5
# 統一恐怖片調色：H3 產出偏亮偏飽和，壓中間調、降飽和、加暗角
GRADE = "eq=saturation=0.72:gamma=0.82:contrast=1.06,vignette=angle=PI/4.5"

RES = {"low": (864, 480), "mid": (1056, 608), "high": (1280, 736)}
NARR_DIR = ROOT / "video_out" / "narration"
MAX_STRETCH = 1.25   # 既有 clip 最多放慢到 1.25 倍，再不夠就補換角度 clip


@dataclass
class Planned:
    shot: Shot
    title: str | None          # 章節標題卡（該章第一個 shot 才有）
    clips: list[float]         # 每段 clip 在成片時間軸上的秒數
    start: float = 0.0         # 在總時間軸上的起點
    speeds: list[float] | None = None  # 放慢倍率（成片秒數 / 取用的原始秒數），None = 全 1
    gens: list[float] | None = None    # 生成長度（決定快取檔名），None = 同 clips
    n_base: int = 0            # 依字數規劃的原始段數；之後的是為了旁白補的段

    def __post_init__(self):
        self.speeds = self.speeds or [1.0] * len(self.clips)
        self.gens = self.gens or list(self.clips)
        self.n_base = self.n_base or len(self.clips)


def fit_to_narration(base: list[float], target: float) -> tuple[list[float], list[float], list[float]]:
    """把依字數規劃的 clip（base）配到旁白總長 target。
    回傳 (成片秒數, 放慢倍率, 生成長度)：
    - target ≤ base 總和：各段等比例截短（生成長度不變，快取照用）
    - 否則先放慢既有 clip（≤ MAX_STRETCH 倍），不夠的時間補新 clip（每段 MIN_CLIP–MAX_CLIP 秒）
    """
    total = sum(base)

    def scaled(k: float, extras: list[float]):
        # k ≥ 1：放慢；k < 1：截短（放慢倍率 1，只取前段）。生成長度永遠是原本的 base
        speeds = [max(k, 1.0)] * len(base) + [1.0] * len(extras)
        return [b * k for b in base] + extras, speeds, list(base) + extras

    if target <= total * MAX_STRETCH + 0.3:
        return scaled(target / total, [])          # 截短或放慢就夠（容許略超過上限 0.3 秒）
    remain = target - total * MAX_STRETCH
    n = math.ceil(remain / MAX_CLIP)
    extras = [max(remain / n, MIN_CLIP)] * n
    left = target - sum(extras)
    if left < total * 0.5:
        return scaled(target / total, [])          # 補段會把既有 clip 擠掉一半以上，不如直接放慢
    # MIN_CLIP 撐大補段後，既有 clip 的倍率回頭扣（可能 < 1 變成截短），總長仍精確等於 target
    return scaled(left / total, extras)


def load_narration() -> dict | None:
    """narration.json 是以「段」為單位（見 narrate.py）；展開成逐行：
    {行 key: {"sec": 分到的秒數, "wav": 段首才有, "pos": 在段內的序號}}。
    段落音檔依字數比例分給各行；段內非最後一行扣掉 LINE_GAP（line.seconds 會再加回來），
    讓整段的字幕總長剛好等於音檔長 + 一個行尾停頓。"""
    f = NARR_DIR / "narration.json"
    if not f.exists():
        return None
    lines: dict[str, dict] = {}
    for head, b in json.loads(f.read_text(encoding="utf-8")).items():
        keys = b.get("lines", [head])
        texts = b.get("texts", [b.get("text", "")])
        weights = [max(1, sum(1 for ch in t if "一" <= ch <= "鿿")) for t in texts]
        for i, (k, w) in enumerate(zip(keys, weights)):
            share = b["sec"] * w / sum(weights)
            last = i == len(keys) - 1
            lines[k] = {"sec": share if last else max(0.3, share - LINE_GAP),
                        "wav": head if i == 0 else None, "pos": i}
    return lines


def narr_key(chapter: str, shot_index: int, line_index: int) -> str:
    return f"{chapter[:3]}_{shot_index:02d}_{line_index:02d}"


def plan(chapters: list[int], max_seconds: float | None, narration: dict | None = None) -> list[Planned]:
    out: list[Planned] = []
    t = 0.0
    for ch in chapters:
        shots = parse(STORY / f"chapter{ch}.vns")
        for i, s in enumerate(shots):
            title = s.chapter if i == 0 else None
            if title:
                s.lines[0].pause_before += TITLE_SEC
            clips = s.clip_lengths()      # 一定要在填旁白長度之前算，快取檔名才不變
            speeds = gens = None
            if narration is not None:
                for li, ln in enumerate(s.lines):
                    rec = narration.get(narr_key(s.chapter, s.index, li))
                    if rec is None:
                        raise SystemExit(f"缺旁白：{narr_key(s.chapter, s.index, li)}（先跑 narrate.py）")
                    ln.audio_sec = rec["sec"]
                    ln.narr_wav = rec.get("wav", narr_key(s.chapter, s.index, li))
                    if rec.get("pos", 0) > 0:
                        ln.pause_before = 0.0   # 同一段音檔裡的後續行：聲音是連著的，不能再插 @wait 停頓
                n_base = len(clips)
                clips, speeds, gens = fit_to_narration(clips, s.seconds)
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
            if narration is not None:
                out.append(Planned(s, title, clips, t, speeds[:len(clips)], gens[:len(clips)], n_base))
            else:
                out.append(Planned(s, title, clips, t))
            t += sum(clips)
    return out


def line_times(planned: list[Planned]):
    """逐行產出 (planned, 行序, line, 起點秒, 本行可用秒數)；字幕與旁白混音共用同一條時間軸。"""
    for p in planned:
        t = p.start
        shot_end = p.start + sum(p.clips)
        for li, ln in enumerate(p.shot.lines):
            t += ln.pause_before
            if t >= shot_end - 0.3:
                break
            yield p, li, ln, t, min(ln.seconds, shot_end - t)
            t += ln.seconds


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
    for p in planned:
        if p.title:
            rows.append(f"Dialogue: 1,{_ts(p.start + 0.3)},{_ts(p.start + TITLE_SEC - 0.2)},Title,,0,0,0,,"
                        f"{{\\fad(600,500)}}{p.title}")
    for p, _, ln, t, avail in line_times(planned):
        chunks = split_subtitle(ln.text)
        total_chars = sum(len(c) for c in chunks)
        # 有旁白：字幕依音檔長度（不含行尾停頓）分配；沒有旁白：依字數估的長度
        speak = min(ln.audio_sec, avail) if ln.audio_sec is not None else avail
        style = {"dialogue": "Dlg", "quote": "Quote"}.get(ln.kind, "Narr")
        for c in chunks:
            dur = speak * len(c) / total_chars
            text = c
            if ln.kind == "dialogue" and c is chunks[0]:
                text = f"{speakers.get(ln.speaker, ln.speaker)}：{c}"
            rows.append(f"Dialogue: 0,{_ts(t)},{_ts(t + dur - 0.05)},{style},,0,0,0,,"
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


def clip_specs(planned: list[Planned]) -> list[dict]:
    """不連 ComfyUI 的分段清單（檔名規則與 generate() 相同）：
    {tag, head, secs（取用原始秒數）, speed, out（成片秒數）, first, last, kind（head/cont/cut/ref）, shot, part}。"""
    out, visits = [], {}
    for si, p in enumerate(planned):
        s = p.shot
        revisit = visits.get(s.bg, 0)
        visits[s.bg] = revisit + 1
        for part, (secs, speed, gen) in enumerate(zip(p.clips, p.speeds, p.gens)):
            cut = prompts.is_cut(s, part, p.n_base) if part < p.n_base else bool(prompts.ANGLES.get(s.bg))
            use_ref = part == 0 and revisit > 0      # generate() 裡 place_ref 在該場景第一次出現後一定有值
            head = prompts.CUT_HEAD if cut else 0.0
            suffix = "_t" if cut else "_c" if use_ref else ""
            tag = f"{s.chapter[:3]}_{s.index:02d}_{part}_{snap_length(gen + head)}f{suffix}"
            kind = "cut" if cut else "ref" if use_ref else "cont" if part > 0 else "head"
            out.append(dict(tag=tag, head=head, secs=secs / speed, speed=speed, out=secs, first=part == 0,
                            last=part == len(p.clips) - 1, kind=kind, shot=si, part=part))
    return out


def generate(planned: list[Planned], out: Path, client: ComfyClient, size: tuple[int, int],
             seed: int, turbo: bool) -> list[tuple[Path, float, float, float, bool, bool]]:
    """逐段生成 clip；回傳 (檔案, 開頭剪掉秒數, 取用原始秒數, 放慢倍率, 是否 shot 開頭, 是否 shot 結尾)。"""
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
        for part, (secs, speed, gen) in enumerate(zip(p.clips, p.speeds, p.gens)):
            # 原本規劃的段落照舊（快取檔名不變）；為了旁白補的段落，有角度清單就換角度，沒有就接續
            if part < p.n_base:
                cut = prompts.is_cut(s, part, p.n_base)
            else:
                cut = bool(prompts.ANGLES.get(s.bg))
            # 幀數進檔名：同一段被 --max-seconds 截短時，才不會誤用錯長度的快取；
            # 換角度（c）與接續（無後綴）的 clip 內容不同，也要分開快取
            # 重回同一場景的第一段：用第一次的全景當參考圖，房間才一致（這裡黏著原構圖反而正好）
            use_ref = part == 0 and revisit > 0 and s.bg in place_ref
            head = prompts.CUT_HEAD if cut else 0.0
            gen_secs = gen + head
            suffix = "_t" if cut else "_c" if use_ref else ""
            tag = f"{s.chapter[:3]}_{s.index:02d}_{part}_{snap_length(gen_secs)}f{suffix}"
            dest = clip_dir / f"{tag}.mp4"
            ptxt = prompts.build(s, part, p.n_base, revisit, cut=cut)
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
            segs.append((dest, head, secs / speed, speed, part == 0, part == len(p.clips) - 1))
            prev = dest
            if part == 0 and s.bg not in place_ref:
                ref_png = clip_dir / f"ref_{s.bg}.png"
                if not ref_png.exists():
                    ff("-i", str(dest), "-vf", r"select=eq(n\,60)", "-frames:v", "1", str(ref_png))
                place_ref[s.bg] = client.upload_image(ref_png, f"anqu_ref_{s.bg}.png")
    return segs


def narration_events(planned: list[Planned]) -> list[tuple[Path, float]]:
    """(旁白 wav, 起點秒)；與字幕共用 line_times，唸的時候字幕同時出現。"""
    return [(NARR_DIR / f"{ln.narr_wav}.wav", t)
            for p, li, ln, t, _ in line_times(planned) if ln.audio_sec is not None and ln.narr_wav]


def build_narration_track(events: list[tuple[Path, float]], dest: Path) -> Path:
    """把逐行旁白依起點疊成一條音軌（adelay + amix）。"""
    args, chains = [], []
    for i, (wav, start) in enumerate(events):
        args += ["-i", str(wav)]
        ms = int(start * 1000)
        chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[n{i}]")
    mix = "".join(f"[n{i}]" for i in range(len(events)))
    graph = ";".join(chains) + f";{mix}amix=inputs={len(events)}:normalize=0:duration=longest[out]"
    ff(*args, "-filter_complex", graph, "-map", "[out]", "-c:a", "pcm_s16le", str(dest))
    return dest


def assemble(segs, ass: Path, out_file: Path, size: tuple[int, int], font_dir: str | None,
             narration: list[tuple[Path, float]] | None = None) -> None:
    work = out_file.parent / "norm"
    work.mkdir(exist_ok=True)
    listing = []
    for i, (src, head, secs, speed, is_first, is_last) in enumerate(segs):
        out_secs = secs * speed
        vf = [f"scale={size[0]}:{size[1]}:flags=lanczos", "setsar=1"]
        af = ["aresample=48000", "aformat=channel_layouts=stereo"]
        if speed > 1.001:
            # 慢動作：拉長時間戳再補幀到 24fps（blend 比單純重複幀順）；環境音同步放慢、音高不變
            vf += [f"setpts={speed:.4f}*PTS", f"minterpolate=fps={FPS}:mi_mode=blend"]
            af.append(f"atempo={1 / speed:.4f}")
        vf.append(f"fps={FPS}")
        if is_first:
            vf.append(f"fade=t=in:st=0:d={FADE_SEC}")
            af.append(f"afade=t=in:st=0:d={FADE_SEC}")
        if is_last:
            vf.append(f"fade=t=out:st={out_secs - FADE_SEC:.3f}:d={FADE_SEC}")
            af.append(f"afade=t=out:st={out_secs - FADE_SEC:.3f}:d={FADE_SEC}")
        dst = work / f"{i:03d}.mp4"
        ff("-ss", f"{head:.3f}", "-t", f"{secs:.3f}", "-i", str(src), "-vf", ",".join(vf), "-af", ",".join(af),
           "-t", f"{out_secs:.3f}", "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", str(dst))
        listing.append(f"file '{dst.name}'")
    (work / "list.txt").write_text("\n".join(listing), encoding="utf-8")
    joined = work / "joined.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(work / "list.txt"), "-c", "copy", str(joined))

    ass_arg = ass.as_posix().replace(":", r"\:")
    sub = f"{GRADE},subtitles='{ass_arg}'" + (f":fontsdir='{font_dir}'" if font_dir else "")
    enc = ["-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_file)]
    if not narration:
        # 只有環境音：H3 原生音普遍偏小聲（約 -50 dB），標準化到 -20 LUFS
        ff("-i", str(joined), "-vf", sub, "-af", "loudnorm=I=-20:TP=-2:LRA=11", *enc)
        return
    track = build_narration_track(narration, work / "narration.wav")
    # 環境音壓在 -30 LUFS 當底，旁白 -18 LUFS；旁白出聲時再用 sidechain 把環境音壓下去（ducking）
    graph = ("[0:a]loudnorm=I=-30:TP=-6[amb];"
             "[1:a]loudnorm=I=-18:TP=-2,asplit=2[nar][sc];"
             "[amb][sc]sidechaincompress=threshold=0.02:ratio=5:attack=30:release=600[duck];"
             "[duck][nar]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.9[a]")
    ff("-i", str(joined), "-i", str(track), "-filter_complex", f"[0:v]{sub}[v];{graph}",
       "-map", "[v]", "-map", "[a]", *enc)


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
    ap.add_argument("--no-narration", action="store_true",
                    help="不配旁白（預設：video_out/narration/narration.json 存在就配，時間軸跟著旁白走）")
    a = ap.parse_args()

    chapters = [int(x) for x in a.chapters.split(",")]
    narration = None if a.no_narration else load_narration()
    planned = plan(chapters, a.max_seconds, narration)
    total = sum(sum(p.clips) for p in planned)
    a.out.mkdir(parents=True, exist_ok=True)

    shotlist = [{**p.shot.to_dict(), "title": p.title, "use_clips": [round(c, 2) for c in p.clips],
                 "start": round(p.start, 2),
                 "speeds": [round(x, 3) for x in p.speeds], "n_base": p.n_base}
                for p in planned]
    (a.out / f"{a.name}.shots.json").write_text(json.dumps(shotlist, ensure_ascii=False, indent=2), encoding="utf-8")
    ass = a.out / f"{a.name}.ass"
    ass.write_text(build_ass(planned, speaker_names(), a.font), encoding="utf-8")
    n_clips = sum(len(p.clips) for p in planned)
    extra = sum(len(p.clips) - p.n_base for p in planned)
    print(f"{len(planned)} shots / {n_clips} clips（旁白補 {extra} 段）/ {total:.1f}s"
          f"{'，配旁白' if narration else ''} → {a.out / (a.name + '.shots.json')}")
    if a.plan:
        return 0

    client = ComfyClient(a.comfy)
    if not client.ping():
        print(f"ComfyUI 沒有回應：{a.comfy}", file=sys.stderr)
        return 2
    segs = generate(planned, a.out, client, RES[a.res], a.seed, not a.no_turbo)
    w, h = (int(x) for x in a.out_res.split("x"))
    final = a.out / f"{a.name}.mp4"
    assemble(segs, ass, final, (w, h), None, narration_events(planned) if narration else None)
    print(f"完成：{final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
