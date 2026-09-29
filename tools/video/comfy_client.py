"""MiniMax H3 圖生影片的 ComfyUI API client。

把 AIGF-V2 工作流（UI 格式、含 subgraph）攤平成 API 格式直接送 /prompt，
不依賴 UI 匯出檔。節點接線對照 AIGF-V2/工作流文件.json 的
「Image to Video (MiniMax H3)」subgraph。
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TURBO_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"

FPS = 24


def snap_length(seconds: float) -> int:
    """秒數 → 幀數，向上對齊模型的 17k+5 網格（同工作流內的 ComfyMathExpression）。"""
    frames = max(5, round(seconds * FPS))
    return frames + (5 - frames % 17) % 17


@dataclass
class ClipJob:
    prompt: str
    first_frame: str | None     # 已上傳到 ComfyUI input/ 的檔名；None = 文生影片
    seconds: float = 5.0
    width: int = 1056
    height: int = 608
    seed: int = 1
    turbo: bool = True          # 8-step turbo LoRA；False = 原生 20 步
    last_frame: str | None = None
    ref_image: str | None = None  # 設了就改走 ReferenceToVideo：同一場景、不同鏡頭（提示詞用 <Picture 1>）
    prefix: str = "video/anqu"


def build_prompt(job: ClipJob) -> dict:
    model = ["1", 0]
    g: dict[str, dict] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "7": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["3", 0], "vae": ["4", 0], "prompt": job.prompt,
            "width": job.width, "height": job.height,
            "length": snap_length(job.seconds)}},
        "10": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": job.seed}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["4", 0]}},
        "14": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["12", 0], "vae": ["5", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "audio": ["14", 0], "fps": FPS}},
        "16": {"class_type": "SaveVideo", "inputs": {
            "video": ["15", 0], "filename_prefix": job.prefix,
            "format": "mp4", "format.codec": "auto"}},
    }
    if job.turbo:
        g["2"] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": ["1", 0], "lora_name": TURBO_LORA, "strength_model": 1.0}}
        model = ["2", 0]
    if job.ref_image:
        g["6"] = {"class_type": "LoadImage", "inputs": {"image": job.ref_image}}
        g["7"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["3", 0], "vae": ["4", 0], "audio_vae": ["5", 0], "prompt": job.prompt,
            "width": job.width, "height": job.height, "length": snap_length(job.seconds),
            "ref_image_size": "match",
            # Autogrow 輸入在 API 格式裡是「群組.前綴+序號」；鍵名錯了不會報錯，只會被默默忽略
            "ref_images.ref_image_0": ["6", 0]}}
    elif job.first_frame:
        g["6"] = {"class_type": "LoadImage", "inputs": {"image": job.first_frame}}
        g["7"]["inputs"]["first_frame"] = ["6", 0]
    if job.last_frame:
        g["17"] = {"class_type": "LoadImage", "inputs": {"image": job.last_frame}}
        g["7"]["inputs"]["last_frame"] = ["17", 0]
    g["8"] = {"class_type": "BasicGuider", "inputs": {"model": model, "conditioning": ["7", 0]}}
    g["9"] = {"class_type": "BasicScheduler", "inputs": {
        "model": model, "scheduler": "simple", "steps": 8 if job.turbo else 20, "denoise": 1.0}}
    g["12"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["11", 0], "guider": ["8", 0], "sampler": ["10", 0],
        "sigmas": ["9", 0], "latent_image": ["7", 1]}}
    return g


class ComfyClient:
    def __init__(self, url: str = "http://127.0.0.1:8188"):
        self.url = url.rstrip("/")
        self.client_id = uuid.uuid4().hex

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(self.url + path, timeout=30) as r:
            return json.loads(r.read())

    def ping(self) -> bool:
        try:
            self._get("/system_stats")
            return True
        except OSError:
            return False

    def upload_image(self, path: Path, name: str | None = None) -> str:
        name = name or path.name
        boundary = uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ])
        req = urllib.request.Request(self.url + "/upload/image", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read())
        return f"{res['subfolder']}/{res['name']}" if res.get("subfolder") else res["name"]

    def submit(self, graph: dict) -> str:
        data = json.dumps({"prompt": graph, "client_id": self.client_id}).encode()
        req = urllib.request.Request(self.url + "/prompt", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["prompt_id"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ComfyUI 拒收 prompt：{e.read().decode(errors='replace')}") from e

    def wait(self, prompt_id: str, timeout: float = 3600, poll: float = 5) -> dict:
        start = time.time()
        while time.time() - start < timeout:
            hist = self._get(f"/history/{prompt_id}")
            if prompt_id in hist:
                entry = hist[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                    raise RuntimeError(f"ComfyUI 執行失敗：{json.dumps(msgs, ensure_ascii=False)[:2000]}")
                if status.get("completed", True):
                    return entry
            time.sleep(poll)
        raise TimeoutError(f"prompt {prompt_id} 超過 {timeout}s 未完成")

    def download_outputs(self, entry: dict, dest: Path) -> Path:
        for out in entry.get("outputs", {}).values():
            for key in ("images", "videos", "gifs"):
                for f in out.get(key, []):
                    if not str(f.get("filename", "")).endswith((".mp4", ".webm", ".mkv")):
                        continue
                    q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                                "type": f.get("type", "output")})
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with urllib.request.urlopen(f"{self.url}/view?{q}", timeout=300) as r:
                        dest.write_bytes(r.read())
                    return dest
        raise RuntimeError(f"輸出裡找不到影片：{json.dumps(entry.get('outputs'), ensure_ascii=False)[:1000]}")

    def run(self, job: ClipJob, dest: Path) -> Path:
        pid = self.submit(build_prompt(job))
        return self.download_outputs(self.wait(pid), dest)
