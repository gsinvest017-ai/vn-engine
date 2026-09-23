import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import review_server as rs  # noqa: E402


def test_parse_range():
    assert rs.parse_range("bytes=0-99", 1000) == (0, 99)
    assert rs.parse_range("bytes=900-", 1000) == (900, 999)
    assert rs.parse_range("bytes=-100", 1000) == (900, 999)
    assert rs.parse_range("bytes=0-5000", 1000) == (0, 999)
    assert rs.parse_range("bytes=1000-", 1000) is None
    assert rs.parse_range("bytes=-", 1000) is None
    assert rs.parse_range(None, 1000) is None
    assert rs.parse_range("items=0-1", 1000) is None


def test_safe_file_blocks_traversal_and_types(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "OUT", tmp_path)
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "secret.txt").write_text("no")
    assert rs.safe_file("a.mp4") == (tmp_path / "a.mp4").resolve()
    assert rs.safe_file("secret.txt") is None
    assert rs.safe_file("../a.mp4") is None
    assert rs.safe_file("%2e%2e/a.mp4") is None
    assert rs.safe_file("") is None


def test_page_escapes_data(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "OUT", tmp_path)
    monkeypatch.setattr(rs, "DOCS", tmp_path)
    import json
    (tmp_path / "hanzi.json").write_text(json.dumps({"items": [
        {"id": "X", "fix": "a", "final_sec": [1.0, 2.0], "object_type": "匾", "suggested_text": "</script><b>"},
        {"id": "Y", "fix": "a", "final_sec": [3.0, 4.0]}]}), encoding="utf-8")
    monkeypatch.setattr(rs, "KNOWN", {"Y": "限制說明"})
    monkeypatch.setattr(rs, "_narr_starts", lambda: {})
    kinds = {m["id"]: m["kind"] for m in rs.markers()}
    assert kinds == {"X": "換字", "Y": "限制"}
    html = rs.page()
    assert "</script><b>" not in html
    assert html.count("</script>") == 2
