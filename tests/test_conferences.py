import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build  # noqa: E402
import conf_check  # noqa: E402
from common import SRC, read_json  # noqa: E402


def test_curated_file_is_valid():
    known = {c["id"] for c in read_json(SRC / "companies.json", {})["companies"]}
    w: list[str] = []
    out = build.conferences(known, "2026-11-13", w)
    assert w == []
    assert out["items"] and out["items"] == sorted(out["items"], key=lambda x: x["start"])


def test_past_events_and_deadlines_drop(monkeypatch, tmp_path):
    data = {"items": [
        {"id": "a", "name": "A", "kind": "expo", "start": "2026-01-01", "end": "2026-01-02", "url": "https://a", "why": "x"},
        {"id": "b", "name": "B", "kind": "academic", "start": "2027-07-01", "end": "2027-07-02", "url": "https://b", "why": "x",
         "deadlines": [{"label": "old", "date": "2026-10-01"}, {"label": "new", "date": "2026-12-01"}]},
        {"id": "c", "name": "C", "kind": "party", "start": "2027-01-01", "end": "2027-01-01", "url": "https://c", "why": "x"},
    ]}
    real = build.read_json
    monkeypatch.setattr(build, "read_json", lambda p, d: data if p.name == "conferences.json" else real(p, d))
    w: list[str] = []
    out = build.conferences(set(), "2026-11-13", w)
    assert [i["id"] for i in out["items"]] == ["b"]
    assert [d["label"] for d in out["items"][0]["deadlines"]] == ["new"]
    assert len(w) == 1  # 잘못된 종류 'party'


def test_check_due():
    assert conf_check.due({}, date(2026, 11, 13))
    assert not conf_check.due({"checked": "2026-11-10"}, date(2026, 11, 13))
    assert conf_check.due({"checked": "2026-11-07"}, date(2026, 11, 13))
