"""매일 자동 수집: 뉴스(+Gemini 분류) · 주가 → web/data/news.json, prices.json, ai-usage.json. 그다음 build.py 로 화면 데이터.

    python scripts/update.py              # 뉴스 + 주가 + 빌드
    python scripts/update.py --no-news    # 주가 + 빌드
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

import build
import usage
from common import OUT, SRC, load_config, log, read_json, write_json
from llm import Gemini
from news import update_news
from prices import update_prices


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-news", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()
    companies = read_json(SRC / "companies.json", {})["companies"]
    today = datetime.now(timezone.utc).date().isoformat()

    if not args.no_news:
        llm = Gemini(cfg)
        over, used, cap = usage.over_cap(OUT, today, cfg)
        if over:
            log.warning("AI 하루 상한 도달(%d/%d) — 오늘은 분류 없이 제목만", used, cap)
            llm.key = ""
        old = read_json(OUT / "news.json", {})
        news = update_news(cfg, old, companies, llm)
        if over:
            news["warnings"].append(f"오늘 AI 상한({cap}회)에 도달해 새 기사는 분류 없이 제목만 표시합니다.")
        write_json(OUT / "news.json", news)
        usage.record(OUT, today, llm.requests, cfg)  # 0회라도 실행 기록 → 허브 카드에 표시

    write_json(OUT / "prices.json", update_prices(cfg, read_json(OUT / "prices.json", {})))
    return build.main([])


if __name__ == "__main__":
    sys.exit(main())
