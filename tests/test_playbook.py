import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import playbook as pb  # noqa: E402


def co(i, tech, scale, capital, execution, **kw):
    return {"id": i, "name": i, "name_ko": i, "scores": {"tech": [tech, "t"], "scale": [scale, "s"], "capital": [capital, "c"], "execution": [execution, "e"]},
            "roadmap": [{"when": "2028", "status": "planned", "title": "공장"}], "customers": [], "risks": ["적자"], **kw}


def test_gaps_actions_parent_support_and_shortest_path():
    cos = [co("bd", 27, 14, 18, 12, parent="hy"), co("hy", 14, 12, 20, 12), co("top", 22, 28, 18, 18)]
    news = [{"date": "2026-11-10", "companies": ["hy"], "title": "Hyundai to build robot factory", "title_ko": "현대차 로봇 공장 착공", "url": "u", "importance": 3}]
    out = pb.build(cos, news, "2026-11-12")
    t = out["targets"]["bd"]
    assert out["default"] == "bd" and t["rank"] == 2 and t["leader"] == "top" and t["leader_total"] == 86
    g = {x["axis"]: x for x in t["gaps"]}
    assert g["scale"]["gap"] == 14 and g["scale"]["leader"] == "top" and g["tech"]["gap"] == 0       # 기술은 이미 1위 → 행동 없음
    acts = {a["id"]: a for a in t["actions"]}
    assert "T1" not in acts and sum(a["gain"] for a in t["actions"] if a["axis"] == "scale") == 14  # 축별 예상 점수 합 = 격차
    assert acts["S1"]["has_parent"] and "그룹" in acts["S1"]["support"] and acts["S2"]["progress"]["n"] == 1   # 모회사 소식도 진척으로 센다
    assert t["reachable"] == 71 + 14 + 2 + 6 and t["shortest"] and sum(acts[i]["gain"] for i in t["shortest"]) >= 86 - 71 + 1
    solo = pb.build([co("a", 10, 10, 10, 10), co("top", 22, 28, 18, 18)], [], "2026-11-12")["targets"]["a"]
    assert not solo["actions"][0]["has_parent"] and "그룹" not in solo["actions"][0]["support"]
