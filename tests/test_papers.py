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


def test_month_helpers_and_finality():
    assert papers.month_list(date(2026, 10, 29), 3) == ["2026-07", "2026-08", "2026-09"]
    assert papers.month_list(date(2027, 1, 5), 2) == ["2026-11", "2026-12"]
    assert papers.month_range("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert papers.is_final([100, "2026-10-09"], "2026-09") is True       # 9월이 끝난 지 8일 뒤에 센 값 → 확정
    assert papers.is_final([100, "2026-10-05"], "2026-09") is False      # 아직 늦은 제출이 더 올라올 수 있음
    assert papers.is_final(None, "2026-09") is False


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


def test_collect_counts_months_caches_final_ones_and_keeps_data_on_failure():
    n = {"calls": 0}

    def handler(req):
        n["calls"] += 1
        return httpx.Response(200, text=feed(100 if "humanoid" in req.url.params["search_query"] else 1000))

    cfg = {**CFG, "months": 4}
    data: dict = {}
    saved = []
    papers.collect(cfg, data, make(handler), TODAY, on_layer_done=lambda: saved.append(1))
    assert n["calls"] == 12 and len(saved) == 3                                      # 층 3개 × 4개월, 층마다 저장
    assert data["month_list"] == ["2026-06", "2026-07", "2026-08", "2026-09"] and data["months"]["total"]["2026-09"] == [1000, "2026-10-29"]
    papers.collect(cfg, data, make(handler), date(2026, 10, 31))                      # 2일 뒤 — 새로 세지 않음(6일 미만)
    assert n["calls"] == 12
    papers.collect(cfg, data, make(handler), date(2026, 11, 10))                      # 10월이 끝난 달로 편입 — 6~9월은 확정이라 10월만 센다
    assert n["calls"] - 12 == 3
    papers.collect(cfg, data, make(lambda req: httpx.Response(500, text="boom")), date(2026, 12, 20), force=True)
    assert data["warnings"] and data["months"]["total"]["2026-09"][0] == 1000       # 실패해도 창 안의 지난 값은 보존
    assert "2026-06" not in data["months"]["total"]                                # 창(최근 4개월) 밖의 오래된 달은 정리됨


def test_paper_block_sums_two_year_halves_and_exposes_series():
    months = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 13)]
    cell = lambda vals: {m: [v, "2027-01-20"] for m, v in zip(months, vals)}   # noqa: E731
    data = {"month_list": months, "months": {"total": cell([100] * 12 + [150] * 12), "humanoid": cell([10] * 12 + [25] * 12), "hand": cell([1] * 12 + [2] * 12)}}
    b = paper_calc.block({**CFG, "months": 24}, data)
    assert b["ready"] and b["total"]["a"] == 1800 and b["total"]["b"] == 1200 and b["total"]["growth"] == 1.5
    assert b["windows"] == {"a": ["2026-01", "2026-12"], "b": ["2025-01", "2025-12"]} and b["baseline_growth"] == 2.5
    hand = next(r for r in b["rows"] if r["id"] == "hand")
    assert (hand["a"], hand["b"], hand["growth"]) == (24, 12, 2.0) and hand["small"] is True and len(hand["series"]) == 24 and "arxiv.org/search" in hand["link"]
    assert paper_calc.block(CFG, {})["ready"] is False
    del data["months"]["hand"]["2026-12"]                                       # 한 층에 빈 달이 있으면 그 층만 빠진다
    assert [r["id"] for r in paper_calc.block({**CFG, "months": 24}, data)["rows"]] == ["humanoid"]


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


def test_months_counted_before_they_settle_are_refreshed_later():
    calls = []

    def handler(req):
        calls.append(req.url.params["search_query"][-30:])
        return httpx.Response(200, text=feed(7))

    cfg = {**CFG, "months": 2, "layers": [], "total": {"id": "total", "q": ""}}
    data: dict = {}
    papers.collect(cfg, data, make(handler), date(2026, 10, 3))          # 9월이 끝난 지 3일 — 아직 늦은 제출이 더 올라올 수 있다
    assert data["month_list"] == ["2026-08", "2026-09"] and len(calls) == 2
    papers.collect(cfg, data, make(handler), date(2026, 10, 6))          # 3일 뒤 — 6일 미만이라 그대로
    assert len(calls) == 2
    papers.collect(cfg, data, make(handler), date(2026, 10, 12))         # 9일 뒤 — 8월은 확정, 9월은 8일이 지난 뒤 다시 센다
    assert len(calls) == 3 and data["months"]["total"]["2026-09"][1] == "2026-10-12"
    papers.collect(cfg, data, make(handler), date(2026, 10, 30))         # 확정된 뒤에는 다시 세지 않는다
    assert len(calls) == 3
