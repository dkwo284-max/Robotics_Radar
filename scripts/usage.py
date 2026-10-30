"""AI 사용량 장부: 날짜별 Gemini 요청 수를 web/data/ai-usage.json 에 쌓는다.

- 같은 날(오클랜드 00시 기준) 여러 번 실행해도 합산된다. 상한 판단은 budget.py(공용 예산)가 이 장부를 읽어서 한다.
- My Hub(https://dkwo284-max.github.io/)가 이 파일을 읽어 앱별 오늘 사용량을 보여준다.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

USAGE_FILE = "ai-usage.json"


def load(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / USAGE_FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def used_today(data_dir: Path, today: str) -> int:
    return int(load(data_dir).get("days", {}).get(today, {}).get("requests", 0))


def record(data_dir: Path, today: str, requests: int, cfg: dict, app: str = "robotics-radar", keep_days: int = 30) -> dict:
    data = load(data_dir)
    days = data.get("days", {})
    d = days.setdefault(today, {"requests": 0, "runs": 0})
    d["requests"] += int(requests)
    d["runs"] += 1
    cutoff = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    days = {k: v for k, v in sorted(days.items()) if k >= cutoff}
    out = {"app": app, "provider": cfg.get("llm", {}).get("provider", "gemini"),
           "cap": int(cfg.get("llm", {}).get("guaranteed", 3)), "updated": today, "days": days}
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / USAGE_FILE).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
