import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import changes  # noqa: E402
import patent_calc  # noqa: E402

CFG = {"publish_records": True, "layers": [{"id": "sw", "label": "하모닉", "note": "", "cpc": "cpc=F16H49", "parts": ["reducer"]}, {"id": "screw", "label": "스크류", "note": "", "cpc": "cpc=F16H25/22", "parts": ["screw"]}],
       "ref": [{"name": "x"}], "ref_note": "n",
       "applicants": [
           {"id": "ubtech", "name": "UBTech", "company": "ubtech", "kind": "company", "home": "CN"},
           {"id": "figure", "name": "Figure", "company": "figure", "kind": "company", "home": "US"},
           {"id": "harmonic", "name": "Harmonic", "company": None, "kind": "incumbent", "home": "JP"},
           {"id": "sbb", "name": "SBB", "company": None, "kind": "kr_part", "home": "KR"}]}


def cell(a, b):
    return {"a": a, "b": b, "fetched": "2026-10-30"}


DATA = {"generated_at": "t", "windows": {}, "status": {"cells": 6, "expected": 9, "pending": 3},
        "applicants": {"ubtech": {"quality": {"total": 100, "sample": 100, "granted": 0.4, "utility": 0.1, "intl": 0.2},
                                  "recent": [{"country": "CN", "number": "1", "kind": "A", "date": "2026-10-01", "title": "Joint", "applicant": "Ubtech"}]},
                       "figure": {"recent": []}},
        "cells": {"ubtech|total": cell(300, 150), "ubtech|sw": cell(40, 10), "ubtech|screw": cell(5, 4),
                  "figure|total": cell(20, 2), "figure|sw": cell(3, 0),
                  "harmonic|sw": cell(120, 100), "sbb|sw": cell(9, 8), "sbb|screw": {"a": None, "b": None, "error": "x"}}}


def test_not_ready_without_data_keeps_reference():
    b = patent_calc.block(CFG, {}, [])
    assert b["ready"] is False and b["ref"] and patent_calc.state(b) == {}


def test_block_rows_industry_movers_and_parts():
    b = patent_calc.block(CFG, DATA, [])
    assert b["ready"] and [r["id"] for r in b["rows"]] == ["ubtech", "figure"]
    sw = next(x for x in b["industry"] if x["id"] == "sw")
    assert (sw["a"], sw["b"]) == (43, 10) and sw["share_a"] == round(43 / 320, 4)
    assert [(m["company"], m["layer"]) for m in b["movers"]] == [("ubtech", "sw")]      # a>=8 이고 1.3배 이상만
    top = b["parts"]["reducer"]["top"]
    assert [t["id"] for t in top] == ["harmonic", "ubtech", "sbb", "figure"]
    assert [k["id"] for k in b["parts"]["reducer"]["kr"]] == ["sbb"]
    assert "screw" in b["parts"] and b["recent"][0]["company"] == "ubtech"
    assert b["coverage"] == {"cells": 6, "expected": 9, "pending": 3}


def test_patent_change_threshold_and_log():
    assert patent_calc.changed(10, 21) and not patent_calc.changed(100, 110) and not patent_calc.changed(2, 9) and patent_calc.changed(0, 12)
    prev = {"companies": {}, "signposts": {}, "specs": {}, "patents": {"ubtech": {"sw": 40, "screw": 5}}}
    cur = copy.deepcopy(prev)
    cur["patents"]["ubtech"].update(sw=62, screw=6)
    ctx = {"names": {"ubtech": "유비테크"}, "layers": {"sw": "하모닉 감속기"}, "stages": [], "signposts": {}, "models": {}, "spec_labels": {}}
    out = changes.diff(prev, cur, ctx, "2026-11-06")
    assert [c["title"] for c in out] == ["유비테크 특허(하모닉 감속기) 최근 3년 40 → 62건"] and out[0]["roles"] == ["engineer", "strategy"]
    assert changes.diff({"companies": {}, "signposts": {}, "specs": {}}, cur, ctx, "2026-11-06") == []   # 이전 상태에 특허가 없으면 기록 안 함


def test_patent_baseline_moves_only_when_logged_or_new():
    prev = {"patents": {"ubtech": {"sw": 100, "screw": 50}}}
    cur = {"patents": {"ubtech": {"sw": 108, "screw": 80, "hand": 7}, "figure": {"sw": 3}}}
    new = [{"kind": "patent", "company": "ubtech", "layer": "screw"}]
    out = changes.keep_baseline(prev, cur, new)["patents"]
    assert out["ubtech"] == {"sw": 100, "screw": 80, "hand": 7}      # sw 는 작은 증가라 기준 유지, screw 는 기록돼 갱신, hand 는 새 칸
    assert out["figure"] == {"sw": 3}
    assert changes.keep_baseline(None, cur, [])["patents"] == cur["patents"]


def test_block_hides_individual_records_unless_publishing_is_allowed():
    safe = patent_calc.block({**CFG, "publish_records": False}, DATA, [])
    assert safe["ready"] and safe["recent"] == [] and all(r["recent"] == [] for r in safe["rows"])
    assert safe["rows"][0]["quality"]["granted"] == 0.4                     # 집계·비율은 그대로
    assert patent_calc.block(CFG, DATA, [])["recent"]                       # 허용된 경우에만 레코드 포함
