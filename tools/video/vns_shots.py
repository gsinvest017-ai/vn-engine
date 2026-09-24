"""把 .vns 劇本解析成影片分鏡（shot）清單。

規則：
- 每個 `@scene` 開一個新 shot；`@weather` / `@effect` / `@sfx` / `@bgm` 累積成該 shot 的畫面與聲音狀態。
- 旁白、對白（`[id] 台詞`）、引文（`> 文字`）都當字幕行；`@wait` 變成字幕之間的停頓。
- 時長依字數估算（CHARS_PER_SEC），shot 超過 MAX_CLIP 秒就拆成多段 clip 接續生成。
- `@char` 不進畫面：旁白立繪是真人照片，做成會動的臉有肖像權疑慮，影片版只保留氛圍鏡頭。
"""
from __future__ import annotations

import math
import re
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path

CHARS_PER_SEC = 6.0      # 中文字幕舒適閱讀速度
MIN_LINE_SEC = 2.5
MAX_CLIP = 10.0          # H3 訓練長度約 5–15 秒，取 10 秒上限留餘裕
MIN_CLIP = 5.0
SUB_MAX_CHARS = 26       # 單條字幕上限，超過就在標點處斷開
LINE_GAP = 0.6           # 有旁白時，每行唸完後的停頓


@dataclass
class Line:
    kind: str            # narration | dialogue | quote
    text: str
    speaker: str = ""
    pause_before: float = 0.0
    audio_sec: float | None = None   # 有旁白音檔時的實際長度（render.plan 填入）
    narr_wav: str | None = None      # 從這行開始播的旁白段落檔名；段內後續行為 None

    @property
    def seconds(self) -> float:
        if self.audio_sec is not None:
            return self.audio_sec + LINE_GAP
        return max(MIN_LINE_SEC, len(self.text) / CHARS_PER_SEC)


@dataclass
class Shot:
    index: int
    chapter: str
    bg: str
    rain: str = "none"
    wind: float = 0.0
    fog: float = 0.0
    dim: float = 0.0
    flicker: bool = False
    vignette: bool = False
    shake: bool = False
    bgm: str | None = None
    sfx: list[str] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    tail_pause: float = 0.0
    source_line: int = 0

    @property
    def seconds(self) -> float:
        return sum(l.pause_before + l.seconds for l in self.lines) + self.tail_pause

    def clip_lengths(self) -> list[float]:
        total = max(self.seconds, MIN_CLIP)
        n = max(1, math.ceil(total / MAX_CLIP))
        return [total / n] * n

    def to_dict(self) -> dict:
        d = asdict(self)
        d["seconds"] = round(self.seconds, 2)
        d["clips"] = [round(x, 2) for x in self.clip_lengths()]
        return d


def _kv(arg: str) -> dict[str, str]:
    out = {}
    for tok in shlex.split(arg):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
        else:
            out.setdefault("_", tok)
    return out


def parse(path: Path, start_index: int = 0) -> list[Shot]:
    shots: list[Shot] = []
    chapter = ""
    cur: Shot | None = None
    pending_pause = 0.0
    # 畫面狀態會跨 @scene 延續（例如雨沒被關掉就一直下）
    state = dict(rain="none", wind=0.0, fog=0.0, dim=0.0, bgm=None)

    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            cmd, _, arg = line[1:].partition(" ")
            kv = _kv(arg)
            if cmd == "chapter":
                chapter = arg.strip()
            elif cmd == "scene":
                if cur is not None:
                    cur.tail_pause += pending_pause
                    pending_pause = 0.0
                state["dim"] = 0.0
                cur = Shot(index=start_index + len(shots), chapter=chapter, bg=kv["bg"],
                           rain=state["rain"], wind=state["wind"], fog=state["fog"],
                           bgm=kv.get("music") or state["bgm"], source_line=no)
                shots.append(cur)
            elif cur is None:
                if cmd == "bgm" and "play" in kv:
                    state["bgm"] = kv["play"]
                continue
            elif cmd == "weather":
                if "rain" in kv:
                    state["rain"] = cur.rain = kv["rain"]
                if "wind" in kv:
                    state["wind"] = cur.wind = float(kv["wind"])
                if "fog" in kv:
                    state["fog"] = cur.fog = float(kv["fog"])
            elif cmd == "effect":
                kind = kv.get("_", "")
                if kind == "dim":
                    cur.dim = max(cur.dim, float(kv.get("level", 0)))
                elif kind == "flicker":
                    cur.flicker = True
                elif kind == "vignette":
                    cur.vignette = True
                elif kind in ("shake", "flash"):
                    cur.shake = True
            elif cmd == "bgm":
                if "play" in kv:
                    state["bgm"] = cur.bgm = kv["play"]
                elif kv.get("_") == "stop":
                    state["bgm"] = None
            elif cmd == "sfx" and "play" in kv:
                if kv["play"] not in cur.sfx:
                    cur.sfx.append(kv["play"])
            elif cmd == "wait":
                pending_pause += int(kv.get("_", "0")) / 1000
            elif cmd == "fade":
                pending_pause += int(kv.get("duration", "0")) / 2000
            continue

        if cur is None:
            continue
        m = re.match(r"^\[(\w+)\]\s*(.+)$", line)
        if m:
            ln = Line("dialogue", m.group(2), speaker=m.group(1))
        elif line.startswith(">"):
            ln = Line("quote", line.lstrip("> ").strip())
        else:
            ln = Line("narration", line)
        ln.pause_before = pending_pause
        pending_pause = 0.0
        cur.lines.append(ln)

    if cur is not None:
        cur.tail_pause += pending_pause
    return [s for s in shots if s.lines]


def split_subtitle(text: str, limit: int = SUB_MAX_CHARS) -> list[str]:
    """長段落在句讀處切成多條字幕，每條不超過 limit 字。"""
    if len(text) <= limit:
        return [text]
    pieces = re.split(r"(?<=[。！？；，、：])", text)
    out, buf = [], ""
    for p in pieces:
        if not p:
            continue
        if buf and len(buf) + len(p) > limit:
            out.append(buf)
            buf = ""
        while len(p) > limit:
            out.append(p[:limit])
            p = p[limit:]
        buf += p
    if buf:
        out.append(buf)
    return out
