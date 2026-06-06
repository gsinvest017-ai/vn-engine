#!/usr/bin/env python3
"""
serve.py — 啟動本地 HTTP Server 來運行 VN Engine。
需要先執行此腳本，再用瀏覽器開啟連結。

用法：
  python serve.py            # 預設 port 8080
  python serve.py 3000       # 指定 port
"""
import http.server
import socketserver
import sys
import os
import webbrowser
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
ROOT = Path(__file__).parent

os.chdir(ROOT)

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress .svg / .vns noise, keep errors
        if args and str(args[1]) not in ("200", "304"):
            super().log_message(fmt, *args)

    def end_headers(self):
        # Allow cross-origin for module scripts
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def guess_type(self, path):
        t = super().guess_type(path)
        if str(path).endswith(".vns"):
            return "text/plain; charset=utf-8"
        if str(path).endswith(".yaml"):
            return "text/yaml; charset=utf-8"
        return t


url = f"http://localhost:{PORT}/engine/"
print(f"VN Engine server running at:  {url}")
print(f"Press Ctrl+C to stop.\n")

try:
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        webbrowser.open(url)
        httpd.serve_forever()
except KeyboardInterrupt:
    print("\nServer stopped.")
