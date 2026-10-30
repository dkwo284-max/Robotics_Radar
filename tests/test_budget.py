import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from datetime import datetime, timezone

import httpx

from budget import allowance, nz_today

BUDGET = {"reserve": 3, "apps": {
    "daily-brief": {"guaranteed": 7, "usage": "/News_Summary/data/ai-usage.json"},
    "whale-radar": {"guaranteed": 3, "usage": "/Whale_Radar/data/ai-usage.json"},
    "robotics-radar": {"guaranteed": 3, "usage": "/Robotics_Radar/data/ai-usage.json"}}}


def _client(used: dict[str, int | None], budget=BUDGET, day="2026-10-30"):
    def handler(req):
        p = req.url.path
        if p == "/budget.json":
            return httpx.Response(200, json=budget) if budget else httpx.Response(404)
        for path, app in (("/News_Summary/", "daily-brief"), ("/Whale_Radar/", "whale-radar"), ("/Robotics_Radar/", "robotics-radar")):
            if p.startswith(path):
                n = used.get(app)
                return httpx.Response(200, json={"days": {day: {"requests": n}}}) if n is not None else httpx.Response(404)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_nz_day_resets_at_auckland_midnight():
    assert nz_today(datetime(2026, 10, 29, 10, 59, tzinfo=timezone.utc)) == "2026-10-29"   # 뉴질랜드 23:59
    assert nz_today(datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)) == "2026-10-30"    # 뉴질랜드 00:00 (서머타임 UTC+13)


def test_unused_guarantee_and_full_reserve():
    left, info = allowance("daily-brief", 0, 7, "2026-10-30", _client({"whale-radar": 1, "robotics-radar": 2}))
    assert left == 7 + 3 and info["complete"]


def test_others_overuse_eats_reserve_but_not_my_guarantee():
    # 웨일이 5회(보장 3 → 예비 2 사용), 로보틱스 3회 → 예비 1 남음. 내 보장량 7 은 그대로
    left, _ = allowance("daily-brief", 2, 7, "2026-10-30", _client({"whale-radar": 5, "robotics-radar": 3}))
    assert left == (7 - 2) + 1
    left, _ = allowance("daily-brief", 6, 7, "2026-10-30", _client({"whale-radar": 6, "robotics-radar": 3}))
    assert left == 1 + 0          # 예비분이 다 소진돼도 남은 내 보장량 1회는 지켜짐


def test_my_overuse_counts_against_reserve():
    left, _ = allowance("whale-radar", 4, 3, "2026-10-30", _client({"daily-brief": 6, "robotics-radar": 1}))
    assert left == 0 + (3 - 1)    # 내가 예비 1 사용 → 예비 2 남음


def test_unreadable_other_app_disables_reserve():
    left, info = allowance("whale-radar", 1, 3, "2026-10-30", _client({"daily-brief": 6, "robotics-radar": None}))
    assert left == 2 and not info["complete"] and info["reserve_left"] == 0


def test_missing_budget_falls_back_to_local_guarantee():
    left, info = allowance("whale-radar", 1, 3, "2026-10-30", _client({}, budget=None))
    assert left == 2 and info["mode"] == "local"
    left, _ = allowance("whale-radar", 5, 3, "2026-10-30", _client({}, budget=None))
    assert left == 0
