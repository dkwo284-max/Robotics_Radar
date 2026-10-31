"""예비 예약 실행이 '이미 갱신됐는지' 판단한다 (워크플로 check 잡이 사용).

기준: '가장 최근에 지나간 19:10 UTC 정기 시각' 이후에 news.json(실제 수집 때만 갱신됨)이 갱신됐으면 신선하다 → 수집·배포 없이 끝낸다.
dashboard.json 은 코드 푸시로 빌드만 다시 해도 바뀌어서, 그 시각을 쓰면 수집이 안 된 날도 '갱신됨'으로 오해한다.
(예전에는 '오늘 19:10 UTC' 기준이라, 늦게 시작한 예비 실행이 UTC 자정을 넘기면 방금 갱신한 데이터를 오래된 것으로 오해하고 다시 수집했다.)

    python scripts/fresh.py      # GITHUB_OUTPUT 에 run=true|false 를 쓴다
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SLOT_HOUR, SLOT_MINUTE = 19, 10  # 정기 실행 시각 (UTC) — 워크플로의 첫 cron 과 같아야 한다


def latest_slot(now: datetime) -> datetime:
    slot = now.astimezone(timezone.utc).replace(hour=SLOT_HOUR, minute=SLOT_MINUTE, second=0, microsecond=0)
    return slot if now >= slot else slot - timedelta(days=1)


def is_fresh(generated_at: str, now: datetime) -> bool:
    try:
        gen = datetime.fromisoformat(generated_at)
    except (TypeError, ValueError):
        return False
    if gen.tzinfo is None:
        gen = gen.replace(tzinfo=timezone.utc)
    return gen >= latest_slot(now)


def main() -> int:
    path = Path(__file__).resolve().parent.parent / "web" / "data" / "news.json"
    try:
        gen = json.loads(path.read_text(encoding="utf-8")).get("generated_at", "")
    except Exception:  # noqa: BLE001
        gen = ""
    fresh = is_fresh(gen, datetime.now(timezone.utc))
    print(f"generated_at={gen!r} fresh={fresh}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'false' if fresh else 'true'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
