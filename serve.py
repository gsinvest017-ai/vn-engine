#!/usr/bin/env python3
"""
serve.py — 啟動本地 HTTP Server 來運行 VN Engine。
同時提供 /api/* REST 路由供 Dev Dashboard 使用。

用法：
  python serve.py            # 預設 port 8080
  python serve.py 3000       # 指定 port
"""
import http.server
import socketserver
import sys
import os
import re
import json
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path

import argparse

_parser = argparse.ArgumentParser(description='VN Engine dev server')
_parser.add_argument('port', nargs='?', type=int, default=8080)
_parser.add_argument('--no-browser', action='store_true',
                     help='Do not open browser on start (useful for remote/SSH sessions)')
_args = _parser.parse_args()

PORT = _args.port
ROOT = Path(__file__).parent

os.chdir(ROOT)


def _tailscale_ip() -> str:
    """Return Tailscale IPv4 address, or empty string if not available."""
    try:
        out = subprocess.check_output(
            ['tailscale', 'ip', '-4'],
            stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
        return out if out else ''
    except Exception:
        return ''


class Handler(http.server.SimpleHTTPRequestHandler):

    # ── Request routing ─────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    MAX_POST = 4 * 1024 * 1024  # 4MB（劇本為純文字，足夠）

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        if length > self.MAX_POST:
            self._respond({'error': f'Body too large (>{self.MAX_POST} bytes)'}, 413)
            return
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
        except json.JSONDecodeError as e:
            self._respond({'error': f'Invalid JSON: {e}'}, 400)
            return
        try:
            if   parsed.path == '/api/run-tool':        self._dispatch_run_tool(body)
            elif parsed.path == '/api/scripts/save':    self._api_script_save(body)
            elif parsed.path == '/api/scripts/upload':  self._api_script_upload(body)
            else:                                       self._respond({'error': 'not found'}, 404)
        except PermissionError as e:
            self._respond({'error': str(e)}, 403)
        except Exception as e:
            self._respond({'error': str(e)}, 500)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self._dispatch_api(parsed)
        else:
            super().do_GET()

    def log_message(self, fmt, *args):
        if args and str(args[1]) not in ('200', '304'):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def guess_type(self, path):
        t = super().guess_type(path)
        if str(path).endswith('.vns'):
            return 'text/plain; charset=utf-8'
        if str(path).endswith('.yaml'):
            return 'text/yaml; charset=utf-8'
        return t

    # ── API dispatcher ───────────────────────────────────────────────

    def _dispatch_api(self, parsed):
        p  = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if   p == '/api/scripts':           data = self._api_scripts()
            elif p == '/api/scripts/content':   data = self._api_script_content(qs.get('f', [''])[0])
            elif p == '/api/manifest':          data = self._api_manifest()
            elif p == '/api/assets/check':      data = self._api_assets_check()
            elif p == '/api/git/log':           data = self._api_git_log()
            elif p == '/api/validate':          data = self._api_validate()
            elif p == '/api/status':            data = {'ok': True, 'port': PORT}
            else:                               self._respond({'error': 'not found'}, 404); return
            self._respond(data)
        except PermissionError as e:
            self._respond({'error': str(e)}, 403)
        except FileNotFoundError as e:
            self._respond({'error': str(e)}, 404)
        except Exception as e:
            self._respond({'error': str(e)}, 500)

    # ── Tool runner ──────────────────────────────────────────────────
    TOOL_WHITELIST = {
        'gen_map':          'tools/gen_map_realistic.py',
        'rembg_narrator':   'tools/rembg_narrator.py',
        'rembg_diao_caidi': 'tools/rembg_diao_caidi.py',
    }

    def _dispatch_run_tool(self, body):
        tool = body.get('tool', '')
        if tool not in self.TOOL_WHITELIST:
            self._respond({'error': f'Unknown tool: {tool}'}, 400)
            return
        script = ROOT / self.TOOL_WHITELIST[tool]
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(ROOT),
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=120,
            )
            self._respond({
                'ok':     result.returncode == 0,
                'tool':   tool,
                'stdout': result.stdout[-3000:] if result.stdout else '',
                'stderr': result.stderr[-1000:] if result.stderr else '',
            })
        except subprocess.TimeoutExpired:
            self._respond({'error': 'Timeout after 120s', 'tool': tool}, 504)
        except Exception as e:
            self._respond({'error': str(e), 'tool': tool}, 500)

    # ── Script write APIs（Dashboard 編輯/匯入劇本） ──────────────────

    SCRIPT_EXTS = ('.vns', '.yaml')

    @staticmethod
    def _sanitize_name(name):
        """檔名/目錄名只留安全字元，去除路徑成分。"""
        base = os.path.basename(str(name).replace('\\', '/'))
        clean = re.sub(r'[^\w\-.]', '_', base)
        if not clean or clean.startswith('.'):
            raise PermissionError(f'Invalid name: {name!r}')
        return clean

    def _resolve_script_path(self, rel):
        """限制目標必須位於 ROOT/scripts/ 之下。"""
        target = (ROOT / rel).resolve()
        scripts_root = (ROOT / 'scripts').resolve()
        if not str(target).startswith(str(scripts_root) + os.sep):
            raise PermissionError('Path outside scripts/ directory')
        return target

    def _api_script_save(self, body):
        """POST /api/scripts/save  {path, content} — 編輯儲存（.bak 備份）。"""
        rel     = body.get('path', '')
        content = body.get('content')
        if not rel or content is None:
            self._respond({'error': 'Missing path or content'}, 400)
            return
        target = self._resolve_script_path(rel)
        if target.suffix not in self.SCRIPT_EXTS:
            raise PermissionError(f'File type not allowed: {target.suffix}')
        if not target.exists():
            self._respond({'error': f'File not found: {rel}（新檔請用 upload）'}, 404)
            return
        # 單一輪替 .bak 備份（git 之外的即時安全網）
        backup = target.with_suffix(target.suffix + '.bak')
        backup.write_text(target.read_text('utf-8'), 'utf-8')
        target.write_text(content, 'utf-8')
        self._respond({'ok': True, 'path': rel, 'bytes': len(content.encode('utf-8')),
                       'backup': str(backup.relative_to(ROOT)).replace('\\', '/')})

    def _api_script_upload(self, body):
        """POST /api/scripts/upload  {story, files:[{name, content}]} — 匯入劇本。

        story 為 scripts/ 下的目錄名（不存在則建立）。
        檔名 sanitize、僅允許 .vns/.yaml、單檔 ≤ 2MB。
        """
        story = self._sanitize_name(body.get('story', ''))
        files = body.get('files', [])
        if not files:
            self._respond({'error': 'No files'}, 400)
            return
        story_dir = self._resolve_script_path(f'scripts/{story}/_probe').parent
        story_dir.mkdir(parents=True, exist_ok=True)

        saved, skipped = [], []
        for f in files:
            try:
                name    = self._sanitize_name(f.get('name', ''))
                content = f.get('content', '')
                ext     = os.path.splitext(name)[1].lower()
                if ext == '.txt':  # 純文字稿視為 .vns 劇本
                    name = name[:-4] + '.vns'
                    ext  = '.vns'
                if ext not in self.SCRIPT_EXTS:
                    skipped.append({'name': name, 'reason': f'不支援的副檔名 {ext}'})
                    continue
                if len(content.encode('utf-8')) > 2 * 1024 * 1024:
                    skipped.append({'name': name, 'reason': '超過 2MB'})
                    continue
                target = story_dir / name
                existed = target.exists()
                if existed:  # 覆蓋前備份
                    target.with_suffix(target.suffix + '.bak').write_text(
                        target.read_text('utf-8'), 'utf-8')
                target.write_text(content, 'utf-8')
                saved.append({'name': name, 'overwritten': existed,
                              'path': str(target.relative_to(ROOT)).replace('\\', '/')})
            except Exception as e:
                skipped.append({'name': str(f.get('name', '?')), 'reason': str(e)})
        self._respond({'ok': bool(saved), 'story': story,
                       'saved': saved, 'skipped': skipped})

    def _respond(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    # ── API handlers ─────────────────────────────────────────────────

    def _api_scripts(self):
        result = []
        # 只掃 ROOT/scripts/（rglob 'scripts/**' 會把 dist/scripts/ 打包產物也掃進來）
        for vns in sorted((ROOT / 'scripts').rglob('*.vns')):
            try:
                text  = vns.read_text('utf-8')
                lines = text.splitlines()
                cmds  = {'dialogue': 0, 'narration': 0, 'scene': 0,
                         'char': 0, 'bgm': 0, 'sfx': 0, 'choice': 0,
                         'effect': 0, 'wait': 0, 'fade': 0}
                scenes = []
                for ln in lines:
                    s = ln.strip()
                    if not s or s.startswith('#'):
                        continue
                    if s.startswith('@scene'):
                        cmds['scene'] += 1
                        m = re.search(r'\bbg=(\S+)', s)
                        if m:
                            scenes.append(m.group(1))
                    elif s.startswith('@char'):   cmds['char']   += 1
                    elif s.startswith('@bgm'):    cmds['bgm']    += 1
                    elif s.startswith('@sfx'):    cmds['sfx']    += 1
                    elif s.startswith('@choice'): cmds['choice'] += 1
                    elif s.startswith('@effect'): cmds['effect'] += 1
                    elif s.startswith('@wait'):   cmds['wait']   += 1
                    elif s.startswith('@fade'):   cmds['fade']   += 1
                    elif re.match(r'^\[.+\]', s): cmds['dialogue'] += 1
                    elif not s.startswith('@'):   cmds['narration'] += 1
                # rough play time estimate: narration ~12 s/line, dialogue ~8 s/line
                est_sec = cmds['narration'] * 12 + cmds['dialogue'] * 8
                result.append({
                    'path':    str(vns.relative_to(ROOT)).replace('\\', '/'),
                    'name':    vns.stem,
                    'lines':   len(lines),
                    'cmds':    cmds,
                    'scenes':  scenes,
                    'est_min': max(1, round(est_sec / 60)),
                })
            except Exception as e:
                result.append({'path': str(vns.name), 'name': vns.stem, 'error': str(e)})
        return result

    def _api_script_content(self, filepath):
        if not filepath:
            raise ValueError('Missing f parameter')
        target = (ROOT / filepath).resolve()
        root_r = ROOT.resolve()
        if not str(target).startswith(str(root_r)):
            raise PermissionError('Path outside project root')
        if not target.exists():
            raise FileNotFoundError(filepath)
        if target.suffix not in ('.vns', '.yaml', '.md', '.json'):
            raise PermissionError('File type not allowed')
        return {'content': target.read_text('utf-8'), 'path': filepath}

    def _api_manifest(self):
        p = ROOT / 'assets' / 'manifest.json'
        if p.exists():
            return json.loads(p.read_text('utf-8'))
        return {}

    def _api_assets_check(self):
        result = {}
        assets_dir = ROOT / 'assets'
        if assets_dir.exists():
            for f in assets_dir.rglob('*'):
                if f.is_file():
                    rel = str(f.relative_to(assets_dir)).replace('\\', '/')
                    result[rel] = True
        return result

    def _api_git_log(self):
        try:
            out = subprocess.check_output(
                ['git', 'log', '--pretty=format:%h\x1f%s\x1f%cr', '--max-count=20'],
                cwd=str(ROOT), stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            )
            result = []
            for line in out.strip().splitlines():
                parts = line.split('\x1f', 2)
                if len(parts) == 3:
                    result.append({'hash': parts[0], 'msg': parts[1], 'date': parts[2]})
            return result
        except Exception:
            return []

    def _api_validate(self):
        issues = []
        assets = ROOT / 'assets'

        def bg_exists(bid):
            return any(
                (assets / 'backgrounds' / f'{bid}{ext}').exists()
                for ext in ('.svg', '.png', '.jpg', '.webp')
            )

        def char_exists(cid):
            return (assets / 'characters' / cid).is_dir()

        def expr_exists(cid, expr):
            return any(
                (assets / 'characters' / cid / f'{expr}{ext}').exists()
                for ext in ('.svg', '.png')
            )

        def bgm_exists(bid):
            return (assets / 'audio' / 'bgm' / f'{bid}.ogg').exists()

        for vns in sorted((ROOT / 'scripts').rglob('*.vns')):
            try:
                rel = str(vns.relative_to(ROOT)).replace('\\', '/')
                for i, raw in enumerate(vns.read_text('utf-8').splitlines(), 1):
                    line = raw.strip()
                    if not line or line.startswith('#'):
                        continue

                    if line.startswith('@scene'):
                        for m in re.finditer(r'\bbg=(\S+)', line):
                            if not bg_exists(m.group(1)):
                                issues.append({
                                    'file': rel, 'line': i, 'type': 'error',
                                    'msg': f'背景 "{m.group(1)}" 不存在',
                                })

                    elif line.startswith('@char') and 'show=' in line:
                        cm = re.search(r'\bshow=(\S+)', line)
                        em = re.search(r'\bexpr=(\S+)', line)
                        if cm:
                            cid = cm.group(1)
                            if not char_exists(cid):
                                issues.append({
                                    'file': rel, 'line': i, 'type': 'error',
                                    'msg': f'角色目錄 "{cid}" 不存在',
                                })
                            elif em and not expr_exists(cid, em.group(1)):
                                issues.append({
                                    'file': rel, 'line': i, 'type': 'warning',
                                    'msg': f'角色 "{cid}" 表情 "{em.group(1)}" 無對應檔案',
                                })

                    elif '@bgm' in line and 'play=' in line:
                        mm = re.search(r'\bplay=(\S+)', line)
                        if mm and not bgm_exists(mm.group(1)):
                            issues.append({
                                'file': rel, 'line': i, 'type': 'info',
                                'msg': f'BGM "{mm.group(1)}" 無 .ogg（程序式 fallback）',
                            })

            except Exception as e:
                issues.append({'file': vns.name, 'line': 0, 'type': 'error', 'msg': str(e)})

        return issues


url      = f'http://localhost:{PORT}/engine/'
dash_url = f'http://localhost:{PORT}/dashboard/'
print(f'VN Engine:       {url}')
print(f'Dev Dashboard:   {dash_url}')

ts_ip = _tailscale_ip()
if ts_ip:
    print(f'\nTailscale access:')
    print(f'  VN Engine:     http://{ts_ip}:{PORT}/engine/')
    print(f'  Dev Dashboard: http://{ts_ip}:{PORT}/dashboard/')

print(f'\nPress Ctrl+C to stop.\n')

try:
    with socketserver.TCPServer(('', PORT), Handler) as httpd:
        if not _args.no_browser:
            webbrowser.open(dash_url)
        httpd.serve_forever()
except KeyboardInterrupt:
    print('\nServer stopped.')
