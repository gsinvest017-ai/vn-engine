#!/usr/bin/env python3
"""
gen_manifest.py — 掃描 scripts/ 中所有 .vns 腳本，
提取用到的素材 ID，更新 assets/manifest.json 中的 status。
執行: python tools/gen_manifest.py
"""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = ROOT / "scripts"
ASSETS_DIR  = ROOT / "assets"
MANIFEST    = ASSETS_DIR / "manifest.json"


def scan_scripts():
    used = {
        "backgrounds": set(),
        "characters":  {},   # id -> {expressions}
        "bgm":         set(),
        "sfx":         set(),
    }

    vns_files = list(SCRIPTS_DIR.rglob("*.vns"))
    if not vns_files:
        print("No .vns files found.")
        return used

    for path in vns_files:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue

            # @scene bg=X
            m = re.search(r"@scene\s+.*?bg=(\w+)", line)
            if m:
                used["backgrounds"].add(m.group(1))

            # @bgm play=X
            m = re.search(r"@bgm\s+play=(\w+)", line)
            if m:
                used["bgm"].add(m.group(1))

            # @sfx play=X or @sfx stop=X
            m = re.search(r"@sfx\s+(?:play|stop)=(\w+)", line)
            if m:
                used["sfx"].add(m.group(1))

            # @char show=X expr=Y
            m = re.search(r"@char\s+show=(\w+).*?(?:expr=(\w+))?", line)
            if m:
                cid  = m.group(1)
                expr = m.group(2) or "normal"
                used["characters"].setdefault(cid, set()).add(expr)

            # @char expr=X:Y
            m = re.search(r"@char\s+expr=(\w+):(\w+)", line)
            if m:
                used["characters"].setdefault(m.group(1), set()).add(m.group(2))

    return used


def check_file_exists(rel_path: str) -> bool:
    return (ASSETS_DIR / rel_path).exists()


def build_report(used):
    lines = ["# Asset Status Report", ""]

    lines.append("## Backgrounds")
    for bg_id in sorted(used["backgrounds"]):
        for ext in (".svg", ".png", ".jpg"):
            path = f"backgrounds/{bg_id}{ext}"
            if check_file_exists(path):
                lines.append(f"  [OK]     {bg_id}  ({path})")
                break
        else:
            lines.append(f"  [MISSING] {bg_id}")

    lines.append("")
    lines.append("## Characters")
    for char_id, exprs in sorted(used["characters"].items()):
        lines.append(f"  {char_id}:")
        for expr in sorted(exprs):
            for ext in (".svg", ".png", ".jpg"):
                path = f"characters/{char_id}/{expr}{ext}"
                if check_file_exists(path):
                    lines.append(f"    [OK]      {expr}  ({path})")
                    break
            else:
                lines.append(f"    [MISSING] {expr}")

    lines.append("")
    lines.append("## BGM")
    for bgm_id in sorted(used["bgm"]):
        path = f"audio/bgm/{bgm_id}.ogg"
        status = "[OK]    " if check_file_exists(path) else "[MISSING]"
        lines.append(f"  {status} {bgm_id}")

    lines.append("")
    lines.append("## SFX")
    for sfx_id in sorted(used["sfx"]):
        path = f"audio/sfx/{sfx_id}.ogg"
        status = "[OK]    " if check_file_exists(path) else "[MISSING]"
        lines.append(f"  {status} {sfx_id}")

    return "\n".join(lines)


def main():
    print("Scanning .vns scripts...")
    used = scan_scripts()

    report = build_report(used)
    print(report)

    report_path = ROOT / "docs" / "asset-status.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to {report_path}")

    # Update manifest status
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        # backgrounds
        for bg_id, info in manifest.get("backgrounds", {}).items():
            for ext in (".svg", ".png", ".jpg"):
                if check_file_exists(f"backgrounds/{bg_id}{ext}"):
                    info["status"] = "ready"
                    break
        # characters
        for char_id, char_data in manifest.get("characters", {}).items():
            for expr, info in char_data.get("expressions", {}).items():
                for ext in (".svg", ".png", ".jpg"):
                    if check_file_exists(f"characters/{char_id}/{expr}{ext}"):
                        info["status"] = "ready"
                        break
        # audio
        for kind in ("bgm", "sfx"):
            for aid, info in manifest.get("audio", {}).get(kind, {}).items():
                if check_file_exists(f"audio/{kind}/{aid}.ogg"):
                    info["status"] = "ready"

        MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print("Manifest updated.")


if __name__ == "__main__":
    main()
