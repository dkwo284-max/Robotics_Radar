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
        kw = " robot patent" if "patent" in url else ""
        item = (f"<item><title>Story {n}{kw} - Src</title><link>https://x.test/{n}</link><pubDate>{__import__('email.utils').utils.formatdate(usegmt=True)}</pubDate>"
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


def test_patent_topic_drops_articles_without_patent_and_robot_words():
    class Client(_FakeClient):
        def get(self, url):
            self.urls.append(url)
            titles = ["Canon hit with class-action lawsuit", "Tesla patent reveals touch skin for robot hands", "로봇 AI 특허 4건 등록"]
            items = "".join(f"<item><title>{t} - Src</title><link>https://x.test/{i}</link><pubDate>{__import__('email.utils').utils.formatdate(usegmt=True)}</pubDate><source url='https://s.test'>Src</source></item>"
                            for i, t in enumerate(titles))
            return _Resp(f"<?xml version='1.0'?><rss><channel>{items}</channel></rss>".encode())

    cfg = {"news": {"lookback_days": 7, "lookback_days_patent": 30, "per_company": 3, "per_company_patent": 5, "queries": {},
                    "patent_queries": {"tesla": [["tesla patent", "en"]]}}}
    client = Client()
    got = news.collect(cfg, client, set())
    assert [x["title"] for x in got] == ["Tesla patent reveals touch skin for robot hands", "로봇 AI 특허 4건 등록"]
    assert "30d" in client.urls[0]                                                    # 특허 질의는 조회 기간을 30일로


# ---------- 증분 수집 ----------
def test_plan_window_backfills_once_then_only_new_days():
    ncfg = {"backfill_days": 30, "lookback_days": 7, "per_company": 3, "per_company_patent": 2, "per_company_backfill": 8, "per_company_patent_backfill": 4}
    today = date(2026, 10, 29)
    first = news.plan_window(ncfg, {}, today)
    assert first == {"days": 30, "per": 8, "per_patent": 4, "backfill": True}                 # 이력이 없으면 한 번 백필
    assert news.plan_window(ncfg, {"covered_days": 30, "generated_at": "2026-10-29T03:00+00:00"}, today)["days"] == 2     # 오늘 이미 수집 — 겹치게 2일
    assert news.plan_window(ncfg, {"covered_days": 30, "generated_at": "2026-10-27T03:00+00:00"}, today) == {"days": 3, "per": 3, "per_patent": 2, "backfill": False}
    assert news.plan_window(ncfg, {"covered_days": 30, "generated_at": "2026-09-01T00:00+00:00"}, today)["days"] == 7        # 오래 쉬었어도 최대 lookback_days
    assert news.plan_window(ncfg, {"covered_days": 10}, today)["backfill"] is True                                           # 이력이 모자라면 다시 백필


def test_update_news_backfills_then_fetches_only_the_recent_window():
    cfg = _news_cfg()
    cfg["news"].update(backfill_days=30, lookback_days=7, max_ai_items=10)
    c1 = _FakeClient()
    out1 = news.update_news(cfg, {}, COMPANIES, FakeLLM(enabled=False), client=c1)
    assert all("when:30d" in u for u in c1.urls) and out1["covered_days"] == 30 and out1["covered_from"]
    c2 = _FakeClient()
    out2 = news.update_news(cfg, out1, COMPANIES, FakeLLM(enabled=False), client=c2)
    assert all("when:2d" in u for u in c2.urls)                                    # 이후에는 최근 이틀만 요청
    assert out2["covered_days"] == 30


def test_failed_backfill_is_not_counted_as_history():
    class Down:
        def get(self, url):
            raise RuntimeError("network down")

    cfg = _news_cfg()
    cfg["news"].update(backfill_days=30, lookback_days=7)
    out = news.update_news(cfg, {}, COMPANIES, FakeLLM(enabled=False), client=Down())
    assert out["covered_days"] == 0                                                # 질의 대부분이 실패하면 다음 실행에서 다시 백필


def test_prices_fetch_three_months_once_then_only_ten_days_and_merge():
    import prices

    class C:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            days = 70 if "range=3mo" in url else 3
            start = 1_700_000_000 + (0 if "range=3mo" in url else 68 * 86400)
            js = {"chart": {"result": [{"meta": {"currency": "USD"}, "timestamp": [start + i * 86400 for i in range(days)],
                                        "indicators": {"quote": [{"close": [100 + (0 if "range=3mo" in url else 68) + i for i in range(days)]}]}}]}}

            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return js
            return R()

    cfg = {"tickers": {"tesla": "TSLA"}, "ticker_notes": {}}
    c = C()
    first = prices.update_prices(cfg, {}, client=c)
    assert "range=3mo" in c.urls[0] and len(first["hist"]["tesla"]) == 70
    c2 = C()
    second = prices.update_prices(cfg, first, client=c2)
    assert "range=10d" in c2.urls[0]                                                # 60일 넘게 쌓였으면 최근 구간만
    assert len(second["hist"]["tesla"]) >= 70 and second["quotes"]["tesla"]["last"] == 170 and len(second["quotes"]["tesla"]["spark"]) == 60


def test_gemini_http_attempts_are_capped_and_ai_can_be_switched_off(monkeypatch):
    import httpx as hx

    import llm as llm_mod

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        return hx.Response(500, text="boom")

    cfg = {"llm": {"models": ["m1", "m2", "m3", "m4"], "max_requests_per_run": 2, "max_http_attempts": 3}}
    g = llm_mod.Gemini(cfg, client=hx.Client(transport=hx.MockTransport(handler)))
    try:
        g.json_call("s", "u", {})
        raise AssertionError("should fail")
    except llm_mod.LLMError:
        pass
    assert len(calls) == 3                                                          # 모델 4개 × 2회가 아니라 요청 1건당 HTTP 3회까지
    assert llm_mod.Gemini({"llm": {"enabled": False}}).enabled is False             # 키가 있어도 AI 완전 끄기
