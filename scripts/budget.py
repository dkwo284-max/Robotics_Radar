"""공용 AI 예산: 세 앱(Daily Brief · 웨일 레이더 · 로보틱스 레이더)이 같은 Gemini 키의 하루 몫을 나눠 쓴다.

※ 이 파일은 세 저장소에 똑같이 들어 있습니다. 고칠 때는 세 곳을 함께 고치세요.

- 예산표는 My Hub 의 budget.json (총량·앱별 보장량·공유 예비분). 숫자는 거기서만 바꾼다.
- 하루 기준: 뉴질랜드(오클랜드) 시간 00시 리셋.
- 앱마다 '보장량'은 다른 앱이 뺏지 못한다. 보장량을 넘어 쓴 만큼은 공유 예비분에서 가져가고,
  예비분이 남아 있을 때만 더 쓸 수 있다. 다른 앱 사용량은 My Hub 주소의 각 앱 ai-usage.json 을 읽어 계산한다.
- 예산표나 다른 앱 기록을 읽지 못하면 안전하게 '내 보장량'만 쓴다(예비분은 쓰지 않음).
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

HUB = "https://dkwo284-max.github.io"
DAY_TZ = ZoneInfo("Pacific/Auckland")


def nz_today(now: datetime | None = None) -> str:
    """오클랜드 기준 오늘 날짜 (00시에 바뀜)."""
    return (now or datetime.now(DAY_TZ)).astimezone(DAY_TZ).date().isoformat()


def fetch_json(url: str, client: httpx.Client | None = None, timeout: float = 10) -> dict | None:
    try:
        c = client or httpx.Client(timeout=timeout, follow_redirects=True)
        try:
            r = c.get(url, headers={"Cache-Control": "no-cache"})
            r.raise_for_status()
            return r.json()
        finally:
            if client is None:
                c.close()
    except Exception:  # noqa: BLE001 — 읽지 못하면 안전 모드
        return None


def allowance(app: str, own_used: int, fallback_guaranteed: int, today: str | None = None,
              client: httpx.Client | None = None) -> tuple[int, dict]:
    """오늘 이 앱이 더 보낼 수 있는 AI 요청 수와 진단 정보.

    own_used: 이 앱의 오늘 사용량(로컬 장부 — 가장 정확)
    fallback_guaranteed: 예산표를 못 읽을 때 쓸 내 보장량
    """
    today = today or nz_today()
    budget = fetch_json(f"{HUB}/budget.json", client)
    apps = (budget or {}).get("apps", {})
    if app not in apps:
        left = max(0, fallback_guaranteed - own_used)
        return left, {"mode": "local", "guaranteed": fallback_guaranteed, "used": own_used, "reserve_left": 0}
    mine = int(apps[app]["guaranteed"])
    reserve = int(budget.get("reserve", 0))
    reserve_used = max(0, own_used - mine)
    complete = True
    others = {}
    for name, a in apps.items():
        if name == app:
            continue
        u = fetch_json(HUB + a["usage"], client)
        if u is None:
            complete = False  # 그 앱이 아직 기록이 없거나 읽기 실패 → 예비분은 쓰지 않는다
            continue
        used = int(u.get("days", {}).get(today, {}).get("requests", 0))
        others[name] = used
        reserve_used += max(0, used - int(a["guaranteed"]))
    reserve_left = max(0, reserve - reserve_used) if complete else 0
    left = max(0, mine - own_used) + reserve_left
    return left, {"mode": "budget", "guaranteed": mine, "used": own_used, "reserve_left": reserve_left,
                  "others": others, "complete": complete}


def describe(app: str, left: int, info: dict) -> str:
    return (f"AI 예산[{app}] 오늘 남은 {left}회 (내 몫 {info['guaranteed']} 중 {info['used']}회 사용, "
            f"예비분 {info['reserve_left']}회 가능, 기준 {info['mode']})")


if __name__ == "__main__":  # 점검용: python scripts/budget.py app-id 오늘사용량 보장량
    import sys

    a, used, g = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    left, info = allowance(a, used, g)
    print(json.dumps({"left": left, **info}, ensure_ascii=False, indent=1))
