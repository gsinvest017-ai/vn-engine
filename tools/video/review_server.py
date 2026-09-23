"""《暗渠之書》重製審片頁：各版成片播放、修正點時間碼跳轉、讀音 A/B 試聽、逐點審查筆記。

    python tools/video/review_server.py --host 192.168.11.197 --port 9201

掛在 gb10 Caddy 的 gs.video-factory.com/review/ 底下（handle_path 會剝掉 /review 前綴，
所以頁面內一律用相對路徑）。只讀：只送 video_out 內白名單副檔名的檔案，支援 HTTP Range
（瀏覽器拖曳 <video> 進度條需要）。刻意不接 gs-video-factory 的審核佇列：那邊的「核可」
會直接上傳 YouTube，未審完的片不能放進去。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video_out"
DOCS = ROOT / "docs" / "remaster_v2"
MIME = {".mp4": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
        ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json"}
CHUNK = 1 << 20

# 已知限制（hanzi id → 說明；手動維護，解掉就刪）。時間碼取 hanzi 報告的 final_sec
KNOWN = {
    "H084": "第三章燈籠大特寫「祆祠覞袖」：追蹤失敗未修（v2.2 重生）",
    "H055": "第一章神龕兩側紅聯：遮擋＋失焦，追蹤失敗未修（v2.2 重生）",
    "H097": "第三章燈籠金字：只做失焦（v2.2 重生）",
}


def versions() -> list[dict]:
    """找出所有版本成片，舊到新。"""
    out = []
    v1 = OUT / "v1_baseline" / "anqu_narrated.mp4"
    if v1.exists():
        out.append({"label": "v1（2026-09-22 原版）", "path": "v1_baseline/anqu_narrated.mp4"})
    for f in sorted((OUT / "remaster_v2").glob("anqu_narrated_v2*.mp4")):
        tag = f.stem.removeprefix("anqu_narrated_").replace("_", ".")
        out.append({"label": tag, "path": f"remaster_v2/{f.name}"})
    return out


def audio_ab() -> list[dict]:
    out = []
    for rel, label in [("remaster_v2/narration_fix/ab_compare.mp3", "讀音 A/B：v1 → v2（20 句）"),
                       ("remaster_v2/narration_fix_v2_1/ab_compare_v2_1.mp3", "讀音 A/B：v1 → v2.1"),
                       ("remaster_v2/bgm/bgm_preview_60s.mp3", "配樂開場 60 秒（單獨）")]:
        if (OUT / rel).exists():
            out.append({"label": label, "path": rel})
    return out


def _narr_starts() -> dict[str, float]:
    """旁白段首行 key → 成片起點秒（與 render.line_times 同一條時間軸）。"""
    try:
        import render
        narration = render.load_narration()
        planned = render.plan([1, 2, 3], None, narration)
        return {render.narr_key(p.shot.chapter, p.shot.index, li): t
                for p, li, _, t, _ in render.line_times(planned)}
    except Exception as e:  # noqa: BLE001 — 審片頁不能因為時間軸算不出來就整頁掛掉
        print(f"[warn] 旁白時間軸算不出來：{e}", file=sys.stderr)
        return {}


def markers() -> list[dict]:
    rows = []
    starts = _narr_starts()
    nf = DOCS / "narration_fix.json"
    if nf.exists():
        for s in json.loads(nf.read_text(encoding="utf-8")).get("sentences", []):
            t0 = starts.get(s["key"])
            if t0 is None:
                continue
            span = s.get("v2_post_span") or [0.0, 0.0]
            rows.append({"t": round(t0 + span[0], 2), "kind": "讀音", "id": s.get("issues", ""),
                         "text": s.get("subtitle", "")[:40]})
    hz = DOCS / "hanzi.json"
    if hz.exists():
        for it in json.loads(hz.read_text(encoding="utf-8")).get("items", []):
            if it.get("fix") not in ("a", "b"):
                continue
            if it["id"] in KNOWN:
                rows.append({"t": it["final_sec"][0], "kind": "限制", "id": it["id"], "text": KNOWN[it["id"]]})
                continue
            rows.append({"t": it["final_sec"][0], "kind": "換字", "id": it["id"],
                         "text": f"{it.get('object_type', '')}：{it.get('suggested_text') or '抹除／失焦'}"})
    return sorted(rows, key=lambda r: r["t"])


def safe_file(rel: str) -> Path | None:
    rel = unquote(rel).lstrip("/")
    if not rel or ".." in Path(rel).parts:
        return None
    p = (OUT / rel).resolve()
    try:
        p.relative_to(OUT.resolve())
    except ValueError:
        return None
    return p if p.is_file() and p.suffix.lower() in MIME else None


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """'bytes=a-b' → (a, b)，含尾；不合法回 None（改送整檔）。"""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not m or (m[1] == "" and m[2] == ""):
        return None
    if m[1] == "":
        start, end = max(0, size - int(m[2])), size - 1
    else:
        start = int(m[1])
        end = min(int(m[2]), size - 1) if m[2] else size - 1
    return (start, end) if start <= end < size else None


def page() -> str:
    data = {"versions": versions(), "audio": audio_ab(), "markers": markers()}
    # JSON 放進 <script type=application/json>：只要擋掉 "</"（JSON 允許 \/），不能做 HTML 跳脫
    blob = json.dumps(data, ensure_ascii=False).replace("</", r"<\/")
    return PAGE.replace("__DATA__", blob)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # 安靜
        pass

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        f = safe_file(path.removeprefix("/files/")) if path.startswith("/files/") else None
        if f is None:
            self.send_error(404)
            return
        size = f.stat().st_size
        rng = parse_range(self.headers.get("Range"), size)
        start, end = rng or (0, size - 1)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", MIME[f.suffix.lower()])
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with f.open("rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    buf = fh.read(min(CHUNK, left))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    left -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass  # 瀏覽器拖曳進度條時常中斷舊請求


PAGE = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>暗渠之書 審片</title>
<style>
:root{--bg:#0e0c0a;--panel:#17140f;--line:#2e281e;--gold:#d4af37;--champ:#e8d9b0;--muted:#9a8f7a;--bad:#d9674a;--ok:#7fb069}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--champ);font:14px/1.5 Inter,"Microsoft JhengHei",sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:18px;margin:0;color:var(--gold)}select,button{background:var(--panel);color:var(--champ);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
button:hover{border-color:var(--gold);cursor:pointer}
main{display:grid;grid-template-columns:minmax(0,2fr) minmax(320px,1fr);gap:12px;padding:12px 16px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px}
video{width:100%;background:#000;border-radius:6px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pair.single{grid-template-columns:1fr}.lbl{color:var(--muted);font-size:12px;margin:4px 0}
table{width:100%;border-collapse:collapse;font-size:13px}td{border-bottom:1px solid var(--line);padding:4px}
td.t{font-family:"JetBrains Mono",monospace;color:var(--gold);white-space:nowrap;cursor:pointer}
.k-限制{color:var(--bad)}.k-讀音{color:#8fb3d9}.k-換字{color:var(--ok)}
.list{max-height:70vh;overflow:auto}input.note{width:100%;background:#0b0a08;color:var(--champ);border:1px solid var(--line);border-radius:4px;padding:2px 4px}
.filters label{margin-right:8px}audio{width:100%}
</style></head><body>
<header><h1>暗渠之書・審片</h1>
<label>右側版本 <select id="ver"></select></label>
<label><input type="checkbox" id="cmp" checked> 左側同步播 v1 對照</label>
<button id="export">複製審查筆記</button><span id="msg" class="lbl"></span></header>
<main><section class="card"><div id="pair" class="pair">
<div id="leftbox"><div class="lbl">v1 原版</div><video id="left" controls preload="metadata" muted></video></div>
<div><div class="lbl" id="rlabel"></div><video id="right" controls preload="metadata"></video></div></div>
<div class="card" style="margin-top:10px"><div class="lbl">試聽</div><div id="audio"></div></div></section>
<section class="card"><div class="filters lbl">
<label><input type="checkbox" data-k="限制" checked>限制</label><label><input type="checkbox" data-k="讀音" checked>讀音</label>
<label><input type="checkbox" data-k="換字" checked>換字</label>（點時間碼跳轉；右欄可寫筆記，存在本機瀏覽器）</div>
<div class="list"><table id="marks"></table></div></section></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);const $=id=>document.getElementById(id);
const L=$('left'),R=$('right');const fmt=t=>{const m=Math.floor(t/60),s=(t%60).toFixed(1).padStart(4,'0');return m+':'+s};
const store={get(k){try{return localStorage.getItem(k)||''}catch(e){return ''}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
const v1=D.versions.find(v=>v.path.startsWith('v1_'));if(v1)L.src='files/'+v1.path;
D.versions.slice().reverse().forEach(v=>{const o=document.createElement('option');o.value=v.path;o.textContent=v.label;$('ver').appendChild(o)});
function pick(){R.src='files/'+$('ver').value;$('rlabel').textContent=$('ver').selectedOptions[0].textContent}
$('ver').onchange=pick;pick();
function cmp(){const on=$('cmp').checked;$('leftbox').style.display=on?'':'none';$('pair').className=on?'pair':'pair single';if(!on)L.pause()}
$('cmp').onchange=cmp;cmp();
R.addEventListener('play',()=>{if($('cmp').checked){L.currentTime=R.currentTime;L.play()}});
R.addEventListener('pause',()=>L.pause());R.addEventListener('seeked',()=>{if($('cmp').checked)L.currentTime=R.currentTime});
D.audio.forEach(a=>{const d=document.createElement('div');d.innerHTML='<div class="lbl"></div><audio controls preload="none"></audio>';
d.querySelector('.lbl').textContent=a.label;d.querySelector('audio').src='files/'+a.path;$('audio').appendChild(d)});
function seek(t){R.currentTime=Math.max(0,t-1);if($('cmp').checked)L.currentTime=R.currentTime;R.play()}
function render(){const on=[...document.querySelectorAll('.filters input')].filter(c=>c.checked).map(c=>c.dataset.k);const tb=$('marks');tb.innerHTML='';
D.markers.filter(m=>on.includes(m.kind)).forEach(m=>{const tr=document.createElement('tr');const key='note:'+m.kind+':'+m.id+':'+m.t;
tr.innerHTML='<td class="t"></td><td></td><td></td><td style="width:34%"><input class="note" placeholder="OK／問題…"></td>';
tr.children[0].textContent=fmt(m.t);tr.children[0].onclick=()=>seek(m.t);tr.children[1].textContent=m.kind+' '+m.id;tr.children[1].className='k-'+m.kind;
tr.children[2].textContent=m.text;const inp=tr.querySelector('input');inp.value=store.get(key);inp.oninput=()=>store.set(key,inp.value);tb.appendChild(tr)})}
document.querySelectorAll('.filters input').forEach(c=>c.onchange=render);render();
$('export').onclick=async()=>{const lines=D.markers.map(m=>[m,store.get('note:'+m.kind+':'+m.id+':'+m.t)]).filter(x=>x[1]).map(([m,n])=>fmt(m.t)+' '+m.kind+' '+m.id+'：'+n);
const txt='審片筆記（'+$('ver').selectedOptions[0].textContent+'）\n'+(lines.join('\n')||'（沒有筆記）');
try{await navigator.clipboard.writeText(txt);$('msg').textContent='已複製 '+lines.length+' 則'}catch(e){prompt('複製以下內容',txt)}};
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9201)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"審片頁 → http://{a.host}:{a.port}/（Ctrl+C 停止）", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
