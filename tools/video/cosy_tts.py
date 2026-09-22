"""CosyVoice2 zero-shot 旁白合成（在 WSL 的 ~/.venv-cosy 執行）。

沿用 gs-agent-workshop/scripts/tts_cosyvoice.py 的做法：
- 每句合成 N 個候選，用 faster-whisper 回聽、以拼音層 CER 挑發音最準的一個
- torchaudio 的 load 走 torchcodec 在 cu128 環境載不起來 → monkeypatch 成 soundfile
- **送進模型前一律轉簡體**：CosyVoice2 讀繁體字會大量唸錯（實測同一句 CER 0.61 → 簡體 0.00），
  只影響模型讀的字，聲音不變；CER 仍對照原本的繁體稿計算（拼音層比對，繁簡同音）

聲音樣本來自 Mozilla Common Voice zh-TW（CC0），見 voice_audition.py。
"""
from __future__ import annotations

import sys
from pathlib import Path

HOME = Path.home()
sys.path.append(str(HOME / "CosyVoice"))
sys.path.append(str(HOME / "CosyVoice" / "third_party" / "Matcha-TTS"))

MODEL_DIR = str(HOME / "models" / "CosyVoice2-0.5B")
SR_OUT = 24000
CER_GOOD = 0.08
# 字/秒；超出這範圍的候選直接淘汰。上限壓在 3.8：老人聲正常只唸 2.3–3.2 字/秒，
# 唸到逗號就停（後半句被吃掉）的候選因為音檔變短，換算出來會「很快」，靠這個抓
RATE_OK = (2.0, 3.8)
CLAUSE_GAP = 0.18
MAX_SENT = 40          # 長段落切句再合成：CosyVoice 一次唸太長會飄、甚至卡在 40 秒上限
SENT_GAP = 0.35


def split_clauses(sent: str) -> list[str]:
    """依 ，、；： 切成子句（保留標點）；太短的併回前一段。"""
    import re
    out: list[str] = []
    for x in [z for z in re.split(r"(?<=[，、；：])", sent) if z.strip()]:
        if out and len(x) < 4:
            out[-1] += x
        else:
            out.append(x)
    return out


def split_sentences(text: str) -> list[str]:
    """依 。！？ 切句；仍超過 MAX_SENT 的再依 ，、；切；太短的併回前句。"""
    import re
    parts = [x.strip() for x in re.split(r"(?<=[。！？])", text) if x.strip()]
    fine: list[str] = []
    for x in parts:
        if len(x) <= MAX_SENT:
            fine.append(x)
            continue
        buf = ""
        for y in [z for z in re.split(r"(?<=[，、；：])", x) if z]:
            if buf and len(buf) + len(y) > MAX_SENT:
                fine.append(buf)
                buf = y
            else:
                buf += y
        if buf:
            fine.append(buf)
    merged: list[str] = []
    for x in fine:
        if merged and len(x) < 6:
            merged[-1] += x
        else:
            merged.append(x)
    return merged


def cer(hyp: str, ref: str) -> float:
    """拼音 token 級編輯距離 / 參考長度：同音字不算錯，只看發音與聲調。"""
    from pypinyin import Style, lazy_pinyin

    def toks(s: str) -> list[str]:
        zh = "".join(ch for ch in s if "一" <= ch <= "鿿")
        return lazy_pinyin(zh, style=Style.TONE3)

    a, b = toks(hyp), toks(ref)
    if not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(b)


class Narrator:
    def __init__(self, prompt_wav: Path, prompt_text: str, candidates: int = 3,
                 instruct: str | None = None):
        import soundfile as sf
        import torch
        import torchaudio

        def _load_wav(wav, target_sr):
            data, sr = sf.read(str(wav), dtype="float32")
            t = torch.from_numpy(data)
            t = t.mean(dim=1).unsqueeze(0) if t.ndim > 1 else t.unsqueeze(0)
            if sr != target_sr:
                t = torchaudio.transforms.Resample(sr, target_sr)(t)
            return t

        import cosyvoice.cli.frontend as _fr
        import cosyvoice.utils.file_utils as _fu
        _fu.load_wav = _load_wav
        _fr.load_wav = _load_wav
        from cosyvoice.cli.cosyvoice import CosyVoice2
        from faster_whisper import WhisperModel
        import opencc
        self.t2s = opencc.OpenCC("t2s").convert

        try:
            import tn  # noqa: F401
            self.text_frontend = True
        except ImportError:
            self.text_frontend = False

        self.torch = torch
        self.prompt_wav = str(prompt_wav)
        self.prompt_text = self.t2s(prompt_text)
        self.instruct = instruct
        self.n = max(1, candidates)
        self.cv = CosyVoice2(MODEL_DIR, load_jit=False, load_trt=False, fp16=True)
        try:
            self.asr = WhisperModel("medium", device="cuda", compute_type="float16")
        except Exception:
            self.asr = WhisperModel("small", device="cpu", compute_type="int8")
        self.to16k = torchaudio.transforms.Resample(SR_OUT, 16000)

    @staticmethod
    def speakable(text: str) -> str:
        """去掉模型唸不好的符號：「」『』 會讓 CosyVoice 前端整句吞掉（實測「唯獨『暗河』兩字」合成出無聲），
        開頭的 …… 會吃掉後面一截；改成停頓用的逗號。字幕仍用原文。"""
        for q in "「」『』":
            text = text.replace(q, "")
        text = text.replace("……", "，").replace("…", "，")
        return text.strip("，").strip() or text

    def _once(self, text: str):
        text = self.t2s(self.speakable(text))
        if self.instruct:
            gen = self.cv.inference_instruct2(text, self.instruct, self.prompt_wav,
                                              stream=False, text_frontend=self.text_frontend)
        else:
            gen = self.cv.inference_zero_shot(text, self.prompt_text, self.prompt_wav,
                                              stream=False, text_frontend=self.text_frontend)
        return self.torch.cat([o["tts_speech"] for o in gen], dim=1)

    def score(self, audio, ref: str) -> float:
        segs, _ = self.asr.transcribe(self.to16k(audio).squeeze(0).numpy(), language="zh", beam_size=2)
        return cer("".join(s.text for s in segs), ref)

    def _best(self, text: str):
        """單句：合成 N 個候選，淘汰語速異常的，剩下挑 CER 最低；全部異常就挑最接近正常語速的。"""
        n_chars = sum(1 for ch in text if "一" <= ch <= "鿿") or len(text)
        cands = []
        for _ in range(self.n):
            audio = self._once(text)
            rate = n_chars / (audio.shape[1] / SR_OUT)
            c = self.score(audio, text)
            ok = RATE_OK[0] <= rate <= RATE_OK[1]
            cands.append((not ok, c, abs(rate - 3.0), audio))
            if ok and c <= CER_GOOD:
                break
        cands.sort(key=lambda x: (x[0], x[1], x[2]))
        bad_rate, c, _, audio = cands[0]
        return audio, c, bad_rate

    def synth(self, text: str):
        """回傳 (audio tensor [1, n], 全段 CER, 語速異常的句數)；長段落切句合成再接起來。"""
        pieces, flags = [], 0
        gap = self.torch.zeros(1, int(SENT_GAP * SR_OUT))
        clause_gap = self.torch.zeros(1, int(CLAUSE_GAP * SR_OUT))
        for sent in split_sentences(text):
            audio, _, bad = self._best(sent)
            clauses = split_clauses(sent)
            if bad and len(clauses) > 1:
                # 5 個候選都不正常（多半是唸到逗號就停）→ 拆成子句各自合成再接
                parts, bad = [], 0
                for cl in clauses:
                    a, _, b = self._best(cl)
                    bad += b
                    parts += [a, clause_gap]
                audio = self.torch.cat(parts[:-1], dim=1)
            flags += bad
            pieces += [audio, gap]
        audio = self.torch.cat(pieces[:-1], dim=1)
        return audio, self.score(audio, text), flags
