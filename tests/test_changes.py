import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import changes  # noqa: E402
import digest  # noqa: E402

CTX = {"names": {"figure": "피규어 AI"}, "stages": ["비상장", "IPO 준비", "신청·심사", "공모·상장 진행", "상장", "사업부"],
       "signposts": {"us_ban": "GUARD Act 통과"}, "models": {"figure03": ("Figure 03", "figure")},
       "spec_labels": {"hand_dof": "손 자유도", "actuator": "구동 방식"}}
BASE = {
    "companies": {"figure": {"total": 73, "attract": 71, "tier": 1, "stage": 0, "facts": {"valuation": 39000, "cum_units": 1000},
                             "roadmap": {"production|양산 확대": ["planned", "2027"]}}},
    "signposts": {"us_ban": "progress"},
    "specs": {"figure03": {"hand_dof": None, "actuator": "custom"}},
}


def test_no_previous_state_means_no_changes():
    assert changes.diff(None, BASE, CTX, "2026-10-30") == []
    assert changes.diff(BASE, copy.deepcopy(BASE), CTX, "2026-10-30") == []


def test_each_kind_of_change_is_logged_with_roles():
    cur = copy.deepcopy(BASE)
    f = cur["companies"]["figure"]
    f.update(total=65, tier=2, stage=1)
    f["facts"]["valuation"] = 60000
    f["roadmap"]["production|양산 확대"] = ["delayed", "2028"]
    f["roadmap"]["product|Figure 04"] = ["planned", "2027"]
    cur["signposts"]["us_ban"] = "happened"
    cur["specs"]["figure03"]["hand_dof"] = 20
    got = {c["kind"]: c for c in changes.diff(BASE, cur, CTX, "2026-10-30")}
    assert got["tier"]["title"] == "피규어 AI Tier 1 → 2" and "exec" in got["tier"]["roles"]
    assert got["listing"]["title"].endswith("비상장 → IPO 준비")
    assert got["fact"]["title"] == "피규어 AI 밸류 $39.0B → $60.0B"
    assert got["signpost"]["roles"] == ["exec", "strategy"]
    assert got["spec"]["title"] == "Figure 03 손 자유도 미공개 → 20" and got["spec"]["layer"] == "hand"
    roadmap = [c for c in changes.diff(BASE, cur, CTX, "2026-10-30") if c["kind"] == "roadmap"]
    assert {c["title"] for c in roadmap} == {"피규어 AI '양산 확대' 계획 → 지연·변경", "피규어 AI 새 로드맵: Figure 04 (2027)"}
    assert all("exec" in c["roles"] for c in roadmap if "양산" in c["title"])


def test_digest_due_rules():
    assert digest.due({}, "2026-10-30", False)
    recent = {"items": [{"to": "2026-10-28", "ai": True}]}
    assert not digest.due(recent, "2026-10-30", True)
    assert digest.due({"items": [{"to": "2026-10-28", "ai": False}]}, "2026-10-30", True)  # AI 로 다시 만들 수 있으면
    assert digest.due({"items": [{"to": "2026-10-23", "ai": True}]}, "2026-10-30", True)


def test_digest_fallback_uses_roles():
    news = [{"id": "a", "date": "2026-10-29", "title": "t", "title_ko": "엔지니어 소식", "ai": True, "importance": 2, "type": "product", "audience": ["engineer"]},
            {"id": "b", "date": "2026-10-29", "title": "raw", "ai": False, "importance": 1, "type": "other"}]
    ch = [{"date": "2026-10-29", "title": "Tier 변화", "roles": ["exec"]}]

    class NoAI:
        enabled, requests = False, 0
    d = digest.make(ch, news, NoAI(), "2026-10-30")
    assert d["ai"] is False
    assert d["roles"]["exec"]["bullets"][0]["text"] == "Tier 변화"
    assert [b["refs"] for b in d["roles"]["engineer"]["bullets"]] == [["a"]]
