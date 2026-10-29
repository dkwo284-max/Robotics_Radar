import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import patents  # noqa: E402

TODAY = date(2026, 10, 30)


def doc(country, number, kind):
    return {"@family-id": "1", "document-id": {"@document-id-type": "docdb", "country": {"$": country}, "doc-number": {"$": number}, "kind": {"$": kind}}}


def count_js(total, refs=()):
    sr = {"ops:publication-reference": [doc(*r) for r in refs] if len(refs) != 1 else doc(*refs[0])} if refs else {}
    return {"ops:world-patent-data": {"ops:biblio-search": {"@total-result-count": str(total), "ops:search-result": sr}}}


def biblio_js():
    ex = {"@country": "US", "@doc-number": "2025123456", "@kind": "A1", "@family-id": "9",
          "bibliographic-data": {"publication-reference": {"document-id": [{"@document-id-type": "docdb", "date": {"$": "20251020"}},
                                                                            {"@document-id-type": "epodoc", "date": {"$": "20251020"}}]},
                                 "invention-title": [{"@lang": "en", "$": "Strain wave gear for robot joint"}],
                                 "parties": {"applicants": {"applicant": [{"applicant-name": {"name": {"$": "BOSTON DYNAMICS INC"}}}]}}}}
    return {"ops:world-patent-data": {"ops:biblio-search": {"@total-result-count": "5", "ops:search-result": {"exchange-documents": [{"exchange-document": ex}]}}}}


def make_ops(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return patents.OPS("k", "s", client=client, pause=0, sleep=lambda s: None)


def auth_ok(req):
    return req.method == "POST" and "accesstoken" in str(req.url)


def test_parsers_accept_list_and_single_refs_and_biblio():
    assert patents.parse_refs(count_js(2, [("US", "1", "A1"), ("CN", "2", "U")])) == [
        {"country": "US", "number": "1", "kind": "A1"}, {"country": "CN", "number": "2", "kind": "U"}]
    assert patents.parse_refs(count_js(1, [("EP", "3", "B1")]))[0]["kind"] == "B1"   # 결과 1건이면 dict
    assert patents.parse_refs(None) == []
    b = patents.parse_biblio(biblio_js())[0]
    assert (b["country"], b["number"], b["kind"], b["date"]) == ("US", "2025123456", "A1", "2025-10-20")
    assert b["title"] == "Strain wave gear for robot joint" and b["applicant"] == "Boston Dynamics Inc"


def test_quality_shares():
    refs = [{"country": "CN", "number": "1", "kind": "A"}, {"country": "CN", "number": "2", "kind": "U"},
            {"country": "US", "number": "3", "kind": "B2"}, {"country": "WO", "number": "4", "kind": "A1"}]
    q = patents.quality(refs, 40, "CN")
    assert q == {"total": 40, "sample": 4, "granted": 0.25, "utility": 0.25, "intl": 0.5}
    assert patents.quality([], 0, "CN") is None


def test_expressions_scope_and_periods():
    robot = {"pa": ["tesla"], "scope": "robot"}
    any_ = {"pa": ["harmonic drive"], "scope": "any"}
    assert patents.layer_expr(robot, {"cpc": "cpc=F16H49"}) == 'pa="tesla" and cpc=F16H49 and cpc=B25J'
    assert patents.layer_expr(robot, {"cpc": "cpc=H02K and cpc=B25J"}) == 'pa="tesla" and cpc=H02K and cpc=B25J'   # B25J 중복 없음
    assert patents.layer_expr(any_, {"cpc": "cpc=F16H49"}) == 'pa="harmonic drive" and cpc=F16H49'
    assert patents.pa_expr({"pa": ["xpeng", "xiaopeng"]}) == '(pa="xpeng" or pa="xiaopeng")'
    p = patents.periods(TODAY, 3)
    assert p["a"] == (date(2023, 10, 31), TODAY) and p["b"] == (date(2020, 10, 31), date(2023, 10, 30))


def test_search_handles_404_and_date_separator_fallback():
    seen = []

    def handler(req):
        if auth_ok(req):
            return httpx.Response(200, json={"access_token": "t", "expires_in": "1199"})
        q = req.url.params["q"]
        seen.append(q)
        if "none" in q:
            return httpx.Response(404, text="<code>SERVER.EntityNotFound</code>")
        if "20230101 20251231" in q:                       # 공백 구분자 거부
            return httpx.Response(400, text="invalid query")
        return httpx.Response(200, json=count_js(7))

    ops = make_ops(handler)
    assert ops.search('pa="none"')[0] == 0
    assert ops.query('pa="x"', date(2023, 1, 1), date(2025, 12, 31))[0] == 7
    assert ops.sep == ","                                   # 쉼표로 전환되어 기억됨
    assert ops.query('pa="y"', date(2023, 1, 1), date(2025, 12, 31))[0] == 7


def test_collect_respects_budget_and_resumes():
    cfg = {"windows": {"years": 3}, "budget": {"max_searches": 6, "cell_ttl_days": 28, "recent_ttl_days": 6, "recent_days": 60, "quality_months": 12, "pause_seconds": 0},
           "layers": [{"id": "sw", "cpc": "cpc=F16H49"}, {"id": "hand", "cpc": "cpc=B25J15/0009"}], "total": {"cpc": "cpc=B25J"},
           "applicants": [{"id": "ubtech", "name": "UBTech", "company": "ubtech", "kind": "company", "home": "CN", "scope": "robot", "pa": ["ubtech"]},
                          {"id": "harmonic", "name": "Harmonic", "company": None, "kind": "incumbent", "home": "JP", "scope": "any", "pa": ["harmonic drive"], "only": ["sw"]}]}

    def handler(req):
        if auth_ok(req):
            return httpx.Response(200, json={"access_token": "t", "expires_in": "1199"})
        if req.url.path.endswith("/biblio"):
            return httpx.Response(200, json=biblio_js())
        return httpx.Response(200, json=count_js(30, [("CN", "1", "A")]))

    data: dict = {}
    ops = make_ops(handler)
    patents.collect(cfg, data, ops, TODAY)
    assert ops.searches <= 6
    assert data["applicants"]["ubtech"]["recent"][0]["title"].startswith("Strain wave")
    assert data["applicants"]["ubtech"]["quality"]["total"] == 30
    first = len(data["cells"])
    assert 0 < first < 4 and data["status"]["pending"] > 0          # 예산이 모자라 일부만
    patents.collect(cfg, data, make_ops(handler), TODAY)           # 이어서 채움
    assert len(data["cells"]) == 4                                  # ubtech total·sw·hand + harmonic sw
    assert data["cells"]["ubtech|sw"]["a"] == 30 and data["status"]["pending"] == 0
    ops3 = make_ops(handler)
    patents.collect(cfg, data, ops3, TODAY)                         # 신선하므로 아무것도 안 함
    assert ops3.searches == 0


def test_auth_failure_is_reported_not_raised():
    def handler(req):
        return httpx.Response(401, text="bad credentials")

    cfg = {"windows": {"years": 3}, "budget": {"max_searches": 10, "cell_ttl_days": 28, "recent_ttl_days": 6, "recent_days": 60, "quality_months": 12, "pause_seconds": 0},
           "layers": [{"id": "sw", "cpc": "cpc=F16H49"}], "total": {"cpc": "cpc=B25J"},
           "applicants": [{"id": "a", "name": "A", "company": "a", "kind": "company", "home": "US", "scope": "robot", "pa": ["a"]}]}
    data: dict = {}
    patents.collect(cfg, data, make_ops(handler), TODAY)
    assert data["warnings"] and "인증 실패" in data["warnings"][0]
