import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build  # noqa: E402
import news  # noqa: E402
import prices  # noqa: E402

TODAY = date.today().strftime("%a, %d %b %Y 09:00:00 GMT")
RSS = f"""<?xml version="1.0"?><rss><channel>
<item><title>Figure raises $2B at $60B valuation - Reuters</title><link>https://x.test/a</link>
<pubDate>{TODAY}</pubDate><source url="https://reuters.com">Reuters</source><description>Figure raises $2B at $60B valuation Reuters</description></item>
<item><title>Old story - Blog</title><link>https://x.test/b</link><pubDate>Mon, 01 Jan 2024 09:00:00 GMT</pubDate></item>
</channel></rss>"""

COMPANIES = [{"id": "figure", "name": "Figure AI", "name_ko": "피규어 AI", "valuation": {"v": 39000}, "cum_units": {"v": None}}]


class FakeLLM:
    def __init__(self, reply=None, enabled=True):
        self.reply, self.enabled, self.requests = reply, enabled, 0

    def json_call(self, system, user, schema):
        self.requests += 1
        return self.reply


def test_parse_feed_strips_source_and_old_items():
    items = news.parse_feed(RSS, "figure", 7, "en")
    assert len(items) == 1
    assert items[0]["title"] == "Figure raises $2B at $60B valuation"
    assert items[0]["source"] == "Reuters"


def test_classify_without_key_keeps_titles():
    items = news.parse_feed(RSS, "figure", 7, "en")
    out, warn, dropped = news.classify(items, COMPANIES, FakeLLM(enabled=False), 40)
    assert out[0]["ai"] is False and out[0]["companies"] == ["figure"] and warn and dropped == []


def test_classify_filters_unknown_ids_and_bad_facts():
    items = news.parse_feed(RSS, "figure", 7, "en")
    reply = {"items": [{"id": items[0]["id"], "relevant": True, "companies": ["figure", "nope"], "type": "funding",
                        "title_ko": "피규어 20억 달러 조달", "summary_ko": "밸류 600억 달러", "importance": 5,
                        "facts": [{"company": "figure", "field": "valuation", "value": 60000, "as_of": "2026-10"},
                                  {"company": "nope", "field": "valuation", "value": 1},
                                  {"company": "figure", "field": "valuation", "value": -3}]}]}
    out, _, _ = news.classify(items, COMPANIES, FakeLLM(reply), 40)
    assert out[0]["companies"] == ["figure"]
    assert out[0]["importance"] == 3
    assert len(out[0]["facts"]) == 1


def test_classify_drops_irrelevant():
    items = news.parse_feed(RSS, "figure", 7, "en")
    reply = {"items": [{"id": items[0]["id"], "relevant": False, "companies": [], "type": "other",
                        "title_ko": "", "summary_ko": "", "importance": 1, "facts": []}]}
    out, _, dropped = news.classify(items, COMPANIES, FakeLLM(reply), 40)
    assert out == [] and dropped == [items[0]["id"]]


def test_proposals_only_when_different():
    base = {"date": date.today().isoformat(), "title": "t", "url": "u", "id": "n1"}
    same = {**base, "facts": [{"company": "figure", "field": "valuation", "value": 40000, "as_of": ""}]}
    diff = {**base, "facts": [{"company": "figure", "field": "valuation", "value": 60000, "as_of": ""}]}
    empty = {**base, "facts": [{"company": "figure", "field": "cum_units", "value": 1500, "as_of": ""}]}
    assert news.proposals([same], COMPANIES, []) == []
    got = news.proposals([diff, empty], COMPANIES, [])
    assert {(p["field"], p["curated"], p["proposed"]) for p in got} == {("valuation", 39000, 60000), ("cum_units", None, 1500)}


def test_price_parse_changes():
    closes = [100 + i for i in range(30)]
    js = {"chart": {"result": [{"meta": {"currency": "USD"}, "timestamp": [1_700_000_000 + i * 86400 for i in range(30)],
                                "indicators": {"quote": [{"close": closes}]}}]}}
    q = prices.parse(js)
    assert q["last"] == 129 and q["chg_1w"] == round((129 / 124 - 1) * 100, 1) and len(q["spark"]) == 30
    assert prices.parse({"chart": {"result": []}}) is None


def test_score_moves_and_tier_change():
    out, _ = build.build(history={"snapshots": []})
    comps = out["companies"]
    hist = {"snapshots": [{"date": "2026-10-01", "scores": {c["id"]: [c["calc"]["total"], c["calc"]["attract"]] for c in comps}}]}
    hist["snapshots"][0]["scores"]["figure"] = [60, 71]
    moves = build.score_moves(comps, hist)
    assert moves["figure"]["d_total"] == 13 and moves["figure"]["tier_from"] == 2
    assert "tesla" not in moves


def test_plausible_filters_unit_mistakes():
    from common import plausible
    assert plausible("cum_units", 15000, 110) is False      # 누적값 감소 (행사 동원 대수)
    assert plausible("valuation", 39000, 40000) is False    # 10% 이내 = 같은 값
    assert plausible("valuation", 39000, 60000) is True
    assert plausible("valuation", 39000, 390) is False      # 1/100 — 단위 착오
    assert plausible("price", None, 20) is False            # 대당 $20 은 불가능
    assert plausible("cum_units", None, 1500) is True


def test_needs_retry_covers_items_classified_before_new_tags():
    assert news.needs_retry({"ai": False}) is True                      # AI 분류 전
    assert news.needs_retry({"ai": True}) is True                       # 역할·기술 층 태그가 생기기 전에 분류됨
    assert news.needs_retry({"ai": True, "layer": "none"}) is False     # 'none' 도 분류가 끝난 값


class _Resp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class _FakeClient:
    """질의마다 기사 1건을 돌려주는 가짜 RSS 클라이언트."""

    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        n = len(self.urls)
        item = (f"<item><title>Story {n} - Src</title><link>https://x.test/{n}</link><pubDate>{__import__('email.utils').utils.formatdate(usegmt=True)}</pubDate>"
                f"<source url='https://s.test'>Src</source></item>")
        return _Resp(f"<?xml version='1.0'?><rss><channel>{item}</channel></rss>".encode())


def test_collect_tags_patent_topic_and_plain_fallback_type():
    cfg = {"news": {"lookback_days": 7, "per_company": 3, "per_company_patent": 2,
                    "queries": {"_market": [["humanoid", "en"]], "tesla": [["tesla", "en"]]},
                    "patent_queries": {"_market": [["humanoid patent", "en"]], "tesla": [["tesla patent", "en"]]}}}
    client = _FakeClient()
    got = news.collect(cfg, client, set())
    assert [x["topic"] for x in got] == ["news", "news", "patent", "patent"]
    assert any("patent" in u for u in client.urls)
    out, warn, _ = news.classify(got, COMPANIES, FakeLLM(enabled=False), 40)
    assert [x["type"] for x in out] == ["other", "other", "patent", "patent"]   # AI 없이도 특허 검색어로 모은 기사는 특허 유형


def test_pref_changes_are_logged_only_after_a_baseline_exists():
    import changes

    ctx = {"names": {"tesla": "테슬라"}, "layers": {}, "stages": [], "signposts": {}, "models": {}, "spec_labels": {}}
    base = {"companies": {}, "signposts": {}, "specs": {}}
    cur = {**base, "pref": {"tesla": {"portfolio": {"기준A": 10}, "notable": ["소송 합의"]}}}
    assert changes.diff({**base}, cur, ctx, "2026-11-01") == []                     # 이전 상태에 pref 가 없으면 기준만 잡는다
    prev = {**base, "pref": {"tesla": {"portfolio": {"기준A": 8}, "notable": []}}}
    out = changes.diff(prev, cur, ctx, "2026-11-01")
    assert {c["title"] for c in out} == {"테슬라 특허 포트폴리오(보도) 8 → 10건 (기준A)", "테슬라 특허·지재권 이슈: 소송 합의"}
    assert all(c["kind"] == "pref" and c["company"] == "tesla" for c in out)
    assert "kind" not in changes.keep_baseline(prev, cur, out)                      # 기준값 보존 로직이 pref 항목(layer 없음)에 깨지지 않는다


class _BatchLLM:
    """요청한 id 를 그대로 '관련 있음'으로 돌려주는 가짜 Gemini. 요청 수 상한을 흉내 낸다."""

    enabled = True

    def __init__(self, max_requests):
        self.max_requests, self.requests, self.calls = max_requests, 0, []

    def json_call(self, system, user, schema, max_tokens=0):
        import re

        if self.requests >= self.max_requests:
            raise news.LLMError("max_requests_per_run reached")
        self.requests += 1
        ids = re.findall(r"\[id\] (\S+)", user)
        self.calls.append(ids)
        return {"items": [{"id": i, "relevant": True, "companies": [], "type": "patent", "title_ko": "제목", "summary_ko": "요약", "importance": 1,
                           "audience": ["engineer"], "layer": "hand", "signpost": "none", "facts": []} for i in ids]}


def _news_cfg():
    return {"news": {"lookback_days": 7, "per_company": 3, "max_ai_items": 2, "keep_days": 120,
                     "queries": {"a": [["x", "en"]], "b": [["y", "en"]], "c": [["z", "en"]]}}}


def test_update_news_classifies_in_chunks_within_the_request_budget():
    llm = _BatchLLM(max_requests=1)
    out = news.update_news(_news_cfg(), {}, COMPANIES, llm, client=_FakeClient())
    assert llm.requests == 1 and len(llm.calls[0]) == 2
    assert len(out["items"]) == 2 and all(x["ai"] and x["layer"] == "hand" for x in out["items"])   # 예산 밖의 세 번째 기사는 저장하지 않고 다음 실행으로
    llm2 = _BatchLLM(max_requests=2)
    out2 = news.update_news(_news_cfg(), {}, COMPANIES, llm2, client=_FakeClient())
    assert llm2.requests == 2 and [len(c) for c in llm2.calls] == [2, 1] and len(out2["items"]) == 3


def test_update_news_reclassifies_untagged_old_items_after_fresh_ones():
    old = {"items": [{"id": "old1", "date": date.today().isoformat(), "title": "t", "source": "s", "url": "u", "query": "a", "ai": True, "type": "other",
                      "companies": [], "importance": 1, "title_ko": "", "summary_ko": "", "facts": []}]}   # layer 태그가 생기기 전에 분류된 기사
    llm = _BatchLLM(max_requests=2)
    out = news.update_news({"news": {**_news_cfg()["news"], "max_ai_items": 10, "queries": {"a": [["x", "en"]]}}}, old, COMPANIES, llm, client=_FakeClient())
    assert llm.calls[0][-1] == "old1" and llm.calls[0][0] != "old1"                                       # 새 기사 먼저
    assert next(x for x in out["items"] if x["id"] == "old1")["layer"] == "hand"
