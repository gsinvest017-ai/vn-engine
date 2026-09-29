"""「沖散」修正與第二套 ASR 交叉驗證（remaster v2.1）。

「沖散」依序試：(1) CosyVoice3 唸對的子句用 CosyVoice2 inference_vc 轉成 s70_C 音色，只換掉 v2.0 採用候選
（第一章_01_04:0 #3）裡含「沖散」的那一段（rubberband 對齊原段長度、接點 10 ms 淡入淡出）——讀音對了但音色量測
回不到 CV2 → 不採用；(2) CosyVoice2 換斷句寫法整句重生 → 採用。交叉驗證用 FunASR（SenseVoiceSmall、paraformer-zh）
和 whisper medium 並列重聽 20 句修正句的 v1／v2.0／v2.1。

    # WSL ~/.venv-cosy（GPU）
    python tools/video/narr_vc.py vc            # 每個 CV3 來源 × 每種替換範圍 → 轉換、拼回、驗證、接縫量測
    python tools/video/narr_vc.py timbre        # （CPU）VC 結果的音色（campplus、F0）與接縫量測、重新排序
    python tools/video/narr_vc.py rewrite       # 第 2 招：CosyVoice2 換斷句寫法再生，每種 8 個候選
    python tools/video/narr_vc.py adopt --src rewrite --file comma_around_3.wav ...   # 加進 narration_fix/cands
    #  接著照 narr_fix 流程：narr_fix.py splice → narr_post.py → narr_fix.py calibrate/plancheck
    python tools/video/narr_vc.py asr-whisper   # v1 / v2.0 / v2.1 的 20 句，whisper medium 重聽（同一套切句）
    # WSL ~/.venv-asr2（FunASR，CPU）
    python tools/video/narr_vc.py asr-funasr    # 同樣的音檔，SenseVoiceSmall＋paraformer-zh 重聽
    python tools/video/narr_vc.py report        # report.json/.md、ab_compare_v2_1.mp3（v1 → v2.1 逐句）

輸出在 video_out/remaster_v2/narration_fix_v2_1/。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import narr_fix as F  # noqa: E402

OUT21 = F.V2 / "narration_fix_v2_1"
BACKUP20 = F.V2 / "backup_v2_0"
KEY, CI = "第一章_01_04", 0
SENT = "記憶在我腦中並不連續。它們像被暴雨沖散後重新堆積的河砂。"
BASE_CAND = "第一章_01_04_0_2.wav"     # v2.0 採用的 CosyVoice2 候選（#3）
CV3_DIR = F.OUT / "cv3"
# 替換範圍（純漢字字位 [lo, hi)）：sent2＝第二句整句（句號停頓處接，最自然）；phrase＝只換「被暴雨沖散後」
REGIONS = {"sent2": (10, 26), "phrase": (13, 19)}
SR = F.SR


# ---------------------------------------------------------------- 純函式（Windows 可測）
def backup_rel(src: Path, v2: Path = F.V2, video_out: Path = F.ROOT / "video_out") -> Path:
    """備份用的相對路徑：remaster_v2 底下的相對 remaster_v2（與其他修補工作的 backup_v2_0 一致，
    例：narration_fix/cands.json），其餘相對 video_out（例：narration/第一章_01_04.wav）。"""
    s = src.resolve()
    try:
        return s.relative_to(v2.resolve())
    except ValueError:
        return s.relative_to(video_out.resolve())


def backup_once(src: Path, dst_root: Path = BACKUP20, **kw) -> Path | None:
    """覆寫 video_out 底下的檔案前，複製到 backup_v2_0/<相對路徑>；已備份過就不動（只備份一次）。"""
    if not src.exists():
        return None
    dst = dst_root / backup_rel(src, **kw)
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return dst


def frame_rms(y: np.ndarray, sr: int, frame: float = 0.005) -> np.ndarray:
    n = max(1, int(frame * sr))
    k = len(y) // n
    if k == 0:
        return np.zeros(0)
    return np.sqrt(np.mean(y[: k * n].astype(np.float64).reshape(k, n) ** 2, axis=1))


def cut_point(y: np.ndarray, sr: int, t_a: float, t_b: float, frame: float = 0.005) -> int:
    """在 [t_a, t_b] 之間找能量最低的 5 ms 格，回傳該格中心的樣本位置（在字與字的縫裡下刀）。"""
    if t_b < t_a:
        t_a, t_b = t_b, t_a
    n = max(1, int(frame * sr))
    a, b = max(0, int(t_a * sr)), min(len(y), int(t_b * sr))
    if b - a < n:
        return int(np.clip((a + b) // 2, 0, len(y)))
    r = frame_rms(y[a:b], sr, frame)
    return a + int(np.argmin(r)) * n + n // 2


def region_cuts(y: np.ndarray, sr: int, spans: list[tuple], lo: int, hi: int,
                voiced_end: int | None = None, pad: float = 0.04) -> tuple[int, int]:
    """字位 [lo, hi) 對應的樣本區間：左右接點各在相鄰兩字的縫中（前字尾−pad ～ 後字頭＋pad 的最低能量處）；
    lo=0 從頭、hi=字數 到有聲結尾（voiced_end，預設整段）。"""
    n = len(spans)
    a = 0 if lo == 0 else cut_point(y, sr, spans[lo - 1][1] - pad, spans[lo][0] + pad)
    if hi >= n:
        b = len(y) if voiced_end is None else voiced_end
    else:
        b = cut_point(y, sr, spans[hi - 1][1] - pad, spans[hi][0] + pad)
    return a, b


def replace_region(base: np.ndarray, a: int, b: int, new: np.ndarray, sr: int = SR,
                   fade_sec: float = F.FADE) -> np.ndarray:
    """base[a:b] 換成 new（長度要先對齊成 b−a），接點 10 ms 淡入淡出；總長不變。"""
    new = F.fit_length(new.astype(np.float32), b - a)
    return np.concatenate([base[:a], F.fade(new, sr, fade_sec), base[b:]]).astype(np.float32)


def _mel_fb(sr: int, n_fft: int, n_mels: int) -> np.ndarray:
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10 ** (m / 2595.0) - 1.0)
    pts = mel2hz(np.linspace(hz2mel(0), hz2mel(sr / 2), n_mels + 2))
    bins = np.floor((n_fft + 1) * pts / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        l, c, r = bins[m - 1], bins[m], bins[m + 1]
        for k in range(l, c):
            fb[m - 1, k] = (k - l) / max(1, c - l)
        for k in range(c, r):
            fb[m - 1, k] = (r - k) / max(1, r - c)
    return fb


def spectral_frames(y: np.ndarray, sr: int, n_fft: int = 1024, hop: int = 240):
    """回傳 (功率譜 [T, F], 每格 RMS dB)；不足一格回傳空陣列。"""
    y = y.astype(np.float64)
    if len(y) < n_fft:
        return np.zeros((0, n_fft // 2 + 1)), np.zeros(0)
    idx = np.arange(0, len(y) - n_fft + 1, hop)
    frames = np.stack([y[i:i + n_fft] for i in idx]) * np.hanning(n_fft)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    rms_db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-12)
    return spec, rms_db


def voiced_stats(y: np.ndarray, sr: int, db_floor: float = 25.0) -> dict | None:
    """有聲格（比該段最大 RMS 低不到 db_floor dB）的 MFCC 平均（c1–c12）、頻譜重心、RMS dB。"""
    spec, rms_db = spectral_frames(y, sr)
    if len(rms_db) == 0:
        return None
    keep = rms_db > rms_db.max() - db_floor
    spec, rms_db = spec[keep], rms_db[keep]
    freqs = np.fft.rfftfreq(1024, 1 / sr)
    centroid = float(np.mean((spec * freqs).sum(1) / (spec.sum(1) + 1e-12)))
    logmel = np.log(spec @ _mel_fb(sr, 1024, 40).T + 1e-10)
    n = logmel.shape[1]
    dct = np.cos(np.pi / n * (np.arange(n)[None, :] + 0.5) * np.arange(13)[:, None])
    mfcc = logmel @ dct.T
    return {"mfcc": mfcc[:, 1:13].mean(0), "centroid_hz": centroid,
            "rms_db": float(10 * np.log10(np.mean(10 ** (rms_db / 10))))}


def seam_metrics(y: np.ndarray, sr: int, a: int, b: int, ctx: float = 1.5, edge: float = 0.05,
                 silent_db: float = -50.0) -> dict:
    """替換段 y[a:b] 與前後各 ctx 秒的上下文比：MFCC 平均向量距離、頻譜重心差、響度差；
    以及兩個接點前後各 edge 秒的 RMS 跳變（dB）。上下文不足（段落頭尾）的那側略過。"""
    reg = voiced_stats(y[a:b], sr)
    out: dict = {}
    n_ctx = int(ctx * sr)
    for side, seg in (("left", y[max(0, a - n_ctx):a]), ("right", y[b:b + n_ctx])):
        st = voiced_stats(seg, sr)
        if st is None or reg is None or st["rms_db"] < silent_db:     # 段落尾端的靜音不算上下文
            continue
        out[side] = {"mfcc_dist": round(float(np.linalg.norm(reg["mfcc"] - st["mfcc"])), 2),
                     "centroid_diff_hz": round(reg["centroid_hz"] - st["centroid_hz"], 1),
                     "loud_diff_db": round(reg["rms_db"] - st["rms_db"], 2)}
    ne = int(edge * sr)

    def db(z):
        return 10 * np.log10(np.mean(z.astype(np.float64) ** 2) + 1e-12)
    for name, p in (("jump_a_db", a), ("jump_b_db", b)):
        if ne <= p <= len(y) - ne:
            out[name] = round(float(db(y[p:p + ne]) - db(y[p - ne:p])), 2)
    if reg is not None:
        out["region"] = {"centroid_hz": round(reg["centroid_hz"], 1), "rms_db": round(reg["rms_db"], 2)}
    return out


def cosine(u, v) -> float:
    u, v = np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64)
    return float(u @ v / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-12))


def vc_rank(c: dict):
    """VC 候選排序：驗證全過 → whisper 聽到「散」→ 沒漏字 → 變速少（每 10% 一級：VC 段要壓/拉越多越不自然）
    → 散 的 CTC 邊際大 → 與 CV2 原段音色相似 → 接縫 MFCC 距離小。"""
    import math
    san = next((x for x in c["checks"] if x["char"] == "散"), {})
    seam = np.mean([c["seam"][s]["mfcc_dist"] for s in ("left", "right") if s in c["seam"]] or [0.0])
    return (not c["all_pass"], "散" not in c["asr"], c.get("cer", 0.0) > F.CER_OK,
            int(abs(math.log(c.get("tempo", 1.0))) / 0.1), -round(san.get("ctc_margin", -99.0), 0),
            -round(c["spk_sim_base"], 2), round(float(seam), 1))


# ---------------------------------------------------------------- 交叉驗證 ASR 的判讀（Windows 可測）
def _toks(s: str, norm: bool = True) -> list[tuple[str, str]]:
    """純漢字與其拼音（TONE3，依上下文）。norm=True 先過 tw_reading.for_cer（一字換一字，字位不變）。"""
    from pypinyin import Style, lazy_pinyin
    import tw_reading
    if norm:
        s = tw_reading.for_cer(s)
    zh = F.zh_only(s)
    return list(zip(zh, lazy_pinyin(zh, style=Style.TONE3, neutral_tone_with_five=True)))


def _toneless(p: str) -> str:
    return re.sub(r"[0-9]", "", p).replace("v", "u")


def align_hyp(ref: str, hyp: str) -> list[int | None]:
    """拼音層（不看聲調）編輯距離對齊：ref 每個字位對到 hyp 的哪個字位（刪除則 None）。"""
    rp = [_toneless(p) for _, p in _toks(ref)]
    hp = [_toneless(p) for _, p in _toks(hyp)]
    n, m = len(rp), len(hp)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0], d[0, :] = np.arange(n + 1), np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (rp[i - 1] != hp[j - 1]))
    out: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        if d[i, j] == d[i - 1, j - 1] + (rp[i - 1] != hp[j - 1]):
            out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif d[i, j] == d[i - 1, j] + 1:
            i -= 1
        else:
            j -= 1
    return out


def target_reading(ref: str, hyp: str, target: dict) -> dict:
    """ASR 轉寫在目標字位寫了什麼字，判定像台灣讀音（tw）、誤讀（alt）、其他（other）或無從判斷（lexical）。

    ASR 有語言模型、會「猜詞」：聲母韻母不同的誤讀（沖散→沖上）聽得出來 → 比無聲調拼音；
    純聲調差異（檔 dàng/dǎng）ASR 多半照詞彙寫原字，寫原字（或其簡體）＝lexical（無從判斷）；
    只有寫成別的字（突→圖、檔→黨）時才用那個字的聲調判定。"""
    al = align_hyp(ref, hyp)
    j = al[target["i"]] if target["i"] < len(al) else None
    if j is None:
        return {"hyp_char": "", "hyp_py": "", "verdict": "missing"}
    ch, py = _toks(hyp, norm=False)[j]
    return {"hyp_char": ch, "hyp_py": py, "verdict": char_verdict(ch, target)}


def char_verdict(ch: str, target: dict) -> str:
    """ASR 寫的字 ch 的所有讀音（多音字全列）裡：只含台灣讀音＝tw、只含誤讀＝alt、兩者都含＝lexical
    （例：繁體「著」同時是 zhe／zhù，寫「著」無從判斷）、都不含＝other。
    聲母韻母不同的比無聲調拼音；純聲調差異的，寫原字（或其簡體）一律 lexical，換了字才比帶聲調的讀音。"""
    from pypinyin import Style, pinyin
    import tw_reading
    reads = set(pinyin(ch, style=Style.TONE3, heteronym=True, neutral_tone_with_five=True)[0])
    tw, alt = target["tw"].replace("v", "u"), target["alt"].replace("v", "u")
    reads = {r.replace("v", "u") for r in reads}
    if _toneless(tw) != _toneless(alt):
        has_tw = any(_toneless(r) == _toneless(tw) for r in reads)
        has_alt = any(_toneless(r) == _toneless(alt) for r in reads)
    else:
        if ch in (target["char"], tw_reading.SIMPLIFIED.get(target["char"], target["char"])):
            return "lexical"
        has_tw, has_alt = tw in reads, alt in reads
    return "lexical" if has_tw and has_alt else "tw" if has_tw else "alt" if has_alt else "other"


def tw_reading_for(s: str) -> str:
    import tw_reading
    return tw_reading.for_cer(s)


# ---------------------------------------------------------------- WSL：VC
def _paths():
    return {"cands": F.OUT / "cands", "vc": OUT21 / "vc"}


def cmd_vc(a) -> int:
    import soundfile as sf
    import torch
    import torchaudio
    from cosy_tts import Narrator, cer, tts_text
    OUT21.mkdir(parents=True, exist_ok=True)
    vdir = _paths()["vc"]
    vdir.mkdir(exist_ok=True)
    vd = F.VOICES / "s70_C"
    nar = Narrator(vd / "prompt.wav", (vd / "prompt.txt").read_text(encoding="utf-8"), candidates=1,
                   asr_device="cpu")
    chk = F.Checker()
    A = chk.A
    zh_tts = F.zh_only(tts_text(SENT, A.T2S))
    sylls = [A.toneless(p) for p in A.tone3(zh_tts)]

    def spans_of(y):
        em, dur = chk.al.emission(y.astype(np.float32), SR)
        return chk.al.align(em, dur, sylls)

    def load24(p):
        y, sr = sf.read(str(p), dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        if sr != SR:
            y = torchaudio.functional.resample(torch.from_numpy(y), sr, SR).numpy()
        return y

    def spk(y, tmp):
        sf.write(str(tmp), y, SR)
        e = nar.cv.frontend._extract_spk_embedding(str(tmp))
        tmp.unlink()
        return np.asarray(e.cpu().numpy() if hasattr(e, "cpu") else e).ravel()

    base = load24(F.OUT / "cands" / BASE_CAND)
    bspans = spans_of(base)
    bvoiced = F.voiced_bounds(base)[1]
    prompt_emb = spk(load24(vd / "prompt.wav"), vdir / "tmp_p.wav")
    sources = sorted(CV3_DIR.glob("*.wav"))
    rows = []
    base_eval = {}
    for rname, (lo, hi) in REGIONS.items():
        ba, bb = region_cuts(base, SR, bspans, lo, hi, voiced_end=bvoiced)
        base_emb = spk(base[ba:bb], vdir / "tmp_b.wav")
        base_eval[rname] = {"cut": [ba, bb], "seam": seam_metrics(base, SR, ba, bb),
                            "spk_sim_prompt": round(cosine(base_emb, prompt_emb), 3)}
        for src in sources:
            x = load24(src)
            sp = spans_of(x)
            sa, sb = region_cuts(x, SR, sp, lo, hi, voiced_end=F.voiced_bounds(x)[1])
            seg = x[sa:sb]
            tmp = vdir / f"tmp_src_{src.stem}_{rname}.wav"
            sf.write(str(tmp), seg, SR)
            for k in range(a.n):
                torch.manual_seed(1234 + k)
                w = torch.cat([o["tts_speech"] for o in nar.cv.inference_vc(str(tmp), str(vd / "prompt.wav"),
                                                                             stream=False)], dim=1)
                v = w.squeeze(0).cpu().numpy().astype(np.float32)
                tempo = len(v) / (bb - ba)
                z = F.fit_length(F.rubberband(v, tempo, vdir / f"tmp_rb_{src.stem}_{rname}_{k}"), bb - ba)
                z = F.match_level(z, base[ba:bb])
                comp = replace_region(base, ba, bb, z)
                name = f"{src.stem}_{rname}_{k}"
                sf.write(str(vdir / f"{name}.wav"), comp, SR)
                sf.write(str(vdir / f"{name}.region.wav"), v, SR)
                text = F.transcribe(nar, comp)
                checks = chk.check(comp, SR, SENT, KEY)
                emb = spk(comp[ba:bb], vdir / "tmp_c.wav")
                src_emb = spk(seg, vdir / "tmp_s.wav")
                r = {"file": f"{name}.wav", "source": src.name, "region": rname, "seed": 1234 + k,
                     "src_cut": [sa, sb], "base_cut": [ba, bb], "src_sec": round(len(seg) / SR, 3),
                     "vc_sec": round(len(v) / SR, 3), "base_region_sec": round((bb - ba) / SR, 3),
                     "tempo": round(tempo, 4), "asr": text, "cer": round(cer(text, SENT), 3), "checks": checks,
                     "all_pass": all(F.check_ok(c) for c in checks), "margin_sum": F.margin_sum(checks),
                     "spk_sim_base": round(cosine(emb, base_emb), 3),
                     "spk_sim_prompt": round(cosine(emb, prompt_emb), 3),
                     "src_spk_sim_base": round(cosine(src_emb, base_emb), 3),
                     "seam": seam_metrics(comp, SR, ba, bb)}
                rows.append(r)
                san = next(c for c in checks if c["char"] == "散")
                print(f"{name} tempo×{tempo:.3f} 散 CTC {san['ctc_margin']:+.1f} {san['ctc_verdict']} "
                      f"spk(base) {r['spk_sim_base']:.3f}（CV3 原 {r['src_spk_sim_base']:.3f}） {text}", flush=True)
            tmp.unlink()
    rows.sort(key=vc_rank)
    out = {"base": {"file": BASE_CAND, "regions": base_eval,
                    "checks": chk.check(base, SR, SENT, KEY), "asr": F.transcribe(nar, base)},
           "cands": rows}
    (OUT21 / "vc.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("最佳：", rows[0]["file"] if rows else None)
    return 0


def cmd_timbre(a) -> int:
    """vc 之後（不需 GPU）：用 CV2 自帶的 campplus 說話人向量與 F0 中位數，比較「替換段」和「同一句沒被換的部分」
    （base 的上下文，也就是聽眾會拿來比的聲音）：base 原段（基準）、CV3 原音、VC 後。重算接縫量測並重新排序。"""
    import onnxruntime as ort
    import soundfile as sf
    import torch
    import torchaudio
    import torchaudio.compliance.kaldi as kaldi
    sys.path.insert(0, str(F.PRON))
    import analyze as A
    from cosy_tts import MODEL_DIR
    sess = ort.InferenceSession(f"{MODEL_DIR}/campplus.onnx", providers=["CPUExecutionProvider"])

    def emb(y):
        t = torchaudio.functional.resample(torch.from_numpy(y.astype(np.float32)).unsqueeze(0), SR, 16000)
        f = kaldi.fbank(t, num_mel_bins=80, dither=0, sample_frequency=16000)
        f = f - f.mean(dim=0, keepdim=True)
        return sess.run(None, {sess.get_inputs()[0].name: f.unsqueeze(0).numpy()})[0].ravel()

    def f0med(y):
        f0, _ = A.f0_track(y.astype(np.float64), SR)
        v = f0[f0 > 0]
        return round(float(np.median(v)), 1) if len(v) else None

    vc = json.loads((OUT21 / "vc.json").read_text(encoding="utf-8"))
    base, _ = sf.read(str(F.OUT / "cands" / BASE_CAND), dtype="float32")
    ctx_cache = {}
    for rname, info in vc["base"]["regions"].items():
        ba, bb = info["cut"]
        ctx = np.concatenate([base[:ba], base[bb:F.voiced_bounds(base)[1]]])
        e_ctx = emb(ctx)
        ctx_cache[rname] = (e_ctx, f0med(ctx))
        info["timbre"] = {"ctx_f0": ctx_cache[rname][1], "region_f0": f0med(base[ba:bb]),
                          "sim_ctx": round(cosine(emb(base[ba:bb]), e_ctx), 3)}
        info["seam"] = seam_metrics(base, SR, ba, bb)
    for c in vc["cands"]:
        y, _ = sf.read(str(OUT21 / "vc" / c["file"]), dtype="float32")
        ba, bb = c["base_cut"]
        src, _ = sf.read(str(CV3_DIR / c["source"]), dtype="float32")
        sa, sb = c["src_cut"]
        e_ctx, f_ctx = ctx_cache[c["region"]]
        c["timbre"] = {"ctx_f0": f_ctx, "vc_f0": f0med(y[ba:bb]), "cv3_f0": f0med(src[sa:sb]),
                       "vc_sim_ctx": round(cosine(emb(y[ba:bb]), e_ctx), 3),
                       "cv3_sim_ctx": round(cosine(emb(src[sa:sb]), e_ctx), 3)}
        c["seam"] = seam_metrics(y, SR, ba, bb)
        print(c["file"], c["timbre"], flush=True)
    vc["cands"].sort(key=vc_rank)
    (OUT21 / "vc.json").write_text(json.dumps(vc, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("基準", {r: i["timbre"] for r, i in vc["base"]["regions"].items()})
    print("最佳：", vc["cands"][0]["file"])
    return 0


# 第 2 招：CosyVoice2 換寫法再生（只改送 TTS 的文字；字幕不變）。full＝整句重生；sub＝只生第二句、拼回 sent2 範圍
REWRITES = {
    "comma_around": ("full", "记忆在我脑中并不连续。它们像被暴雨，冲散后，重新堆积的河砂。"),
    "comma_before_san": ("full", "记忆在我脑中并不连续。它们像被暴雨冲，散后重新堆积的河砂。"),
    "comma_after_san": ("full", "记忆在我脑中并不连续。它们像被暴雨冲散，后重新堆积的河砂。"),
    "sub_only": ("sub", "它们像被暴雨冲散后重新堆积的河砂。"),
}


def cmd_rewrite(a) -> int:
    """每種寫法生 a.n 個候選；驗證「散」、whisper 回聽、音色（campplus 與同段其他句比）。"""
    import soundfile as sf
    import torch
    from cosy_tts import Narrator, cer, split_sentences
    vd = F.VOICES / "s70_C"
    nar = Narrator(vd / "prompt.wav", (vd / "prompt.txt").read_text(encoding="utf-8"), candidates=1,
                   asr_device="cpu")
    chk = F.Checker()
    rdir = OUT21 / "rewrite"
    rdir.mkdir(parents=True, exist_ok=True)
    base, _ = sf.read(str(F.OUT / "cands" / BASE_CAND), dtype="float32")
    vc = json.loads((OUT21 / "vc.json").read_text(encoding="utf-8"))
    ba, bb = vc["base"]["regions"]["sent2"]["cut"]
    # 音色參考：同一段（第一章_01_04）沒動過的第 2 個合成單位（v1 原音）
    raw, _ = sf.read(str(F.BACKUP / f"{KEY}.raw.wav"), dtype="float32")
    n = len(split_sentences("".join(F.load_index(F.BACKUP)[KEY]["texts"])))
    s1, e1 = F.chunk_spans(raw, SR, n)[1]
    ref = raw[s1:e1]

    def spk(y, name):
        p = rdir / f"tmp_{name}.wav"
        sf.write(str(p), y, SR)
        e = nar.cv.frontend._extract_spk_embedding(str(p))
        p.unlink()
        return np.asarray(e.cpu().numpy() if hasattr(e, "cpu") else e).ravel()
    ref_emb = spk(ref, "ref")
    base_sim = round(cosine(spk(base, "base"), ref_emb), 3)
    rows = []
    for name, (mode, text) in REWRITES.items():
        for k in range(a.n):
            w = torch.cat([o["tts_speech"] for o in nar.cv.inference_zero_shot(
                text, nar.prompt_text, nar.prompt_wav, stream=False, text_frontend=nar.text_frontend)], dim=1)
            y = w.squeeze(0).cpu().numpy().astype(np.float32)
            r = {"variant": name, "mode": mode, "text": text, "k": k}
            if mode == "sub":
                v0, v1_ = F.voiced_bounds(y)
                seg = y[v0:v1_]
                tempo = len(seg) / (bb - ba)
                z = F.match_level(F.fit_length(F.rubberband(seg, tempo, rdir / f"tmp_rb_{k}"), bb - ba), base[ba:bb])
                y = replace_region(base, ba, bb, z)
                r["tempo"] = round(tempo, 4)
            f = rdir / f"{name}_{k}.wav"
            sf.write(str(f), y, SR)
            txt = F.transcribe(nar, y)
            checks = chk.check(y, SR, SENT, KEY)
            r.update({"file": f.name, "sec": round(len(y) / SR, 3), "asr": txt, "cer": round(cer(txt, SENT), 3),
                      "checks": checks, "all_pass": all(F.check_ok(c) for c in checks),
                      "spk_sim_ref": round(cosine(spk(y, "c"), ref_emb), 3)})
            rows.append(r)
            san = next(c for c in checks if c["char"] == "散")
            print(f"{f.name} {r['sec']}s 散 CTC {san['ctc_margin']:+.1f} {san['ctc_verdict']} sim {r['spk_sim_ref']} "
                  f"{txt}", flush=True)
    out = {"base_sim_ref": base_sim, "ref": f"v1 {KEY} 第 2 個合成單位", "cands": rows,
           "n_pass": sum(r["all_pass"] and "散" in r["asr"] for r in rows)}
    (OUT21 / "rewrite.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"基準（v2.0 候選）sim {base_sim}；通過（CTC 全過且 whisper 聽到「散」）{out['n_pass']}/{len(rows)}")
    return 0


def cand_entry(c: dict, file: str, n_samples: int, origin: str) -> dict:
    """vc.json / rewrite.json 的一列 → narr_fix cands.json 的候選格式（narr_fix.pick_best 能直接比）。"""
    from cosy_tts import RATE_OK
    sec = n_samples / SR
    rate = len(F.zh_only(SENT)) / sec
    return {"file": file, "sec": round(sec, 3), "asr": c["asr"], "cer": c["cer"], "rate": round(rate, 2),
            "rate_ok": RATE_OK[0] <= rate <= RATE_OK[1], "checks": c["checks"],
            "margin_sum": F.margin_sum(c["checks"]), "all_pass": c["all_pass"], "v2_1_from": origin}


def cmd_adopt(a) -> int:
    """把 vc.json / rewrite.json 裡指定的結果當成新候選，寫進 narration_fix/cands 與 cands.json（先備份 cands.json）；
    之後 narr_fix.py splice 依原本的 pick_best 規則在所有候選裡挑。"""
    import soundfile as sf
    rows = json.loads((OUT21 / f"{a.src}.json").read_text(encoding="utf-8"))["cands"]
    backup_once(F.OUT / "cands.json")
    res = json.loads((F.OUT / "cands.json").read_text(encoding="utf-8"))
    e = res[f"{KEY}:{CI}"]
    for fname in a.file:
        c = next(r for r in rows if r["file"] == fname)
        if not c["all_pass"] and not a.force:
            print(f"{fname} 沒有全部通過驗證，不採用（--force 強制）")
            return 1
        y, _ = sf.read(str(OUT21 / a.src / fname), dtype="float32")
        out = f"{KEY}_{CI}_{a.src}_{Path(fname).stem}.wav"
        sf.write(str(F.OUT / "cands" / out), y, SR)
        e["cands"] = [x for x in e["cands"] if x["file"] != out] + [cand_entry(c, out, len(y), f"{a.src}/{fname}")]
        print(f"加入候選 {a.src}/{fname} → cands/{out}")
    e["best"] = F.pick_best(e["cands"], e["orig_sec"], F.cer_limit(e.get("v1_cer")))
    (F.OUT / "cands.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(e['cands'])} 個候選；pick_best（原句長）＝#{e['best'] + 1} {e['cands'][e['best']]['file']}")
    return 0


# ---------------------------------------------------------------- 20 句音檔（v1 / v2.0 / v2.1）
VERSIONS = {"v1": F.BACKUP, "v2_0": BACKUP20 / "narration", "v2_1": F.NARR}


def sentence_audio(version: str):
    """每個修正句：(k, 字幕, raw 句音檔, 後製句音檔)；切法與 narr_fix.report 相同。"""
    import soundfile as sf
    from cosy_tts import split_sentences
    d = VERSIONS[version]
    idx = F.load_index(d)
    cache = {}
    for key, ci, _ in F.FIXES:
        if key not in cache:
            raw, _ = sf.read(str(d / f"{key}.raw.wav"), dtype="float32")
            post, _ = sf.read(str(d / f"{key}.wav"), dtype="float32")
            n = len(split_sentences("".join(idx[key]["texts"])))
            cache[key] = (raw, post, F.chunk_spans(raw, SR, n), F.lead_trim(raw, SR))
        raw, post, spans, lead = cache[key]
        s, e = spans[ci]
        ps, pe = F.post_span((s / SR, e / SR), lead, idx[key]["tempo"])
        a_, b_ = max(0, int((ps - 0.08) * SR)), min(len(post), int((pe + 0.08) * SR))
        yield f"{key}:{ci}", F.sentence_text(idx[key], ci), raw[s:e], post[a_:b_]


def export_sentences() -> Path:
    """20 句 × 3 版本 × (raw, post) 存成 16 kHz wav，讓不同 venv 的 ASR 讀同一批檔案。"""
    import soundfile as sf
    import torch
    import torchaudio
    d = OUT21 / "sent16k"
    d.mkdir(parents=True, exist_ok=True)
    meta = {}
    for ver in VERSIONS:
        for k, sub, raw, post in sentence_audio(ver):
            for kind, y in (("raw", raw), ("post", post)):
                f = d / f"{ver}__{k.replace(':', '_')}__{kind}.wav"
                z = torchaudio.functional.resample(torch.from_numpy(y), SR, 16000).numpy()
                sf.write(str(f), z, 16000)
                meta.setdefault(k, {"subtitle": sub})[f"{ver}_{kind}"] = f.name
    (d / "index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def cmd_asr_whisper(a) -> int:
    import soundfile as sf
    from faster_whisper import WhisperModel
    d = export_sentences()
    meta = json.loads((d / "index.json").read_text(encoding="utf-8"))
    asr = WhisperModel("medium", device="cpu", compute_type="int8")
    out = {}
    for k, m in meta.items():
        for tag, f in m.items():
            if tag == "subtitle":
                continue
            y, _ = sf.read(str(d / f), dtype="float32")
            segs, _ = asr.transcribe(y, language="zh", beam_size=2)
            out.setdefault(k, {})[tag] = "".join(s.text for s in segs)
        print(k, out[k].get("v2_1_raw"), flush=True)
    (OUT21 / "asr_whisper_medium.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def cmd_asr_funasr(a) -> int:
    """WSL ~/.venv-asr2：FunASR SenseVoiceSmall 與 paraformer-zh（和 whisper 不同家族）。"""
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
    d = OUT21 / "sent16k"
    meta = json.loads((d / "index.json").read_text(encoding="utf-8"))
    models = {"sensevoice_small": AutoModel(model="iic/SenseVoiceSmall", device="cpu", disable_update=True),
              "paraformer_zh": AutoModel(model="paraformer-zh", device="cpu", disable_update=True)}
    for name, m in models.items():
        out = {}
        for k, mm in meta.items():
            for tag, f in mm.items():
                if tag == "subtitle":
                    continue
                kw = {"language": "zh", "use_itn": False} if name == "sensevoice_small" else {}
                r = m.generate(input=str(d / f), **kw)
                text = r[0]["text"] if r else ""
                if name == "sensevoice_small":
                    text = rich_transcription_postprocess(text)
                out.setdefault(k, {})[tag] = text.replace(" ", "")
            print(name, k, out[k].get("v2_1_raw"), flush=True)
        (OUT21 / f"asr_{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


INFORMATIVE = {"tw", "alt", "other", "missing"}


def family_verdicts(row: dict) -> dict[str, set]:
    """一列裡兩個 ASR 家族（whisper／FunASR）各自的「有資訊」判定集合（lexical＝照詞彙寫原字，不算）。"""
    out: dict[str, set] = {"whisper": set(), "funasr": set()}
    for n, v in row.items():
        if isinstance(v, dict) and v.get("verdict") in INFORMATIVE:
            out["whisper" if n.startswith("whisper") else "funasr"].add(v["verdict"])
    return out


def cross_table(meta: dict, asrs: dict[str, dict]) -> list[dict]:
    """每句每個修正字位 × 版本 × ASR 的判定，並標出兩家族 ASR（whisper vs FunASR）判定不一致處。"""
    rows = []
    for k, m in meta.items():
        sub = m["subtitle"]
        for tg in F.find_targets(F.zh_only(sub)):
            for ver in ("v1", "v2_0", "v2_1"):
                for kind in ("raw", "post"):
                    tag = f"{ver}_{kind}"
                    row = {"k": k, "char": tg["char"], "word": tg["word"], "tw": tg["tw"], "alt": tg["alt"],
                           "method": tg["method"], "version": ver, "kind": kind}
                    for an, res in asrs.items():
                        hyp = res.get(k, {}).get(tag)
                        if hyp is None:
                            continue
                        tr = target_reading(sub, hyp, tg)
                        row[an] = {**tr, "hyp": hyp}
                    fams = family_verdicts(row)
                    row["disagree"] = bool(fams["whisper"] and fams["funasr"] and fams["whisper"] != fams["funasr"])
                    rows.append(row)
    return rows


ASR_NAMES = {"whisper_medium": "whisper medium", "sensevoice_small": "SenseVoiceSmall", "paraformer_zh": "paraformer-zh"}
VERDICT_ZH = {"tw": "台灣音", "alt": "誤讀", "other": "他字", "missing": "漏", "lexical": "照詞寫（無從判斷）"}


def summarize_cross(table: list[dict], kind: str = "raw") -> list[dict]:
    """每句×每個修正字：各版本各 ASR 寫的字與判定（只取 kind＝raw 或 post）。"""
    out: dict = {}
    for r in table:
        if r["kind"] != kind:
            continue
        k = (r["k"], r["char"])
        row = out.setdefault(k, {"k": r["k"], "char": r["char"], "word": r["word"], "tw": r["tw"], "alt": r["alt"],
                                 "method": r["method"]})
        for an in ASR_NAMES:
            if an in r:
                row[f"{r['version']}_{an}"] = r[an]
        row[f"{r['version']}_disagree"] = r["disagree"]
    return list(out.values())


def render_md21(rep: dict) -> str:
    L = ["# 旁白修正 v2.1：「沖散」與 20 句第二套 ASR 交叉驗證", ""]
    ch = rep.get("chong_san")
    if ch:
        L += [f"- 採用：`{ch['adopted']}`（{ch['method']}）", f"- 拼回後驗證：{ch['final_checks']}", ""]
    L += ["## 交叉驗證（raw 音檔；後製音檔見 report.json 的 cross_asr）", "",
          "判定：台灣音＝ASR 寫的字與台灣讀音的聲母韻母（聲調類：聲調）相同；誤讀＝與誤讀相同；"
          "照詞寫＝寫原字，純聲調差異 ASR 無從判斷。", ""]
    names = [n for n in ASR_NAMES if n in rep["asr_models"]]
    L.append("| 句 | 字 | 台灣／誤讀 | " + " | ".join(f"v1 {ASR_NAMES[n]}" for n in names) + " | "
             + " | ".join(f"v2.1 {ASR_NAMES[n]}" for n in names) + " | v2.1 兩家族不一致 |")
    L.append("|" + "---|" * (4 + 2 * len(names)))
    for r in rep["summary_raw"]:
        cells = []
        for ver in ("v1", "v2_1"):
            for n in names:
                v = r.get(f"{ver}_{n}")
                cells.append(f"{v['hyp_char'] or '—'} {VERDICT_ZH[v['verdict']]}" if v else "")
        L.append(f"| {r['k']} | {r['char']} | {r['tw']}／{r['alt']} | " + " | ".join(cells)
                 + f" | {'**是**' if r.get('v2_1_disagree') else ''} |")
    d = rep["disagreements"]
    L += ["", f"## 兩家族判定不一致（共 {len(d)} 列，含 v1／v2.0／v2.1 × raw／post）", ""]
    for r in d:
        hyps = "；".join(f"{ASR_NAMES[n]}：{r[n]['hyp']}（{r[n]['hyp_char'] or '—'} {VERDICT_ZH[r[n]['verdict']]}）"
                        for n in names if n in r)
        L.append(f"- {r['k']} {r['char']} {r['version']} {r['kind']}：{hyps}")
    return "\n".join(L) + "\n"


def cmd_report(a) -> int:
    import soundfile as sf
    import subprocess
    OUT21.mkdir(parents=True, exist_ok=True)
    # ab_compare_v2_1：每句 v1 → 0.5 s → v2.1（後製後音檔），句間 1.2 s
    gap = np.zeros(int(0.5 * SR), dtype=np.float32)
    sep = np.zeros(int(1.2 * SR), dtype=np.float32)
    v1 = {k: post for k, _, _, post in sentence_audio("v1")}
    ab, order = [], []
    for k, _, _, post in sentence_audio("v2_1"):
        ab += [v1[k], gap, post, sep]
        order.append(k)
    wav = OUT21 / "ab_compare_v2_1.wav"
    sf.write(str(wav), np.concatenate(ab), SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3",
                    str(OUT21 / "ab_compare_v2_1.mp3")], check=True)
    wav.unlink()
    meta = json.loads((OUT21 / "sent16k" / "index.json").read_text(encoding="utf-8"))
    asrs = {}
    for n in ASR_NAMES:
        p = OUT21 / f"asr_{n}.json"
        if p.exists():
            asrs[n] = json.loads(p.read_text(encoding="utf-8"))
    table = cross_table(meta, asrs)

    def load(name):
        p = OUT21 / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    vc, rw, extra = load("vc.json"), load("rewrite.json"), load("pipeline.json") or {}
    rep = {"ab_order": order, "asr_models": list(asrs), **extra,
           "summary_raw": summarize_cross(table, "raw"), "disagreements": [r for r in table if r["disagree"]],
           "cross_asr": table,
           "vc_trial": {"base": vc["base"], "top": vc["cands"][:6], "n_cands": len(vc["cands"]),
                        "n_pass": sum(c["all_pass"] and "散" in c["asr"] for c in vc["cands"])} if vc else None,
           "rewrite_trial": {"base_sim_ref": rw["base_sim_ref"], "n_pass": rw["n_pass"], "n": len(rw["cands"]),
                             "cands": [{k: c[k] for k in ("file", "variant", "text", "sec", "asr", "cer", "all_pass",
                                                          "spk_sim_ref")}
                                       | {"san_ctc": next(x["ctc_margin"] for x in c["checks"] if x["char"] == "散")}
                                       for c in rw["cands"]]} if rw else None}
    (OUT21 / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (OUT21 / "report.md").write_text(render_md21(rep), encoding="utf-8")
    print(f"交叉驗證 {len(table)} 列，不一致 {len(rep['disagreements'])} 列")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("vc")
    p.add_argument("--n", type=int, default=2, help="每個來源×範圍轉幾次（不同 seed）")
    p = sub.add_parser("adopt")
    p.add_argument("--src", choices=["vc", "rewrite"], default="rewrite")
    p.add_argument("--file", nargs="+", required=True)
    p.add_argument("--force", action="store_true")
    sub.add_parser("timbre")
    p = sub.add_parser("rewrite")
    p.add_argument("--n", type=int, default=8)
    sub.add_parser("asr-whisper")
    sub.add_parser("asr-funasr")
    sub.add_parser("report")
    a = ap.parse_args()
    return {"vc": cmd_vc, "timbre": cmd_timbre, "rewrite": cmd_rewrite, "adopt": cmd_adopt, "asr-whisper": cmd_asr_whisper, "asr-funasr": cmd_asr_funasr,
            "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
