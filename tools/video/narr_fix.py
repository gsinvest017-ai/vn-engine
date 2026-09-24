"""旁白讀音局部修正（remaster v2 / M2）：只重合成讀音有問題的「合成單位」，放回 raw.wav 原位置。

依 docs/remaster_v2/pronunciation.{md,json} 的發現，每句用同一個聲音 zero_shot 生 N 個候選，
whisper 回聽（CER 參考稿＝台灣讀音替換後的 TTS 文字）＋ 讀音檢測留下的 MMS 強制對齊、F0 聲調分類器、
CTC 聲母韻母比較，驗證目標字是台灣音，挑最好的一個；rubberband（音高不變）微調回原句長度再拼回去。

    # WSL ~/.venv-cosy（GPU）：生候選＋驗證；第一次執行會把 video_out/narration/ 備份一次
    python tools/video/narr_fix.py synth [--n 6] [--max-n 8] [--only 第一章_01_01:0]
    python tools/video/narr_fix.py splice          # WSL：挑候選、變速、拼回 raw.wav（永遠從 v1 備份重做）
    python tools/video/narr_post.py                # Windows：重做後製 wav 與 narration.json 的 sec
    python tools/video/narr_fix.py plancheck       # Windows：分鏡 clip 數量與快取檔名檢查
    python tools/video/narr_fix.py report          # WSL：report.json/.md、ab_compare.mp3

輸出在 video_out/remaster_v2/narration_fix/。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import tw_reading  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NARR = ROOT / "video_out" / "narration"
V2 = ROOT / "video_out" / "remaster_v2"
BACKUP = V2 / "narration_v1_backup"
OUT = V2 / "narration_fix"
PRON = V2 / "pronunciation"
CLIPS = ROOT / "video_out" / "clips"
VOICES = ROOT / "video_out" / "voices"

SR = 24000
SENT_GAP = 0.35          # 與 cosy_tts.SENT_GAP 相同（這裡不 import，免得 Windows 端要裝模型套件）
TEMPO_OK = (0.85, 1.18)  # 候選長度 / 原句長度 在這範圍內就 rubberband 拉回原長
FADE = 0.010
CER_OK = 0.10

# 要重合成的合成單位：(段 key, 句#, 對應發現)。第一章_03_01（前夕）依決策不修
FIXES = [
    ("第一章_01_01", 0, "P01"), ("第一章_01_01", 1, "P02"), ("第一章_01_01", 2, "P03"),
    ("第一章_01_02", 0, "P05,P21"), ("第一章_01_04", 0, "P22"), ("第一章_01_04", 2, "P06"),
    ("第一章_01_05", 0, "P20"), ("第一章_01_07", 0, "P23"), ("第一章_03_04", 0, "P10,P09"),
    ("第一章_03_06", 0, "P11,P12"), ("第一章_03_08", 0, "P25"), ("第一章_03_11", 0, "P26"),
    ("第三章_00_00", 1, "P04,P18"), ("第三章_00_00", 2, "P29"), ("第二章_00_00", 0, "P27"),
    ("第二章_00_00", 1, "P14"), ("第二章_00_02", 0, "P28"), ("第二章_00_08", 0, "P15"),
    ("第二章_01_00", 0, "P16"), ("第二章_01_02", 0, "P17"),
]

# 驗證項目：(詞, 目標字在詞中的位置, 台灣讀音 TONE3, 對照（誤讀）TONE3, 方法)
# tone＝F0 聲調分類器比兩個聲調；ctc＝MMS CTC loss 比兩個無聲調拼音；both＝兩者都要過
CHECKS = [
    ("著", 0, "zhe5", "zhu4", "ctc"),
    ("究", 0, "jiu4", "jiu1", "tone"),
    ("期", 0, "qi2", "qi1", "tone"),
    ("褐", 0, "he2", "he4", "tone"),
    ("檔", 0, "dang3", "dang4", "tone"),
    ("突", 0, "tu2", "tu1", "tone"),
    ("微", 0, "wei2", "wei1", "tone"),
    ("跡", 0, "ji1", "ji4", "tone"),
    ("刁", 0, "diao1", "diu1", "ctc"),
    ("忽", 0, "hu1", "gu4", "both"),
    ("徐尋尋", 2, "xun2", "xu2", "ctc"),
    ("殘缺", 0, "can2", "chang2", "ctc"),
    ("側寫", 1, "xie3", "xuan3", "ctc"),
    ("屋頂", 1, "ding3", "di3", "ctc"),
    ("沖散", 1, "san4", "shang4", "ctc"),
    ("回答", 1, "da2", "dang2", "ctc"),
    ("多夢", 0, "duo1", "bo1", "ctc"),
]
TONE_PASS, CTC_PASS = 0.7, 1.0     # 與讀音檢測報告相同的門檻


# ---------------------------------------------------------------- 純函式（Windows 可測）
def zh_only(s: str) -> str:
    return "".join(ch for ch in s if "一" <= ch <= "鿿")


def find_targets(zh: str) -> list[dict]:
    """在純漢字字串裡找出要驗證的字位（同一字位只取第一個符合的規則）。"""
    out, seen = [], set()
    for word, pos, tw, alt, method in CHECKS:
        for m in re.finditer(re.escape(word), zh):
            i = m.start() + pos
            if i in seen:
                continue
            seen.add(i)
            out.append({"i": i, "char": zh[i], "word": word, "ctx": zh[max(0, i - 3): i + 4],
                        "tw": tw, "alt": alt, "method": method})
    return sorted(out, key=lambda t: t["i"])


def tone_verdict(share: float | None) -> str:
    if share is None:
        return "未測"
    return "pass" if share >= TONE_PASS else "fail" if share <= 1 - TONE_PASS else "unsure"


def ctc_verdict(margin: float | None) -> str:
    """margin＝誤讀的 loss − 台灣讀音的 loss（越大越像台灣音）。"""
    if margin is None:
        return "未測"
    return "pass" if margin >= CTC_PASS else "fail" if margin <= -CTC_PASS else "unsure"


def check_ok(c: dict) -> bool:
    vs = [c[k] for k in ("tone_verdict", "ctc_verdict") if k in c]
    return bool(vs) and all(v == "pass" for v in vs)


def stretch_plan(cand_sec: float, orig_sec: float, lo: float = TEMPO_OK[0],
                 hi: float = TEMPO_OK[1]) -> tuple[float, float, bool]:
    """rubberband tempo（>1 加速）與輸出長度；比例超出 [lo, hi] 就只拉到邊界、接受長度改變。"""
    ratio = cand_sec / orig_sec
    tempo = min(max(ratio, lo), hi)
    return tempo, cand_sec / tempo, not (lo <= ratio <= hi)


def cer_limit(v1_cer: float | None) -> float:
    """漏字門檻：專名（徐尋尋、刁才弟…）whisper 常寫成別的字，v1 本身 CER 就高；門檻跟著 v1 放寬。"""
    return CER_OK if v1_cer is None else max(CER_OK, v1_cer + 0.03)


def rank_key(c: dict, orig_sec: float, cer_ok: float = CER_OK):
    """候選排序：語速正常 → 沒漏字（CER）→ 驗證失敗數 → 長度可拉回原長 → 長度差（每 5% 一級：
    變速越少越不突兀）→ CER → 聲學邊際。"""
    fails = sum(not check_ok(x) for x in c["checks"])
    ratio = c["sec"] / orig_sec
    in_range = TEMPO_OK[0] <= ratio <= TEMPO_OK[1]
    # 有驗證沒過的（全部候選都唸不準時）：先比聲學邊際，挑「最接近」台灣音的
    near = -c.get("margin_sum", 0.0) if fails else 0.0
    return (not c["rate_ok"], c["cer"] > cer_ok, fails, near, not in_range, int(abs(math.log(ratio)) / 0.05),
            round(c["cer"], 2), -c.get("margin_sum", 0.0))


def pick_best(cands: list[dict], orig_sec: float, cer_ok: float = CER_OK) -> int:
    return min(range(len(cands)), key=lambda j: rank_key(cands[j], orig_sec, cer_ok))


def zero_runs(x: np.ndarray, sr: int, min_sec: float) -> list[tuple[int, int]]:
    """全 0 樣本區間（樣本索引，[start, end)）。"""
    z = (x == 0).astype(np.int8)
    d = np.diff(np.concatenate([[0], z, [0]]))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    return [(int(s), int(e)) for s, e in zip(starts, ends) if (e - s) >= min_sec * sr]


def chunk_spans(x: np.ndarray, sr: int, n_chunks: int) -> list[tuple[int, int]]:
    """cosy_tts.synth 在合成單位之間插 SENT_GAP 秒的全 0 → 每個合成單位的樣本區間。"""
    gaps = [g for g in zero_runs(x, sr, SENT_GAP - 0.02) if g[0] > 0 and g[1] < len(x)]
    if len(gaps) != n_chunks - 1:
        raise ValueError(f"找到 {len(gaps)} 個句間靜音，預期 {n_chunks - 1}")
    starts = [0] + [g[1] for g in gaps]
    ends = [g[0] for g in gaps] + [len(x)]
    return list(zip(starts, ends))


def fade(y: np.ndarray, sr: int, sec: float = FADE) -> np.ndarray:
    y = y.astype(np.float32).copy()
    n = min(int(sec * sr), len(y) // 2)
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n + 1, dtype=np.float32)[1:]    # 不含 0：句間全 0 區間的邊界不變
        y[:n] *= ramp
        y[-n:] *= ramp[::-1]
    return y


def splice(x: np.ndarray, repl: list[tuple[int, int, np.ndarray]], sr: int = SR) -> np.ndarray:
    """把 x[s:e] 換成新音檔（接點各 10 ms 淡入淡出）；由後往前換，前面的位置不受長度改變影響。"""
    y = x.astype(np.float32).copy()
    for s, e, new in sorted(repl, key=lambda r: r[0], reverse=True):
        y = np.concatenate([y[:s], fade(new, sr), y[e:]])
    return y


def fit_length(y: np.ndarray, n: int) -> np.ndarray:
    """rubberband 輸出長度會差幾毫秒：尾端補 0 或截掉，對齊到 n 個樣本。"""
    return y[:n] if len(y) >= n else np.concatenate([y, np.zeros(n - len(y), dtype=y.dtype)])


def voiced_bounds(y: np.ndarray, db: float = -45.0, min_run: float = 0.15, sr: int = SR) -> tuple[int, int]:
    """有聲部分 [a, b)，規則仿 narr_post 的 silenceremove（-45 dB、start_duration 0.15 s）：
    從頭（尾）找第一段連續超過 db 至少 min_run 秒的聲音；更短的雜音（開頭的氣音、喀聲）當靜音。
    以 10 ms 為一格；找不到就回傳 (0, len)。"""
    fr = max(1, int(0.01 * sr))
    n = len(y) // fr
    if n == 0:
        return 0, len(y)
    on = np.abs(y[: n * fr]).reshape(n, fr).max(axis=1) > 10 ** (db / 20)
    need = max(1, int(round(min_run / 0.01)))

    def first_run(v):
        run = 0
        for i, o in enumerate(v):
            run = run + 1 if o else 0
            if run >= need:
                return i - need + 1
        return None

    a, r = first_run(on), first_run(on[::-1])
    if a is None or r is None:
        return 0, len(y)
    return a * fr, min(len(y), (n - r) * fr)


def soft_limit(y: np.ndarray, knee: float = 0.8, ceil: float = 0.99) -> np.ndarray:
    """超過 knee 的部分用 tanh 軟壓，漸近 ceil（< 1，PCM16 不削波）；knee 以下原樣不動。"""
    a = np.abs(y)
    over = a > knee
    out = y.astype(np.float32).copy()
    out[over] = np.sign(y[over]) * (knee + (ceil - knee) * np.tanh((a[over] - knee) / (ceil - knee)))
    return out


def match_level(y: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """把 y 的 RMS 調到 ref 的 RMS（v1 同一句的有聲部分）。rubberband 會掉 2–3 dB、峰值/RMS 比也變大，
    只做峰值限制會補不回來（v1 峰值已是 0.99）→ 全增益後軟限幅（只動到極少數峰值樣本）。"""
    ry, rr = float(np.sqrt(np.mean(y ** 2))), float(np.sqrt(np.mean(ref ** 2)))
    if ry <= 0 or rr <= 0:
        return y
    return soft_limit(y * (rr / ry))


def rebuild(v1: np.ndarray, voiced: np.ndarray, sr: int = SR) -> np.ndarray:
    """v1 句自己的頭尾靜音（原樣本）＋ 新的有聲部分（接點淡入淡出）。
    narr_post 會修掉段落頭尾 -45 dB 以下的靜音：沿用 v1 的靜音，修剪量才跟 v1 一樣、後製長度不漂。"""
    a, b = voiced_bounds(v1)
    return np.concatenate([v1[:a], fade(voiced, sr), v1[b:]]).astype(np.float32)


def lead_trim(x: np.ndarray, sr: int, db: float = -45.0) -> float:
    """narr_post 的 silenceremove 開頭修剪量（近似）。"""
    nz = np.where(np.abs(x) > 10 ** (db / 20))[0]
    return nz[0] / sr if len(nz) else 0.0


def post_span(raw_span: tuple[float, float], lead: float, tempo: float) -> tuple[float, float]:
    """raw.wav 秒數 → 後製 wav 秒數（narr_post：修剪開頭靜音再 rubberband 變速）。"""
    return tuple(max(0.0, (t - lead) / tempo) for t in raw_span)


def clip_tags(planned) -> list[str]:
    """與 render.generate 相同的 clip 快取檔名（不連 ComfyUI）；render 改命名規則時這裡要跟著改。"""
    import prompts
    from comfy_client import snap_length
    tags, visits = [], {}
    for p in planned:
        s = p.shot
        revisit = visits.get(s.bg, 0)
        visits[s.bg] = revisit + 1
        for part, gen in enumerate(p.gens):
            cut = prompts.is_cut(s, part, p.n_base) if part < p.n_base else bool(prompts.ANGLES.get(s.bg))
            use_ref = part == 0 and revisit > 0
            head = prompts.CUT_HEAD if cut else 0.0
            suffix = "_t" if cut else "_c" if use_ref else ""
            tags.append(f"{s.chapter[:3]}_{s.index:02d}_{part}_{snap_length(gen + head)}f{suffix}")
    return tags


def sentence_text(rec: dict, ci: int) -> str:
    from cosy_tts import split_sentences
    return split_sentences("".join(rec["texts"]))[ci]


# ---------------------------------------------------------------- 聲學驗證（WSL ~/.venv-cosy）
class Checker:
    """讀音檢測（video_out/remaster_v2/pronunciation/analyze.py）的對齊、F0、聲調分類器，套在單句音檔上。"""

    def __init__(self):
        import pickle
        sys.path.insert(0, str(PRON))
        import analyze as A
        self.A = A
        self.al = A.Aligner()
        self.clf = pickle.loads((PRON / "tone_clf.pkl").read_bytes())
        an = json.loads((PRON / "analysis.json").read_text(encoding="utf-8"))
        self.f0_median = {k: b["f0_median"] for k, b in an["blocks"].items()}

    def check(self, x: np.ndarray, sr: int, sentence: str, key: str) -> list[dict]:
        from cosy_tts import tts_text
        A = self.A
        zh_sub = zh_only(tw_reading.to_tts(A.split_speakable(sentence)))
        zh_orig = zh_only(A.split_speakable(sentence))
        zh_tts = zh_only(tts_text(sentence, A.T2S))
        assert len(zh_sub) == len(zh_orig) == len(zh_tts), sentence
        sylls = [A.toneless(p) for p in A.tone3(zh_tts)]
        em, dur = self.al.emission(x.astype(np.float32), sr)
        spans = self.al.align(em, dur, sylls)
        f0, ft = A.f0_track(x.astype(np.float64), sr)
        out = []
        for tg in find_targets(zh_orig):
            i = tg["i"]
            t0, t1, sc = spans[i]
            nx = spans[i + 1][0] if i + 1 < len(spans) else t1 + 0.12
            t1x = max(t1, min(nx - 0.01, t1 + 0.12))
            r = {**tg, "tts_char": zh_sub[i], "t0": round(t0, 3), "t1": round(t1, 3), "align": round(sc, 3)}
            tw_t, alt_t = int(tg["tw"][-1]), int(tg["alt"][-1])
            if tg["method"] in ("tone", "both"):
                fv = A.syl_features(f0, ft, t0, t1x, self.f0_median[key])
                if fv is None:
                    r["tone_verdict"] = "未測"
                else:
                    pr = self.clf.predict_proba(fv.reshape(1, -1))[0]
                    cl = list(self.clf.classes_)
                    p_tw, p_alt = pr[cl.index(tw_t)], pr[cl.index(alt_t)]
                    r["p_tw_tone"] = round(float(p_tw / (p_tw + p_alt + 1e-9)), 3)
                    r["tone_pred"] = int(cl[int(np.argmax(pr))])
                    r["tone_verdict"] = tone_verdict(r["p_tw_tone"])
            if tg["method"] in ("ctc", "both"):
                l_tw = self.al.ctc_score(em, dur, t0, t1, A.toneless(tg["tw"]))
                l_alt = self.al.ctc_score(em, dur, t0, t1, A.toneless(tg["alt"]))
                r["ctc_loss"] = {A.toneless(tg["tw"]): round(l_tw, 2), A.toneless(tg["alt"]): round(l_alt, 2)}
                r["ctc_margin"] = round(l_alt - l_tw, 2)
                r["ctc_verdict"] = ctc_verdict(r["ctc_margin"])
            if tg["char"] == "著":
                r["dur"] = round(t1 - t0, 3)
            out.append(r)
        return out


def margin_sum(checks: list[dict]) -> float:
    """各驗證的聲學邊際加總（聲調：share−0.5 放大到與 CTC 同量級）。"""
    s = 0.0
    for c in checks:
        if "p_tw_tone" in c:
            s += (c["p_tw_tone"] - 0.5) * 10
        if "ctc_margin" in c:
            s += max(-10.0, min(10.0, c["ctc_margin"]))
    return round(s, 2)


def load_index(d: Path) -> dict:
    return json.loads((d / "narration.json").read_text(encoding="utf-8"))


def ensure_backup() -> None:
    """整個 video_out/narration/ 只備份一次（之後都從備份重做，可重複執行）。"""
    if not BACKUP.exists():
        shutil.copytree(NARR, BACKUP)
        print(f"備份 {NARR} → {BACKUP}", flush=True)


def v1_sentence(key: str, ci: int):
    import soundfile as sf
    idx = load_index(BACKUP)
    from cosy_tts import split_sentences
    x, sr = sf.read(str(BACKUP / f"{key}.raw.wav"), dtype="float32")
    n = len(split_sentences("".join(idx[key]["texts"])))
    s, e = chunk_spans(x, sr, n)[ci]
    return x, sr, s, e


def transcribe(nar, y: np.ndarray) -> str:
    """與 Narrator.score 相同的 whisper 回聽，但留下轉寫文字寫進報告。"""
    import torch
    segs, _ = nar.asr.transcribe(nar.to16k(torch.from_numpy(y).unsqueeze(0)).squeeze(0).numpy(),
                                 language="zh", beam_size=2)
    return "".join(s_.text for s_ in segs)


def cmd_synth(a) -> int:
    import soundfile as sf
    from cosy_tts import RATE_OK, Narrator, cer, tts_text
    ensure_backup()
    OUT.mkdir(parents=True, exist_ok=True)
    cdir = OUT / "cands"
    cdir.mkdir(exist_ok=True)
    idx = load_index(BACKUP)
    res_path = OUT / "cands.json"
    res = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    fixes = [f for f in FIXES if not a.only or f"{f[0]}:{f[1]}" in a.only.split(",")]
    chk = Checker()
    nars: dict[str, Narrator] = {}
    for key, ci, issues in fixes:
        rec = idx[key]
        voice = rec["voice"]
        if voice not in nars:
            vd = VOICES / voice
            nars[voice] = Narrator(vd / "prompt.wav", (vd / "prompt.txt").read_text(encoding="utf-8"),
                                   candidates=1, asr_device=a.asr_device)
        nar = nars[voice]
        sent = sentence_text(rec, ci)
        x, sr, s, e = v1_sentence(key, ci)
        orig_sec = (e - s) / sr
        v1 = x[s:e]
        entry = res.get(f"{key}:{ci}") or {}
        entry.update({"key": key, "chunk": ci, "issues": issues, "voice": voice, "subtitle": sent,
                      "tts_text": tts_text(sent, nar.t2s), "raw_span": [round(s / sr, 3), round(e / sr, 3)],
                      "orig_sec": round(orig_sec, 3)})
        entry["v1_checks"] = chk.check(v1, sr, sent, key)
        entry["v1_asr"] = transcribe(nar, v1)
        entry["v1_cer"] = round(cer(entry["v1_asr"], sent), 3)
        cer_ok = cer_limit(entry["v1_cer"])
        cands = entry.get("cands", [])
        n_chars = len(zh_only(sent))
        j = 0
        while j < a.max_n:
            wav = cdir / f"{key}_{ci}_{j}.wav"
            if j < len(cands) and wav.exists():
                j += 1
                continue
            if not wav.exists():
                audio = nar._once(sent)
                sf.write(str(wav), audio.squeeze(0).numpy(), SR)
            y, _ = sf.read(str(wav), dtype="float32")
            text = transcribe(nar, y)
            c = {"file": wav.name, "sec": round(len(y) / SR, 3), "asr": text, "cer": round(cer(text, sent), 3)}
            rate = n_chars / c["sec"]
            c["rate"], c["rate_ok"] = round(rate, 2), RATE_OK[0] <= rate <= RATE_OK[1]
            c["checks"] = chk.check(y, SR, sent, key)
            c["margin_sum"] = margin_sum(c["checks"])
            c["all_pass"] = all(check_ok(x_) for x_ in c["checks"])
            cands = cands[:j] + [c]
            j += 1
            print(f"  {key}:{ci} #{j} {c['sec']:.2f}s/{orig_sec:.2f}s CER={c['cer']:.2f} "
                  f"pass={c['all_pass']} " + " ".join(
                      f"{x_['char']}:{x_.get('tone_verdict', '')}{x_.get('ctc_verdict', '')}" for x_ in c["checks"]),
                  flush=True)
            good = [q for q in cands if q["all_pass"] and q["rate_ok"] and q["cer"] <= cer_ok
                    and TEMPO_OK[0] <= q["sec"] / orig_sec <= TEMPO_OK[1]]
            if j >= a.n and len(good) >= 1:
                break
        entry["cands"] = cands
        entry["best"] = pick_best(cands, orig_sec, cer_ok)
        res[f"{key}:{ci}"] = entry
        res_path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        b = cands[entry["best"]]
        v1s = " ".join(f"{x_['char']}:{x_.get('tone_verdict', '')}{x_.get('ctc_verdict', '')}"
                       for x_ in entry["v1_checks"])
        print(f"{key}:{ci} v1[{v1s}] → best #{entry['best'] + 1} pass={b['all_pass']} CER={b['cer']}", flush=True)
    return 0


def rubberband(y: np.ndarray, tempo: float, tmp: Path) -> np.ndarray:
    import soundfile as sf
    src, dst = tmp.with_suffix(".in.wav"), tmp.with_suffix(".out.wav")
    sf.write(str(src), y, SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af",
                    f"rubberband=tempo={tempo:.5f}:pitchq=quality:transients=smooth", "-ar", str(SR), "-ac", "1",
                    str(dst)], check=True)
    out, _ = sf.read(str(dst), dtype="float32")
    src.unlink()
    dst.unlink()
    return out


def cmd_splice(a) -> int:
    import soundfile as sf
    ensure_backup()
    res = json.loads((OUT / "cands.json").read_text(encoding="utf-8"))
    idx = load_index(NARR)
    calib_path = OUT / "calib.json"
    calib = json.loads(calib_path.read_text(encoding="utf-8")) if calib_path.exists() else {}
    by_block: dict[str, list] = {}
    choice = {}
    for key, ci, _ in FIXES:
        e = res.get(f"{key}:{ci}")
        if not e:
            print(f"跳過 {key}:{ci}（沒有候選）")
            continue
        best = pick_best(e["cands"], e["orig_sec"], cer_limit(e.get("v1_cer")))
        # 長度比的是「有聲部分」：頭尾靜音沿用 v1（rebuild），候選自己的頭尾靜音不算
        x1, _, s, t = v1_sentence(key, ci)
        v1 = x1[s:t]
        a1, b1 = voiced_bounds(v1)
        orig_voiced = (b1 - a1) / SR
        ys, cands = [], []
        for c in e["cands"]:
            y, _ = sf.read(str(OUT / "cands" / c["file"]), dtype="float32")
            a2, b2 = voiced_bounds(y)
            ys.append(y[a2:b2])
            cands.append({**c, "sec": (b2 - a2) / SR})
        best = pick_best(cands, orig_voiced, cer_limit(e.get("v1_cer")))
        j = (a.pick or {}).get(f"{key}:{ci}", best)
        c = cands[j]
        tempo, out_sec, clamped = stretch_plan(c["sec"], orig_voiced)
        # 校正量（calibrate 算的）：後製長度仍有殘差時，微調這句的目標長度
        target = ((b1 - a1) / SR if not clamped else out_sec) + calib.get(f"{key}:{ci}", 0.0)
        tempo = c["sec"] / target
        z = rubberband(ys[j], tempo, OUT / f"tmp_{key}_{ci}")
        z = match_level(fit_length(z, round(target * SR)), v1[a1:b1])
        new = rebuild(v1, z)
        by_block.setdefault(key, []).append((s, t, new))
        n_out = len(new)
        choice[f"{key}:{ci}"] = {"cand": j, "file": c["file"], "tempo": round(tempo, 4), "clamped": clamped,
                                 "orig_sec": e["orig_sec"], "new_sec": round(n_out / SR, 3),
                                 "orig_voiced_sec": round(orig_voiced, 3), "cand_voiced_sec": round(c["sec"], 3),
                                 "intended_delta_sec": round(out_sec - orig_voiced, 3) if clamped else 0.0,
                                 "calib_sec": round(calib.get(f"{key}:{ci}", 0.0), 4),
                                 "delta_sec": round(n_out / SR - e["orig_sec"], 3)}
        print(f"{key}:{ci} 候選 #{j + 1} 有聲 {c['sec']:.2f}s → ×{tempo:.3f} → 句長 {n_out / SR:.2f}s "
              f"（原 {e['orig_sec']:.2f}s{'，超出範圍、長度改變' if clamped else ''}）", flush=True)
    for key, repl in by_block.items():
        src = BACKUP / f"{key}.raw.wav"
        x, sr = sf.read(str(src), dtype="float32")
        y = splice(x, repl, sr)
        sf.write(str(NARR / f"{key}.raw.wav"), y, sr, subtype=sf.info(str(src)).subtype)
        # narr_post 沿用 narration.json 的 raw_sec：長度改了要一起更新
        idx[key] = {**idx[key], "raw_sec": round(len(y) / sr, 3),
                    "tts_fix_v2": sorted(ci for k, ci, _ in FIXES if k == key and f"{k}:{ci}" in choice)}
    (NARR / "narration.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "choice.json").write_text(json.dumps(choice, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"拼回 {len(by_block)} 段、{len(choice)} 句 → 接著在 Windows 跑 narr_post.py")
    return 0


CALIB_BIAS = 0.015   # 後製秒數寧長勿短：旁白補的 clip 長度吃 17 幀網格，v1 有的 shot 只差 0.02 s 就換檔名


def calib_residuals(v1_sec: dict, v2_sec: dict, choice: dict, tempo: dict) -> dict[str, float]:
    """每個有修的段：後製秒數與目標（v1＋刻意的長度改變/tempo＋偏差）的差 → 換算成 raw 秒數，
    記在該段最後一句修正句上（段內句子長度改變只影響總長，放哪句都一樣）。"""
    out: dict[str, float] = {}
    for key in {k.split(":")[0] for k in choice}:
        mine = sorted((k for k in choice if k.split(":")[0] == key), key=lambda k: int(k.split(":")[1]))
        intended = sum(choice[k]["intended_delta_sec"] for k in mine) / tempo[key]
        resid = v1_sec[key] + intended + CALIB_BIAS - v2_sec[key]
        out[mine[-1]] = resid * tempo[key]
    return out


def cmd_calibrate(a) -> int:
    """narr_post 之後跑（Windows）：累加校正量到 calib.json，再跑一次 splice → narr_post。"""
    i1, i2 = load_index(BACKUP), load_index(NARR)
    choice = json.loads((OUT / "choice.json").read_text(encoding="utf-8"))
    path = OUT / "calib.json"
    calib = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    res = calib_residuals({k: v["sec"] for k, v in i1.items()}, {k: v["sec"] for k, v in i2.items()}, choice,
                          {k: v["tempo"] for k, v in i2.items()})
    for k, r in res.items():
        calib[k] = round(calib.get(k, 0.0) + r, 4)
        print(f"{k} 殘差 raw {r:+.3f}s → 校正 {calib[k]:+.3f}s")
    path.write_text(json.dumps(calib, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def cmd_plancheck(a) -> int:
    """render.py --plan 跑一次（輸出到 plan_check/），再比 v1/v2 的 clip 數與快取檔名。"""
    import render
    out_dir = V2 / "plan_check"
    subprocess.run([sys.executable, str(Path(__file__).parent / "render.py"), "--plan", "--out", str(out_dir),
                    "--name", "plan"], check=True)
    chapters = [1, 2, 3]
    v2 = render.plan(chapters, None, render.load_narration())
    saved = render.NARR_DIR
    render.NARR_DIR = BACKUP
    try:
        v1 = render.plan(chapters, None, render.load_narration())
    finally:
        render.NARR_DIR = saved
    t1, t2 = clip_tags(v1), clip_tags(v2)
    missing_v1 = [t for t in t1 if not (CLIPS / f"{t}.mp4").exists()]
    missing = [t for t in t2 if not (CLIPS / f"{t}.mp4").exists()]
    i1, i2 = load_index(BACKUP), load_index(NARR)
    blocks = [{"key": k, "v1_sec": i1[k]["sec"], "v2_sec": i2[k]["sec"],
               "delta": round(i2[k]["sec"] - i1[k]["sec"], 3), "fixed": k in {f[0] for f in FIXES}}
              for k in i1]
    rep = {"v1_clips": len(t1), "v2_clips": len(t2), "same_count": len(t1) == len(t2),
           "v1_missing_cache": missing_v1, "v2_missing_cache": missing,
           "tags_changed": [[a_, b_] for a_, b_ in zip(t1, t2) if a_ != b_],
           "v1_total_sec": round(sum(sum(p.clips) for p in v1), 2),
           "v2_total_sec": round(sum(sum(p.clips) for p in v2), 2), "blocks": blocks}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "plan_check.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"clip 數 v1 {len(t1)} / v2 {len(t2)}；v2 缺快取 {len(missing)}（v1 自檢缺 {len(missing_v1)}）；"
          f"總長 {rep['v1_total_sec']} → {rep['v2_total_sec']} 秒")
    for b in blocks:
        if abs(b["delta"]) > 0.0005:
            print(f"  {b['key']} {b['v1_sec']:.3f} → {b['v2_sec']:.3f}（{b['delta']:+.3f}）{'*' if b['fixed'] else ''}")
    return 0 if rep["same_count"] and not missing else 1


def fmt_checks(cs: list[dict]) -> str:
    parts = []
    for c in cs:
        v = []
        if "p_tw_tone" in c:
            v.append(f"台灣調 {c['p_tw_tone']:.2f}")
        if "ctc_margin" in c:
            v.append(f"CTC 邊際 {c['ctc_margin']:+.1f}")
        mark = "✓" if check_ok(c) else "✗"
        parts.append(f"{c['char']}({c['tw']}) {mark} " + "、".join(v))
    return "；".join(parts)


def cmd_report(a) -> int:
    import soundfile as sf
    from cosy_tts import split_sentences
    res = json.loads((OUT / "cands.json").read_text(encoding="utf-8"))
    choice = json.loads((OUT / "choice.json").read_text(encoding="utf-8"))
    plan = json.loads((OUT / "plan_check.json").read_text(encoding="utf-8")) if (OUT / "plan_check.json").exists() else None
    i1, i2 = load_index(BACKUP), load_index(NARR)
    chk = Checker()
    rows, ab = [], []
    gap = np.zeros(int(0.5 * SR), dtype=np.float32)
    sep = np.zeros(int(1.2 * SR), dtype=np.float32)
    cache = {}

    def post_seg(d: Path, idx: dict, key: str, ci: int):
        if (d, key) not in cache:
            raw, _ = sf.read(str(d / f"{key}.raw.wav"), dtype="float32")
            post, _ = sf.read(str(d / f"{key}.wav"), dtype="float32")
            n = len(split_sentences("".join(idx[key]["texts"])))
            cache[(d, key)] = (raw, post, chunk_spans(raw, SR, n), lead_trim(raw, SR))
        raw, post, spans, lead = cache[(d, key)]
        s, e = spans[ci]
        ps, pe = post_span((s / SR, e / SR), lead, idx[key]["tempo"])
        a_, b_ = max(0, int((ps - 0.08) * SR)), min(len(post), int((pe + 0.08) * SR))
        return raw[s:e], post[a_:b_], (round(ps, 2), round(pe, 2))

    for key, ci, issues in FIXES:
        k = f"{key}:{ci}"
        if k not in choice:
            continue
        e, ch = res[k], choice[k]
        raw1, post1, pspan1 = post_seg(BACKUP, i1, key, ci)
        raw2, post2, pspan2 = post_seg(NARR, i2, key, ci)
        final_checks = chk.check(raw2, SR, e["subtitle"], key)      # 拼回、變速後的實際音檔再驗一次
        c = e["cands"][ch["cand"]]
        rows.append({"key": key, "chunk": ci, "issues": issues, "subtitle": e["subtitle"], "tts_text": e["tts_text"],
                     "n_cands": len(e["cands"]), "cand": ch["cand"], "cand_cer": c["cer"],
                     "tempo": ch["tempo"], "clamped": ch["clamped"], "orig_sec": ch["orig_sec"],
                     "new_sec": ch["new_sec"], "v1_post_span": pspan1, "v2_post_span": pspan2,
                     "v1_checks": e["v1_checks"], "cand_checks": c["checks"], "final_checks": final_checks,
                     "final_all_pass": all(check_ok(x) for x in final_checks),
                     "v1_all_pass": all(check_ok(x) for x in e["v1_checks"])})
        ab += [post1, gap, post2, sep]
    wav = OUT / "ab_compare.wav"
    sf.write(str(wav), np.concatenate(ab), SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3",
                    str(OUT / "ab_compare.mp3")], check=True)
    wav.unlink()
    cv3 = OUT / "cv3" / "cv3_try.json"
    cv3_rows = json.loads(cv3.read_text(encoding="utf-8")) if cv3.exists() else []
    rep = {"sentences": rows, "plan_check": plan,
           "cv3_trial": [{k: r[k] for k in ("file", "text", "sec", "asr", "cer")} | {"checks": fmt_checks(r["checks"])}
                         for r in cv3_rows],
           "summary": {"fixed": len(rows), "final_all_pass": sum(r["final_all_pass"] for r in rows),
                       "v1_all_pass": sum(r["v1_all_pass"] for r in rows),
                       "clamped": [f"{r['key']}:{r['chunk']}" for r in rows if r["clamped"]]}}
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "report.md").write_text(render_md(rep), encoding="utf-8")
    print(json.dumps(rep["summary"], ensure_ascii=False))
    return 0


def render_md(rep: dict) -> str:
    s = rep["summary"]
    L = ["# 旁白讀音局部修正報告（remaster v2 / M2）", "",
         f"重合成 {s['fixed']} 句；拼回後聲學驗證全過 {s['final_all_pass']} 句（v1 同一套驗證全過 {s['v1_all_pass']} 句）。"
         f"長度超出 0.85–1.18 倍而改變長度：{', '.join(s['clamped']) or '無'}。", "",
         "- 驗證：MMS 強制對齊 → F0 聲調分類器（台灣調機率 ≥0.7 算過）與 CTC 聲母韻母比較（誤讀 loss − 台灣讀音 loss ≥1 算過）；"
         "「拼回後」是 rubberband 變速、拼回 raw.wav 之後再驗一次",
         "- 試聽：ab_compare.mp3 依下表順序，每句「v1 → 0.5 秒 → v2」，句與句之間 1.2 秒（後製後的音檔）", ""]
    L += ["| 段 key | 句# | 發現 | 送 TTS 文字 | 候選 | 長度 原→新（tempo） | v1 驗證 | v2 拼回後驗證 |", "|---|---|---|---|---|---|---|---|"]
    for r in rep["sentences"]:
        L.append(f"| {r['key']} | {r['chunk']} | {r['issues']} | {r['tts_text']} | #{r['cand'] + 1}/{r['n_cands']} "
                 f"CER {r['cand_cer']:.2f} | {r['orig_sec']:.2f}→{r['new_sec']:.2f}s（×{r['tempo']:.3f}） | "
                 f"{fmt_checks(r['v1_checks'])} | {fmt_checks(r['final_checks'])} |")
    if rep.get("cv3_trial"):
        L += ["", "## 第一章_01_04:0「沖散」：Fun-CosyVoice3 試驗（未採用）", "",
              "CosyVoice2 8 個候選 whisper 全聽成「沖上」、CTC 都偏 shang（最好的 #3 邊際 +0.4＝無法判定），v2.0 採用 #3；"
              "v2.1 改用 CosyVoice2 換斷句重生的候選（見 remaster_v2/narration_fix_v2_1/report.md）。"
              "CosyVoice3（cv3/）不加 hotfix 也唸得出 sàn，但音色與 CV2 旁白不同（未經人耳確認）、"
              "有的把「連續」唸錯，而且唸得過長（1.2–1.3 倍，超出可變速範圍），所以沒拼進去；需要時人工試聽後改用。", "",
              "| 檔案 | 送 TTS 文字 | 秒 | whisper | 驗證 |", "|---|---|---|---|---|"]
        for r in rep["cv3_trial"]:
            L.append(f"| cv3/{r['file']} | {r['text']} | {r['sec']} | {r['asr']} | {r['checks']} |")
    p = rep.get("plan_check")
    if p:
        L += ["", "## 分鏡檢查（render.py --plan）", "",
              f"- clip 數：v1 {p['v1_clips']} → v2 {p['v2_clips']}（{'相同' if p['same_count'] else '不同'}）",
              f"- v2 需要但 video_out/clips/ 沒有的快取：{len(p['v2_missing_cache'])} 個 {p['v2_missing_cache'] or ''}",
              f"- 快取檔名有變的 clip：{len(p['tags_changed'])} 個",
              f"- 總長：{p['v1_total_sec']} → {p['v2_total_sec']} 秒", "",
              "| 段 key | v1 sec | v2 sec | 差 | 有修 |", "|---|---|---|---|---|"]
        for b in p["blocks"]:
            L.append(f"| {b['key']} | {b['v1_sec']:.3f} | {b['v2_sec']:.3f} | {b['delta']:+.3f} | {'✓' if b['fixed'] else ''} |")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("synth")
    p.add_argument("--n", type=int, default=6, help="至少生幾個候選")
    p.add_argument("--max-n", type=int, default=8, help="都沒過驗證時最多生到幾個")
    p.add_argument("--only", default="", help="只做這些句，例：第一章_01_01:0,第一章_01_02:0")
    p.add_argument("--asr-device", default="cpu")
    p = sub.add_parser("splice")
    p.add_argument("--pick", type=json.loads, default=None, help='人工指定候選：{"第一章_01_01:0": 2}（0 起算）')
    sub.add_parser("calibrate")
    sub.add_parser("plancheck")
    sub.add_parser("report")
    a = ap.parse_args()
    return {"synth": cmd_synth, "splice": cmd_splice, "plancheck": cmd_plancheck, "calibrate": cmd_calibrate, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
