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
