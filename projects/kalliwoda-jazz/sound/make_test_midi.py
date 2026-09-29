"""8 小節 ballad 測試曲（F 大調、60 BPM、swing 三連音感）：小號旋律 + Bill Evans 式 rootless 鋼琴 + 撥奏低音 + 刷子小鼓 + hi-hat/ride。

只是音色庫與渲染鏈的測試素材，不是 Kalliwoda 改編本身。

和聲（每小節 4 拍）：
  1 Fmaj9 | 2 Em7b5  A7b9 | 3 Dm9 | 4 Gm9  C13 | 5 Am9  D7b9 | 6 Gm9 | 7 Gm9  Gb13(=C7 的三全音代理) | 8 F6/9
鋼琴左手 rootless（A/B 型，3-7 或 7-3 為核心，加 9/13），右手偶爾加頂音；低音走根音 + 半音接近音（two-feel）。
鼓：刷子長 stir（key 24）每小節一次鋪底 + 每拍短 stir（key 28），拍 2、4 刷子輕拍（key 38–40，力度 ~40–60）；
    hi-hat 腳踩 chick（44）在 2、4；ride（51）極輕的 swing 「ding, ding-da-ding」。
小號：後拍慵懶（整體延後 ~35 ms）、樂句間留白，音域 C4–D5（Chet 的中音域）。

用法：python projects/kalliwoda-jazz/sound/make_test_midi.py [--out 路徑]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "tools" / "video"))
import jazz_render as J  # noqa: E402

BPM = 60
SW = 2 / 3                     # swing：第二個八分音符落在三連音第 3 格
LAY = 0.035                    # 小號延後 35 ms（60 BPM 下 = 0.035 拍）
N = {n: i for i, n in enumerate(["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"])}
N.update({"Db": 1, "D#": 3, "Gb": 6, "G#": 8, "A#": 10})


def p(name: str) -> int:
    """'A3' → 57（科學音名，C4 = 60）。"""
    return (int(name[-1]) + 1) * 12 + N[name[:-1]]


# (起拍, 拍長, 和弦名, 左手 rootless voicing, 低音根音)
CHORDS = [
    (0, 4, "Fmaj9", ["A3", "C4", "E4", "G4"], "F2"),
    (4, 2, "Em7b5", ["G3", "Bb3", "D4", "E4"], "E2"),
    (6, 2, "A7b9", ["G3", "Bb3", "C#4", "F4"], "A1"),
    (8, 4, "Dm9", ["F3", "A3", "C4", "E4"], "D2"),
    (12, 2, "Gm9", ["F3", "A3", "Bb3", "D4"], "G1"),
    (14, 2, "C13", ["E3", "A3", "Bb3", "D4"], "C2"),
    (16, 2, "Am9", ["G3", "B3", "C4", "E4"], "A1"),
    (18, 2, "D7b9", ["F#3", "B3", "C4", "Eb4"], "D2"),
    (20, 4, "Gm9", ["F3", "A3", "Bb3", "D4"], "G1"),
    (24, 2, "Gm9", ["F3", "Bb3", "D4", "A4"], "G1"),
    (26, 2, "Gb13", ["E3", "Ab3", "Bb3", "Eb4"], "Gb1"),
    (28, 4, "F6/9", ["A3", "D4", "G4", "C5"], "F1"),
]

# 小號旋律 (起拍, 拍長, 音, 力度)；8 小節、兩個樂句，中間與結尾留白
MELODY = [
    (0.0 + SW, 0.33, "C4", 52), (1.0, 1.4, "A4", 60), (2.66, 0.34, "G4", 50), (3.0, 1.9, "E4", 56),
    (5.0 + SW, 0.33, "D4", 50), (6.0, 0.66, "E4", 54), (6.66, 0.34, "F4", 52), (7.0, 0.9, "G4", 58),
    (8.0, 2.8, "F4", 55),
    # 第 4 小節：留白（只剩鋼琴回應）
    (16.0 + SW, 0.33, "E4", 50), (17.0, 1.0, "C5", 64), (18.0, 0.66, "B4", 58), (18.66, 0.34, "A4", 54),
    (19.0, 0.9, "Eb4", 56),
    (20.0, 0.66, "D4", 52), (20.66, 0.34, "F4", 54), (21.0, 2.0, "A4", 60),
    (24.0 + SW, 0.33, "Bb3", 48), (25.0, 0.66, "D4", 52), (25.66, 0.34, "F4", 54), (26.0, 0.66, "Ab4", 58),
    (26.66, 0.34, "Gb4", 52), (27.0, 0.9, "E4", 54),
    (28.0, 3.5, "G4", 50),
]


def build(out: Path) -> Path:
    b = J.MidiBuilder(bpm=BPM)
    for name in ("trumpet", "piano", "bass", "brush", "hihat"):
        b.track(name)

    # ---- 小號 ----
    for s, d, n, v in MELODY:
        b.note("trumpet", s + LAY, d, p(n), v)

    # ---- 鋼琴：和弦「稍微搶在拍前/拍後」分散、延音踏板每個和弦換一次 ----
    for k, (s, d, name, voicing, _root) in enumerate(CHORDS):
        on = s + (0.0 if k % 2 == 0 else SW)          # 一半的和弦在反拍（anticipation 感）
        for j, n in enumerate(voicing):
            b.note("piano", on + 0.012 * j, d - (on - s) - 0.05, p(n), 44 + 3 * j)   # 由下往上輕微 roll
        b.cc("piano", max(0, on - 0.02), 64, 0)
        b.cc("piano", on + 0.08, 64, 100)
        if d == 4:                                     # 長和弦中間加一個右手的 9 或頂音點綴
            b.note("piano", s + 2 + SW, 1.2, p(voicing[-1]) + 12, 38)
    b.cc("piano", 31.9, 64, 0)

    # ---- 低音：two-feel，拍 1、3 根音；和弦換之前半音接近 ----
    for k, (s, d, name, voicing, root) in enumerate(CHORDS):
        r = p(root)
        r = r + 12 if r < p("E1") else r
        if d == 4:
            b.note("bass", s, 1.8, r, 80)
            nxt = CHORDS[k + 1][4] if k + 1 < len(CHORDS) else None
            if nxt:
                target = p(nxt) if p(nxt) >= p("E1") else p(nxt) + 12
                b.note("bass", s + 2, 1.0, r + 7 if r + 7 < 50 else r - 5, 70)       # 五度
                b.note("bass", s + 3, 0.9, target + (1 if target < r + 7 else -1), 68)  # 半音接近
            else:
                b.note("bass", s + 2, 1.9, r, 60)
        else:
            b.note("bass", s, 1.9, r, 78)

    # ---- 刷子（Frankensnare 14x5 maple brush）----
    for bar in range(8):
        s = bar * 4
        b.note("brush", s, 3.9, 24, 70)               # 長 stir 鋪底（同 group 會自動互相截斷）
        for beat in range(4):                          # 每拍一個短 stir（畫圈刷），讓掃弦聲不中斷
            b.note("brush", s + beat + 0.02, 0.95, 28, 92 if beat % 2 == 0 else 84)
        for beat in (1, 3):
            b.note("brush", s + beat, 0.3, 38, 42 + (bar % 3) * 4)
        if bar in (3, 7):                              # 樂句尾的一個輕 slap
            b.note("brush", s + 3 + SW, 0.2, 38, 64)

    # ---- hi-hat 腳踩 + 極輕 ride（Virtuosity Drums，OH mic）----
    for bar in range(8):
        s = bar * 4
        for beat in (1, 3):
            b.note("hihat", s + beat, 0.2, 44, 55)
        if bar >= 4:                                   # 後半段才加 ride，做一點層次
            for beat in range(4):
                b.note("hihat", s + beat, 0.3, 51, 34 + (6 if beat in (1, 3) else 0))
                if beat in (1, 3):
                    b.note("hihat", s + beat + SW, 0.2, 51, 28)
    b.end(34)
    b.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "test_ballad_8bar.mid")
    a = ap.parse_args()
    print(build(a.out))
