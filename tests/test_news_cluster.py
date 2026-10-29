import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import news_cluster as nc  # noqa: E402


def item(i, title, date="2026-10-20", source="A", **kw):
    return {"id": str(i), "title": title, "date": date, "source": source, **kw}


def test_same_story_from_several_outlets_is_merged_and_prefers_classified():
    a = item(1, "Formic Raises $50 Million to Scale Physical AI Across American Manufacturing", source="PR")
    b = item(2, "Formic Raises $50 Million to Expand Physical AI Across America - Pulse 2.0", date="2026-10-21", source="Pulse", ai=True, importance=2)
    out = nc.tidy([a, b])
    assert len(out) == 1 and out[0]["id"] == "2" and out[0]["n_src"] == 2 and out[0]["also"] == ["PR"]


def test_templated_titles_with_different_numbers_stay_separate():
    a = item(1, "Europe Robotics Market to Reach USD 54.05 Billion by 2035, Growing at CAGR")
    b = item(2, "North America Robotics Market to Reach USD 67.71 Billion by 2035, Growing at CAGR")
    assert len(nc.tidy([a, b])) == 2


def test_far_apart_dates_are_not_merged():
    a = item(1, "Tesla begins humanoid production in California")
    b = item(2, "Tesla begins humanoid production in California", date="2026-10-29")
    assert len(nc.tidy([a, b])) == 2


def test_market_patent_items_need_a_humanoid_or_physical_ai_word():
    keep = item(1, "Tesla patent reveals touch-sensitive skin for humanoid hands", topic="patent", query="_market")
    drop = item(2, "Delivery robots face lawsuit over biometric scans", topic="patent", query="_market")
    company = item(3, "Delivery robots face lawsuit", topic="patent", query="tesla")
    assert [x["id"] for x in nc.tidy([keep, drop, company])] == ["1", "3"] or {x["id"] for x in nc.tidy([keep, drop, company])} == {"1", "3"}
