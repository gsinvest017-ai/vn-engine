"""CosyVoice2 zero-shot 旁白合成（在 WSL 的 ~/.venv-cosy 執行）。

沿用 gs-agent-workshop/scripts/tts_cosyvoice.py 的做法：
- 每句合成 N 個候選，用 faster-whisper 回聽、以拼音層 CER 挑發音最準的一個
- torchaudio 的 load 走 torchcodec 在 cu128 環境載不起來 → monkeypatch 成 soundfile
- zero_shot 模式保留台灣腔與語氣；prompt 必須是單段、降噪、逐字稿精準，否則會跳字（見 Narrator）
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
CHUNK_MIN = 16       # 合成單位最少字數；更短的句子要跟前後句併在一起唸
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
    """依 。！？ 切句，再把相鄰句子併成 CHUNK_MIN–MAX_SENT 字的合成單位。

    不能讓短句單獨合成：prompt 逐字稿（~30 字）遠長於目標文字時，CosyVoice 常只吐出底噪或亂碼
    （實測「然後，我聽見了。」三次失敗兩次；唸兩遍再切半也不行，模型常只唸一遍）。
    和後面的句子接在一起唸就穩了（「然後，我聽見了。不是雨聲。是櫓聲。」）。
    單句仍超過 MAX_SENT 的，依 ，、；： 再切。"""
    import re
    sents: list[str] = []
    for x in [x.strip() for x in re.split(r"(?<=[。！？])", text) if x.strip()]:
        if len(x) <= MAX_SENT:
            sents.append(x)
            continue
        buf = ""
        for y in [z for z in re.split(r"(?<=[，、；：])", x) if z]:
            if buf and len(buf) + len(y) > MAX_SENT:
                sents.append(buf)
                buf = y
            else:
                buf += y
        if buf:
            sents.append(buf)
    chunks: list[str] = []
    for x in sents:
        too_short = chunks and (len(chunks[-1]) < CHUNK_MIN or len(x) < CHUNK_MIN)
        if too_short and len(chunks[-1]) + len(x) <= MAX_SENT + CHUNK_MIN:
            chunks[-1] += x
        else:
            chunks.append(x)
    return chunks


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
                 instruct: str | None = None, mode: str = "zero_shot"):
        """mode：
        - zero_shot（預設）：音色＋韻律＋口音都跟 prompt。台灣腔、老人慢慢講的語氣都靠這個。
          跳字問題靠「prompt 用單段、降噪、逐字稿精準」解決（實測 4 段拼接 prompt 9 次 0 次合格，
          單段降噪 8/9 合格、CER 平均 0.05）。
        - cross_lingual：只取音色、不對齊 prompt 逐字稿，最不會跳字，但**口音與語氣會丟掉**，
          退回模型預設的大陸腔（使用者試聽確認），旁白不用。
        instruct2 也一樣會丟掉 prompt 韻律（frontend_instruct2 刪掉了 llm_prompt_speech_token）。"""
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
        self.mode = mode
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
        elif self.mode == "zero_shot":
            gen = self.cv.inference_zero_shot(text, self.prompt_text, self.prompt_wav,
                                              stream=False, text_frontend=self.text_frontend)
        else:
            gen = self.cv.inference_cross_lingual(text, self.prompt_wav,
                                                  stream=False, text_frontend=self.text_frontend)
        return self.torch.cat([o["tts_speech"] for o in gen], dim=1)

    def score(self, audio, ref: str) -> float:
        segs, _ = self.asr.transcribe(self.to16k(audio).squeeze(0).numpy(), language="zh", beam_size=2)
        return cer("".join(s.text for s in segs), ref)

    def _best(self, text: str):
        """單一合成單位：合成 N 個候選，淘汰語速異常的，剩下挑 CER 最低；全部異常就挑最接近正常語速的。"""
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
        """回傳 (audio tensor [1, n], CER, 語速異常的句數)；長段落切句合成再接起來。
        CER 是各合成單位自己評分的字數加權平均，不再拿整段重評一次（省時間，結果相同）。"""
        pieces, flags, weighted, chars = [], 0, 0.0, 0
        gap = self.torch.zeros(1, int(SENT_GAP * SR_OUT))
        clause_gap = self.torch.zeros(1, int(CLAUSE_GAP * SR_OUT))
        for sent in split_sentences(text):
            audio, c, bad = self._best(sent)
            scored = [(sent, c)]
            clauses = split_clauses(sent)
            if bad and len(clauses) > 1:
                # 5 個候選都不正常（多半是唸到逗號就停）→ 拆成子句各自合成再接
                parts, bad, scored = [], 0, []
                for cl in clauses:
                    a, cc, b = self._best(cl)
                    bad += b
                    parts += [a, clause_gap]
                    scored.append((cl, cc))
                audio = self.torch.cat(parts[:-1], dim=1)
            for t, cc in scored:
                n = len(t)
                weighted, chars = weighted + cc * n, chars + n
            flags += bad
            pieces += [audio, gap]
        audio = self.torch.cat(pieces[:-1], dim=1)
        return audio, weighted / max(chars, 1), flags
