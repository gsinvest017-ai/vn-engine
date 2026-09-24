"""v2.1b：第一章_03_06:0 句首「檔案」重生（v2.0／v2.1 送 TTS「黨案」，三套 ASR 都聽成「火案」）。

換送 TTS 的寫法（原字「档」、「挡」、句首加逗號…），每種 8 個候選，依 narr_fix 的挑選規則，外加：
三套 ASR（whisper medium、SenseVoiceSmall、paraformer-zh）至少兩套在「檔」的字位寫 檔/档/黨/党/擋/挡
（聲母韻母是 dang）、沒有「多數 ASR 同意」的其他誤讀，而且模擬拼回後（splice 的變速與接回）驗證全過、
F0 聲調分類器判第三聲。分層見 tier()；沒有候選同時滿足時，優先保 dang 的聲母韻母。

    # WSL ~/.venv-cosy（GPU）
    python tools/video/narr_dang.py evidence        # v1 / v2.1 該句切出來（raw、後製；v2.1 取 backup_v2_1）
    python tools/video/narr_dang.py gen [--n 8]     # 每種寫法 n 個候選：聲學驗證＋whisper，另存 16 kHz 給 FunASR
    python tools/video/narr_dang.py asr-whisper --dir evidence
    # WSL ~/.venv-asr2
    python tools/video/narr_dang.py asr-funasr --dir cands16k   # 或 --dir evidence
    python tools/video/narr_dang.py pick            # WSL ~/.venv-cosy：模擬拼回後再驗證、套規則挑候選、加進 cands.json
    #  接著：narr_fix.py splice --pick ... → narr_post.py → narr_fix.py plancheck → evidence --final → ASR → ab

輸出在 video_out/remaster_v2/narration_fix_v2_1b/。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import narr_fix as F  # noqa: E402

OUT = F.V2 / "narration_fix_v2_1b"
BACKUP21 = F.V2 / "backup_v2_1" / "narration"
KEY, CI = "第一章_03_06", 0
K = f"{KEY}:{CI}"
SENT = "檔案裡最早的文字寫於乾隆年間。字跡斷斷續續，像有人在極度不安之中留下的紀錄："
REST = "里最早的文字写于乾隆年间。字机断断续续，像有人在极度不安之中留下的纪录："
# 送 TTS 的文字（已是簡體、已含「跡→机」替換；直接給 inference_zero_shot，不再過 tts_text）
VARIANTS = {
    "orig_dang": "档案" + REST,          # 原字：讓模型自己唸（v1 是這樣，dàng）
    "block_dang": "挡案" + REST,         # 擋：兩岸都唸 dǎng
    "comma_party": "，党案" + REST,      # v2.0 的「黨」，句首加逗號改韻律
    "comma_block": "，挡案" + REST,
    "comma_orig": "，档案" + REST,
}
DANG_CHARS = set("檔档黨党擋挡")
ASRS = ("whisper_medium", "sensevoice_small", "paraformer_zh")
VERSIONS = {"v1": F.BACKUP, "v2_1": BACKUP21, "v2_1b": F.NARR}
SR = F.SR


# ---------------------------------------------------------------- 純函式（Windows 可測）
def hyp_char_at(ref: str, hyp: str, i: int) -> str:
    """ASR 轉寫 hyp 對齊到參考稿 ref 第 i 個漢字位置的字（拼音層對齊；刪除則空字串）。"""
    import narr_vc as V
    al = V.align_hyp(ref, hyp)
    j = al[i] if i < len(al) else None
    return "" if j is None else F.zh_only(hyp)[j]


def dang_votes(asr_texts: dict[str, str], ref: str = SENT, i: int = 0) -> tuple[int, dict[str, str]]:
    """幾套 ASR 在「檔」字位寫成 dang 的字（聲母韻母對）。"""
    chars = {n: hyp_char_at(ref, t, i) for n, t in asr_texts.items()}
    return sum(c in DANG_CHARS for c in chars.values()), chars


def consensus_errors(asr_texts: dict[str, str], ref: str = SENT, min_votes: int = 2) -> list[int]:
    """參考稿字位裡，至少 min_votes 套 ASR 寫成聲母韻母不同的字（或漏字）的位置——多數 ASR 同意的新誤讀
    （例：「裡」三套都寫 密/例）。比對不看聲調（聲調差異 ASR 本來就判不出來）。"""
    import narr_vc as V
    rp = [V._toneless(p) for _, p in V._toks(ref)]
    bad = [0] * len(rp)
    for hyp in asr_texts.values():
        hp = [V._toneless(p) for _, p in V._toks(hyp)]
        for i, j in enumerate(V.align_hyp(ref, hyp)):
            bad[i] += j is None or hp[j] != rp[i]
    return [i for i, b in enumerate(bad) if b >= min_votes]


def dang_check(checks: list[dict]) -> dict | None:
    return next((x for x in checks if x["char"] == "檔"), None)


def tier(c: dict, cer_ok: float, orig_sec: float) -> int:
    """0＝全部條件：narr_fix 規則（候選驗證全過、語速、CER、長度可拉回）＋≥2 套 ASR 寫 dang＋沒有多數 ASR
    同意的其他誤讀＋拼回後（final_checks，模擬 splice 的變速與接回；沒有就用候選本身）驗證全過且聲調分類器判 3 聲；
    1＝dang ≥2 套、沒有其他誤讀、其他條件都過，只差「檔」的聲調；2＝dang ≥2 套、其他條件有缺；3＝dang 不到 2 套。"""
    final = c.get("final_checks") or c["checks"]
    d = dang_check(final) or {}
    length_ok = c["rate_ok"] and c["cer"] <= cer_ok and F.TEMPO_OK[0] <= c["sec"] / orig_sec <= F.TEMPO_OK[1]
    if c.get("dang_votes", 0) < 2:
        return 3
    if c.get("consensus_errors"):
        return 2
    if (length_ok and c["all_pass"] and all(F.check_ok(x) for x in final)
            and d.get("tone_pred") == 3 and d.get("tone_verdict") == "pass"):
        return 0
    others_ok = all(F.check_ok(x) for x in c["checks"] + final if x["char"] != "檔")
    return 1 if others_ok and length_ok else 2


def choose(cands: list[dict], orig_sec: float, cer_ok: float) -> tuple[int, int]:
    """最好的一層裡依 narr_fix.rank_key 挑（sec 用有聲長度）。回傳 (index, tier)。"""
    tiers = [tier(c, cer_ok, orig_sec) for c in cands]
    best_t = min(tiers)
    pool = [j for j, t in enumerate(tiers) if t == best_t]
    j = min(pool, key=lambda j: F.rank_key(cands[j], orig_sec, cer_ok))
    return j, best_t


# ---------------------------------------------------------------- WSL
def _resample16(y: np.ndarray) -> np.ndarray:
    import torch
    import torchaudio
    return torchaudio.functional.resample(torch.from_numpy(y), SR, 16000).numpy()


def sentence_cut(d: Path):
    import soundfile as sf
    from cosy_tts import split_sentences
    idx = F.load_index(d)
    raw, _ = sf.read(str(d / f"{KEY}.raw.wav"), dtype="float32")
    post, _ = sf.read(str(d / f"{KEY}.wav"), dtype="float32")
    n = len(split_sentences("".join(idx[KEY]["texts"])))
    s, e = F.chunk_spans(raw, SR, n)[CI]
    ps, pe = F.post_span((s / SR, e / SR), F.lead_trim(raw, SR), idx[KEY]["tempo"])
    a_, b_ = max(0, int((ps - 0.08) * SR)), min(len(post), int((pe + 0.08) * SR))
    return raw[s:e], post[a_:b_]


def cmd_evidence(a) -> int:
    """該句 raw／後製切出來，16 kHz 存到 evidence/，並用 narr_fix.Checker 驗一次（raw）。"""
    import soundfile as sf
    d = OUT / "evidence"
    d.mkdir(parents=True, exist_ok=True)
    chk = F.Checker()
    vers = ["v2_1b"] if a.final else ["v1", "v2_1"]
    res_p = OUT / "evidence_checks.json"
    res = json.loads(res_p.read_text(encoding="utf-8")) if res_p.exists() else {}
    for ver in vers:
        raw, post = sentence_cut(VERSIONS[ver])
        for kind, y in (("raw", raw), ("post", post)):
            sf.write(str(d / f"{ver}__{kind}.wav"), _resample16(y), 16000)
            sf.write(str(d / f"{ver}__{kind}.24k.wav"), y, SR)
        res[ver] = chk.check(raw, SR, SENT, KEY)
        print(ver, F.fmt_checks(res[ver]), flush=True)
    res_p.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


def cmd_gen(a) -> int:
    import soundfile as sf
    import torch
    from cosy_tts import RATE_OK, Narrator, cer
    vd = F.VOICES / "s70_C"
    nar = Narrator(vd / "prompt.wav", (vd / "prompt.txt").read_text(encoding="utf-8"), candidates=1,
                   asr_device="cpu")
    chk = F.Checker()
    cdir, d16 = OUT / "cands", OUT / "cands16k"
    cdir.mkdir(parents=True, exist_ok=True)
    d16.mkdir(exist_ok=True)
    path = OUT / "gen.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    done = {r["file"] for r in rows}
    n_chars = len(F.zh_only(SENT))
    for name, text in VARIANTS.items():
        if a.only and name not in a.only.split(","):
            continue
        for k in range(a.n):
            f = cdir / f"{name}_{k}.wav"
            if f.name in done:
                continue
            w = torch.cat([o["tts_speech"] for o in nar.cv.inference_zero_shot(
                text, nar.prompt_text, nar.prompt_wav, stream=False, text_frontend=nar.text_frontend)], dim=1)
            y = w.squeeze(0).cpu().numpy().astype(np.float32)
            sf.write(str(f), y, SR)
            sf.write(str(d16 / f.name), _resample16(y), 16000)
            txt = F.transcribe(nar, y)
            checks = chk.check(y, SR, SENT, KEY)
            sec = len(y) / SR
            r = {"file": f.name, "variant": name, "tts_text": text, "k": k, "sec": round(sec, 3), "asr": txt,
                 "cer": round(cer(txt, SENT), 3), "rate": round(n_chars / sec, 2),
                 "rate_ok": RATE_OK[0] <= n_chars / sec <= RATE_OK[1], "checks": checks,
                 "margin_sum": F.margin_sum(checks), "all_pass": all(F.check_ok(c) for c in checks)}
            rows.append(r)
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
            dg = dang_check(r) or {}
            print(f"{f.name} {r['sec']}s CER {r['cer']} 檔 tone={dg.get('tone_pred')} p3={dg.get('p_tw_tone')} "
                  f"pass={r['all_pass']} {txt}", flush=True)
    return 0


def cmd_asr_whisper(a) -> int:
    import soundfile as sf
    from faster_whisper import WhisperModel
    d = OUT / a.dir
    asr = WhisperModel("medium", device="cpu", compute_type="int8")
    out = {}
    for f in sorted(d.glob("*.wav")):
        if f.name.endswith(".24k.wav"):
            continue
        y, _ = sf.read(str(f), dtype="float32")
        segs, _ = asr.transcribe(y, language="zh", beam_size=2)
        out[f.name] = "".join(s.text for s in segs)
        print(f.name, out[f.name], flush=True)
    _merge(OUT / f"asr_{a.dir}_whisper_medium.json", out)
    return 0


def cmd_asr_funasr(a) -> int:
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
    d = OUT / a.dir
    models = {"sensevoice_small": AutoModel(model="iic/SenseVoiceSmall", device="cpu", disable_update=True),
              "paraformer_zh": AutoModel(model="paraformer-zh", device="cpu", disable_update=True)}
    for name, m in models.items():
        out = {}
        for f in sorted(d.glob("*.wav")):
            if f.name.endswith(".24k.wav"):
                continue
            kw = {"language": "zh", "use_itn": False} if name == "sensevoice_small" else {}
            r = m.generate(input=str(f), **kw)
            text = r[0]["text"] if r else ""
            if name == "sensevoice_small":
                text = rich_transcription_postprocess(text)
            out[f.name] = text.replace(" ", "")
            print(name, f.name, out[f.name], flush=True)
        _merge(OUT / f"asr_{a.dir}_{name}.json", out)
    return 0


def _merge(p: Path, new: dict) -> None:
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    old.update(new)
    p.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")


def load_asr(dir_: str) -> dict[str, dict[str, str]]:
    """{wav 檔名: {asr 名: 轉寫}}（whisper 的候選轉寫也可以用 gen.json 的 24 kHz 版；這裡一律用 16 kHz 重聽的）。"""
    out: dict[str, dict[str, str]] = {}
    for n in ASRS:
        p = OUT / f"asr_{dir_}_{n}.json"
        if p.exists():
            for f, t in json.loads(p.read_text(encoding="utf-8")).items():
                out.setdefault(f, {})[n] = t
    return out


def simulate_splice(y: np.ndarray, calib: float) -> np.ndarray:
    """與 narr_fix.cmd_splice 相同的處理（有聲部分變速到 v1 有聲長度＋校正量、match_level、沿用 v1 頭尾靜音），
    不寫入 narration；回傳拼回後的該句音檔。"""
    x1, _, s, t = F.v1_sentence(KEY, CI)
    v1 = x1[s:t]
    a1, b1 = F.voiced_bounds(v1)
    v0, v1_ = F.voiced_bounds(y)
    seg = y[v0:v1_]
    target = (b1 - a1) / SR + calib
    z = F.rubberband(seg, (len(seg) / SR) / target, OUT / "tmp_sim")
    return F.rebuild(v1, F.match_level(F.fit_length(z, round(target * SR)), v1[a1:b1]))


def cmd_pick(a) -> int:
    """gen.json＋三套 ASR＋模擬拼回後驗證 → 分層挑選；把選中的候選加進 narration_fix/cands.json
    （從 backup_v2_1 的 cands.json 重做，不累積前一次的選擇），印出 splice 的 --pick。"""
    import soundfile as sf
    rows = json.loads((OUT / "gen.json").read_text(encoding="utf-8"))
    asr = load_asr("cands16k")
    res = json.loads((F.V2 / "backup_v2_1" / "narration_fix" / "cands.json").read_text(encoding="utf-8"))
    e = res[K]
    cer_ok = F.cer_limit(e.get("v1_cer"))
    calib = json.loads((F.OUT / "calib.json").read_text(encoding="utf-8")).get(K, 0.0)
    x1, _, s, t = F.v1_sentence(KEY, CI)
    a1, b1 = F.voiced_bounds(x1[s:t])
    orig_voiced = (b1 - a1) / SR
    chk = F.Checker()
    cands = []
    for r in rows:
        y, _ = sf.read(str(OUT / "cands" / r["file"]), dtype="float32")
        v0, v1_ = F.voiced_bounds(y)
        a3 = asr.get(r["file"], {})
        votes, chars = dang_votes(a3)
        c = {**r, "voiced_sec": round((v1_ - v0) / SR, 3), "sec": (v1_ - v0) / SR,
             "dang_votes": votes, "dang_chars": chars, "asr3": a3, "consensus_errors": consensus_errors(a3)}
        if votes >= 2 and F.TEMPO_OK[0] <= c["sec"] / orig_voiced <= F.TEMPO_OK[1]:
            c["final_checks"] = chk.check(simulate_splice(y, calib), SR, SENT, KEY)
        cands.append(c)
    for c in cands:
        c["tier"] = tier(c, cer_ok, orig_voiced)
    j, best_t = choose(cands, orig_voiced, cer_ok)
    c = cands[j]

    def tone(checks, ch):
        q = next((x for x in checks or [] if x["char"] == ch), {})
        return [q.get("tone_pred"), q.get("p_tw_tone")] if q else None
    summary = [{k: x[k] for k in ("file", "variant", "voiced_sec", "cer", "rate_ok", "all_pass", "dang_votes",
                                  "dang_chars", "consensus_errors", "tier")}
               | {"cand_檔": tone(x["checks"], "檔"), "cand_跡": tone(x["checks"], "跡"),
                  "final_檔": tone(x.get("final_checks"), "檔"), "final_跡": tone(x.get("final_checks"), "跡")}
               for x in cands]
    pick = {"chosen": c["file"], "tier": best_t, "orig_voiced_sec": round(orig_voiced, 3), "cer_ok": cer_ok,
            "calib": calib, "cands": summary}
    (OUT / "pick.json").write_text(json.dumps(pick, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    for x in summary:
        print(x, flush=True)
    print(f"選 {c['file']}（tier {best_t}）", flush=True)
    if a.dry_run:
        return 0
    # 加進 narration_fix/cands.json（sec 用候選全長，與 synth 產生的候選一致；splice 會自己重算有聲長度）
    y, _ = sf.read(str(OUT / "cands" / c["file"]), dtype="float32")
    out = f"{KEY}_{CI}_v21b_{Path(c['file']).stem}.wav"
    sf.write(str(F.OUT / "cands" / out), y, SR)
    sec = len(y) / SR
    entry = {"file": out, "sec": round(sec, 3), "asr": c["asr"], "cer": c["cer"], "rate": c["rate"],
             "rate_ok": c["rate_ok"], "checks": c["checks"], "margin_sum": c["margin_sum"],
             "all_pass": c["all_pass"], "v2_1b_from": f"narration_fix_v2_1b/cands/{c['file']}",
             "v2_1b_tts_text": c["tts_text"], "v2_1b_asr3": c["asr3"]}
    e["cands"] = [x for x in e["cands"] if x["file"] != out] + [entry]
    (F.OUT / "cands.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    idx = next(i for i, x in enumerate(e["cands"]) if x["file"] == out)
    print(f"加入 cands/{out}；splice 用 --pick '{json.dumps({K: idx}, ensure_ascii=False)}'")
    return 0


def cmd_ab(a) -> int:
    """ab_danga.mp3：後製音檔 v1 → 0.5 s → v2.1 → 0.5 s → v2.1b。"""
    import soundfile as sf
    import subprocess
    gap = np.zeros(int(0.5 * SR), dtype=np.float32)
    parts = []
    for ver in ("v1", "v2_1", "v2_1b"):
        y, _ = sf.read(str(OUT / "evidence" / f"{ver}__post.24k.wav"), dtype="float32")
        parts += [y, gap]
    dst = F.V2 / "narration_fix_v2_1" / "ab_danga.mp3"
    wav = OUT / "ab_danga.wav"
    sf.write(str(wav), np.concatenate(parts[:-1]), SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3",
                    str(dst)], check=True)
    wav.unlink()
    print(dst)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("evidence")
    p.add_argument("--final", action="store_true", help="只切現行 narration（v2.1b）")
    p = sub.add_parser("gen")
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--only", default="")
    for n in ("asr-whisper", "asr-funasr"):
        p = sub.add_parser(n)
        p.add_argument("--dir", default="cands16k")
    p = sub.add_parser("pick")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("ab")
    a = ap.parse_args()
    return {"evidence": cmd_evidence, "gen": cmd_gen, "asr-whisper": cmd_asr_whisper, "asr-funasr": cmd_asr_funasr,
            "pick": cmd_pick, "ab": cmd_ab}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
