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

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
ROOT = Path(__file__).parent

os.chdir(ROOT)


class Handler(http.server.SimpleHTTPRequestHandler):

    # ── Request routing ─────────────────────────────────────────────

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
        for vns in sorted(ROOT.rglob('scripts/**/*.vns')):
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

        for vns in sorted(ROOT.rglob('scripts/**/*.vns')):
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


url     = f'http://localhost:{PORT}/engine/'
dash_url = f'http://localhost:{PORT}/dashboard/'
print(f'VN Engine:       {url}')
print(f'Dev Dashboard:   {dash_url}')
print(f'Press Ctrl+C to stop.\n')

try:
    with socketserver.TCPServer(('', PORT), Handler) as httpd:
        webbrowser.open(dash_url)
        httpd.serve_forever()
except KeyboardInterrupt:
    print('\nServer stopped.')
