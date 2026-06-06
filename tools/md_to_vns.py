#!/usr/bin/env python3
"""
md_to_vns.py — 把純文字/Markdown 小說轉換為 .vns 腳本草稿。
這不是全自動工具，而是輔助作者節省初始格式化時間。

用法:
  python tools/md_to_vns.py 台中暗渠.md --output scripts/taichung-anqu/draft.vns
  python tools/md_to_vns.py 台中暗渠.md  # 印到 stdout

規則:
  - 第一行 → @chapter 標題
  - 空行分隔段落
  - 引號內文字 → 推測為對話 [unknown_speaker]
  - > 開頭 → quote narration
  - 其餘 → 普通旁白
  - 章節標題（第X章）→ @chapter + @fade
"""
import re
import sys
from pathlib import Path


def guess_speaker(text: str) -> str | None:
    """超簡單推測：如果有 '名字說/問/答' 模式就抓名字。"""
    m = re.search(r"(.{2,6})(?:說|問|答|道|喊|低聲|忽然問)[：:「]", text)
    if m:
        return m.group(1).strip()
    return None


def convert(md_text: str, story_title: str = "未命名故事") -> str:
    lines = md_text.splitlines()
    out = []
    chapter_count = 0
    i = 0

    # Story header
    out.append(f"# {story_title} — VNScript 草稿（由 md_to_vns.py 生成）")
    out.append("# 注意：此為草稿，請手動補充 @char/@scene/@effect/@sfx 等指令")
    out.append("")

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1

        if not line:
            # blank line → brief pause
            if out and out[-1] != "":
                out.append("")
            continue

        # Chapter heading
        chapter_m = re.match(r"(第[一二三四五六七八九十百\d]+章)\s*(.*)", line)
        if chapter_m:
            chapter_count += 1
            num   = chapter_m.group(1)
            title = chapter_m.group(2).strip()
            if chapter_count > 1:
                out.append("@chapter_end")
                out.append("")
            out.append(f"@chapter {num}　{title}")
            out.append(f"@scene bg=FILL_IN_SCENE transition=fade")
            out.append(f"@bgm play=FILL_IN_BGM fade=1500")
            out.append("")
            continue

        # Pure quote (already prefixed with >)
        if line.startswith(">"):
            out.append(line)
            continue

        # Book title (first line)
        if chapter_count == 0:
            out.append(f"# 書名: {line}")
            continue

        # Dialogue detection: text contains quotes 「」or 『』
        quote_m = re.search(r"[「『](.*?)[」』]", line)
        if quote_m:
            speaker = guess_speaker(line)
            dialogue_text = quote_m.group(1)
            if speaker:
                # Emit narration before quote (if any text before quote)
                before = line[:line.index("「" if "「" in line else "『")].strip()
                if before:
                    # Remove trailing dialogue verbs
                    before = re.sub(r"(.{2,6})(?:說|問|答|道|喊)[：:]\s*$", "", before).strip()
                    if before:
                        out.append(before)
                char_id = _name_to_id(speaker)
                out.append(f"[{char_id}] {dialogue_text}")
            else:
                out.append(f"[unknown] {dialogue_text}")
            # Text after closing quote (if any)
            after_q = "」" if "」" in line else "』"
            after_idx = line.rfind(after_q)
            after = line[after_idx + 1:].strip()
            if after:
                out.append(after)
            continue

        # Emphasized text (wrapped in ——/—)
        if line.startswith("—") or re.match(r"^[「『《〈]", line):
            out.append(f"> {line}")
            continue

        # Normal narration
        out.append(line)

    # End
    out.append("")
    out.append("@chapter_end")
    out.append("")
    out.append("@end")

    return "\n".join(out)


def _name_to_id(name: str) -> str:
    """Convert Chinese name to ASCII-safe id."""
    mapping = {
        "刁才弟": "diao_caidi",
        "徐尋尋": "xu_xunxun",
        "廖啟祥": "liao_qixiang",
    }
    return mapping.get(name, name.lower().replace(" ", "_") or "unknown")


def main():
    if len(sys.argv) < 2:
        print("Usage: python md_to_vns.py <input.md> [--output <out.vns>]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = None

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = Path(sys.argv[idx + 1])

    # Try common encodings
    text = None
    for enc in ("utf-8", "big5", "gb18030", "utf-8-sig"):
        try:
            text = input_path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        print(f"Error: cannot decode {input_path}")
        sys.exit(1)

    title = input_path.stem
    vns = convert(text, title)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(vns, encoding="utf-8")
        print(f"Written to {output_path}")
    else:
        print(vns)


if __name__ == "__main__":
    main()
