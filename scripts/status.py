"""데이터 상태 파일(status.json): 화면의 '데이터 상태' 패널이 읽는다. AI 를 쓰지 않는다.

뉴스·주가·논문·주간 다이제스트 각 파이프라인의 마지막 갱신 시각과 AI 분류 대기 건수를 모은다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from common import OUT, read_json


def build_status(out_dir: Path = OUT) -> dict:
    news = read_json(out_dir / "news.json", {})
    prices = read_json(out_dir / "prices.json", {})
    digest = read_json(out_dir / "digest.json", {})
    papers = read_json(out_dir / "papers.json", {})
    usage = read_json(out_dir / "ai-usage.json", {})
    items = news.get("items", [])
    pending = sum(1 for x in items if not x.get("ai"))
    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "news": {"generated_at": news.get("generated_at"), "items": len(items), "pending": news.get("pending", pending),
                 "ai_ok_day": news.get("ai_ok_day"), "warnings": news.get("warnings", [])},
        "prices": {"generated_at": prices.get("generated_at"), "symbols": len(prices.get("quotes", {}))},
        "digest": {"generated_at": (digest.get("items") or [{}])[0].get("generated_at") if digest.get("items") else None},
        "papers": {"generated_at": papers.get("generated_at")},
        "ai": {"today": int((usage.get("days", {}).get(today) or {}).get("requests", 0)), "cap": usage.get("cap")},
    }


def write_status(out_dir: Path = OUT) -> None:
    out = build_status(out_dir)
    (out_dir / "status.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
