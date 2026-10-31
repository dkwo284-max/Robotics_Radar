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


ORIGINALS = ["Mobis eyes prototype run", "Hyundai parts arm readies trial output", "Seoul supplier begins sample builds",
             "Quarterly figures beat forecast", "Spring harvest festival opens", "Battery cell maker expands plant"]  # 서로 전혀 다른 원문 제목


def ko(i, title_ko, date="2026-10-30", companies=("hyundai",), importance=3, **kw):
    # 원문 제목은 매체마다 완전히 달라 1차(원문 제목 유사도)로는 못 묶이는 상황
    return item(i, ORIGINALS[i % len(ORIGINALS)], date=date, source=f"S{i}", ai=True, title_ko=title_ko,
                companies=list(companies), importance=importance, **kw)


def test_same_event_with_different_korean_wording_counts_once():
    """엔지니어 화면의 '주요 변화 3건'이 사실은 같은 사건(현대모비스 아틀라스 부품 시제품 생산)이던 경우."""
    items = [ko(1, "현대모비스, 아틀라스 휴머노이드 로봇 부품 시제품 다음 달 생산"),
             ko(2, "현대모비스, 다음 달 아틀라스 액추에이터 시제품 생산 착수"),
             ko(3, "현대모비스, 아틀라스 핵심부품 시제품 생산")]
    out = nc.tidy(items)
    assert len(out) == 1 and out[0]["n_src"] == 3 and set(out[0]["also"]) == {"S2", "S3"}


def test_korean_rule_keeps_different_events_separate():
    base = [ko(1, "현대모비스, 아틀라스 부품 시제품 다음 달 생산"),
            ko(2, "현대차그룹, 새만금에 9조원 투자해 AI 밸리 구축")]                       # 같은 기업이어도 내용이 다르면 별개
    assert len(nc.tidy(base)) == 2
    other_company = [ko(1, "현대모비스, 아틀라스 부품 시제품 다음 달 생산", companies=("hyundai",)),
                     ko(2, "현대모비스, 아틀라스 부품 시제품 다음 달 생산", companies=("tesla",))]  # 기업이 겹치지 않으면 묶지 않음
    assert len(nc.tidy(other_company)) == 2
    numbers = [ko(1, "두산로보틱스, 3분기 영업손실 134억원 기록", companies=("doosan",)),
               ko(2, "두산로보틱스, 3분기 영업손실 201억원 기록", companies=("doosan",))]        # 숫자가 어긋나면 다른 사건
    assert len(nc.tidy(numbers)) == 2
    far = [ko(1, "현대모비스, 아틀라스 부품 시제품 생산"), ko(2, "현대모비스, 아틀라스 부품 시제품 생산", date="2026-11-05")]
    assert len(nc.tidy(far)) == 2                                                          # 날짜가 멀면 별개


def test_unclassified_items_are_not_merged_by_the_korean_rule():
    a = ko(1, "현대모비스, 아틀라스 부품 시제품 생산"); b = ko(2, "현대모비스, 아틀라스 핵심부품 시제품 생산")
    a["ai"] = False
    assert len(nc.tidy([a, b])) == 2
