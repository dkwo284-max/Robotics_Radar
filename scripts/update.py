"""매일 자동 수집: 뉴스(+Gemini 분류) · 주가 → 빌드(변화 로그) → 주 1회 다이제스트(+Gemini) → 다시 빌드.

    python scripts/update.py              # 뉴스 + 주가 + 빌드 (+ 다이제스트 날이면 다이제스트)
    python scripts/update.py --no-news    # 주가 + 빌드
    python scripts/update.py --patents probe   # EPO OPS 키·검색식 점검만 (수집·빌드 안 함)
    python scripts/update.py --patents skip    # 특허 수집 건너뜀 (기본 auto: 키가 있으면 이어서 수집)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

import build
import papers
import patents
import usage
from common import OUT, SRC, load_config, log, read_json, write_json
from digest import due, update_digest
from llm import Gemini
from news import update_news
from prices import update_prices


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--patents", choices=["auto", "probe", "skip"], default="auto")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.patents == "probe":
        return patents.main(["--probe"])
    cfg = load_config()
    companies = read_json(SRC / "companies.json", {})["companies"]
    signposts = read_json(SRC / "strategy.json", {}).get("signposts", [])
    today = datetime.now(timezone.utc).date().isoformat()
    cap = int(cfg["llm"].get("daily_cap", 2))
    requests = 0

    if not args.no_news:
        llm = Gemini(cfg)
        over, used, _ = usage.over_cap(OUT, today, cfg)
        if over:
            log.warning("AI 하루 상한 도달(%d/%d) — 오늘은 분류 없이 제목만", used, cap)
            llm.key = ""
        news = update_news(cfg, read_json(OUT / "news.json", {}), companies, llm, signposts=signposts)
        if over:
            news["warnings"].append(f"오늘 AI 상한({cap}회)에 도달해 새 기사는 분류 없이 제목만 표시합니다.")
        write_json(OUT / "news.json", news)
        requests += llm.requests

    write_json(OUT / "prices.json", update_prices(cfg, read_json(OUT / "prices.json", {})))
    try:  # 논문 신호(arXiv, 키 불필요): 6일 지난 층만 갱신. 실패해도 나머지 파이프라인은 계속
        papers.main([])
    except Exception as e:  # noqa: BLE001
        log.warning("논문 신호 수집 실패(무시하고 계속): %s", e)
    if args.patents == "auto":  # 키가 없으면 건너뜀. 실패해도 나머지 파이프라인은 계속
        try:
            patents.main([])
        except Exception as e:  # noqa: BLE001
            log.warning("특허 수집 실패(무시하고 계속): %s", e)
    rc = build.main([])  # 변화 로그(data/changes.json)를 먼저 갱신

    # 주간 다이제스트: 오늘 남은 AI 한도가 있을 때만 Gemini, 아니면 규칙 기반
    dg_llm = Gemini(cfg)
    if usage.used_today(OUT, today) + requests + 1 > cap:
        dg_llm.key = ""
    old = read_json(OUT / "digest.json", {})
    if due(old, today, dg_llm.enabled):
        changes = read_json(SRC / "changes.json", {}).get("items", [])
        write_json(OUT / "digest.json", update_digest(old, changes, read_json(OUT / "news.json", {}).get("items", []), dg_llm, today))
        requests += dg_llm.requests
        rc = build.main([]) or rc

    if not args.no_news or requests:
        usage.record(OUT, today, requests, cfg)  # 0회라도 실행 기록 → 허브 카드에 표시
        build.write_usage(today)
    return rc


if __name__ == "__main__":
    sys.exit(main())
