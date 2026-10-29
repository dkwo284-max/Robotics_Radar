import copy
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import changes  # noqa: E402
import paper_calc  # noqa: E402
import papers  # noqa: E402

TODAY = date(2026, 10, 29)


def feed(n):
    return (f"<?xml version='1.0'?><feed xmlns:opensearch='http://a9.com/-/spec/opensearch/1.1/' xmlns='http://www.w3.org/2005/Atom'>"
            f"<opensearch:totalResults xmlns:opensearch='http://a9.com/-/spec/opensearch/1.1/'>{n}</opensearch:totalResults></feed>")


def make(handler):
    return papers.Arxiv(client=httpx.Client(transport=httpx.MockTransport(handler)), pause=0, sleep=lambda s: None)


CFG = {"base": "cat:cs.RO", "ttl_days": 6, "min_sample": 30, "total": {"id": "total", "label": "전체", "q": ""},
       "layers": [{"id": "humanoid", "label": "휴머노이드", "q": "abs:humanoid", "link": "humanoid", "parts": [], "note": "n"},
                  {"id": "hand", "label": "손", "q": "(abs:\"dexterous hand\")", "link": "\"dexterous hand\"", "parts": ["hand"], "note": "n"}]}


def test_periods_are_two_consecutive_years():
    p = papers.periods(TODAY)
    assert p["a"] == (date(2025, 10, 30), TODAY) and p["b"] == (date(2024, 10, 30), date(2025, 10, 29))


def test_total_builds_query_with_dates_and_parses_count():
    seen = []

    def handler(req):
        seen.append(req.url.params["search_query"])
        return httpx.Response(200, text=feed(921))

    ax = make(handler)
    assert ax.total("cat:cs.RO AND abs:humanoid", date(2025, 10, 30), TODAY) == 921
    assert seen == ["cat:cs.RO AND abs:humanoid AND submittedDate:[202510300000 TO 202610292359]"]


def test_total_retries_when_busy_and_raises_on_bad_shape():
    calls = []

    def busy_then_ok(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, text=feed(5))

    assert make(busy_then_ok).total("x", TODAY, TODAY) == 5 and len(calls) == 3
    try:
        make(lambda req: httpx.Response(200, text="<feed/>")).total("x", TODAY, TODAY)
        raise AssertionError("should raise")
    except papers.PapersError:
        pass


def test_collect_refreshes_only_stale_layers_and_keeps_data_on_failure():
    n = {"calls": 0}

    def handler(req):
        n["calls"] += 1
        return httpx.Response(200, text=feed(100 if "humanoid" in req.url.params["search_query"] else 1000))

    data: dict = {}
    papers.collect(CFG, data, make(handler), TODAY)
    assert set(data["layers"]) == {"total", "humanoid", "hand"} and n["calls"] == 6          # 층 3개 × 기간 2개
    papers.collect(CFG, data, make(handler), date(2026, 10, 31))                              # 2일 지남 — 새로 세지 않음
    assert n["calls"] == 6
    papers.collect(CFG, data, make(lambda req: httpx.Response(500, text="boom")), date(2026, 11, 10), force=True)
    assert data["warnings"] and data["layers"]["total"]["a"] == 1000                          # 실패하면 지난 값 보존


def test_paper_block_shares_growth_and_small_sample_flag():
    data = {"layers": {"total": {"a": 1000, "b": 800}, "humanoid": {"a": 100, "b": 40}, "hand": {"a": 12, "b": 6}}, "windows": {"a": ["x", "y"]}}
    b = paper_calc.block(CFG, data)
    assert b["ready"] and b["total"]["growth"] == 1.25 and b["baseline_growth"] == 2.5
    hand = next(r for r in b["rows"] if r["id"] == "hand")
    assert hand["share_a"] == 0.012 and hand["growth"] == 2.0 and hand["small"] is True and "arxiv.org/search" in hand["link"]
    assert paper_calc.block(CFG, {})["ready"] is False and paper_calc.state(paper_calc.block(CFG, {})) == {}


def test_paper_changes_use_threshold_and_baseline():
    assert paper_calc.changed(80, 203) and not paper_calc.changed(100, 110) and not paper_calc.changed(5, 15)
    prev = {"companies": {}, "signposts": {}, "specs": {}, "papers": {"hand": 80, "vla": 300}}
    cur = copy.deepcopy(prev)
    cur["papers"].update(hand=203, vla=310, tactile=40)
    ctx = {"names": {}, "layers": {}, "paper_layers": {"hand": "다지 손"}, "stages": [], "signposts": {}, "models": {}, "spec_labels": {}}
    out = changes.diff(prev, cur, ctx, "2026-11-06")
    assert [c["title"] for c in out] == ["논문 신호(다지 손) 최근 12개월 80 → 203편"] and out[0]["roles"] == ["strategy", "engineer"]
    kept = changes.keep_baseline(prev, cur, out)["papers"]
    assert kept == {"hand": 203, "vla": 300, "tactile": 40}       # 작은 증가(vla)는 기준 유지, 기록된 칸·새 칸만 갱신
    assert changes.diff({"companies": {}, "signposts": {}, "specs": {}}, cur, ctx, "2026-11-06") == []   # 이전에 papers 가 없으면 기준만
