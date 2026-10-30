"""매일 자동 수집: 뉴스(+Gemini 분류) · 주가 → 빌드(변화 로그) → 주 1회 다이제스트(+Gemini) → 다시 빌드.

    python scripts/update.py              # 뉴스 + 주가 + 빌드 (+ 다이제스트 날이면 다이제스트)
    python scripts/update.py --no-news    # 주가 + 빌드
    python scripts/update.py --patents probe   # EPO OPS 키·검색식 점검만 (수집·빌드 안 함)
    python scripts/update.py --patents skip    # EPO 특허 집계 건너뜀 (기본 auto: patents_cfg.json 의 enabled=true 이고 키가 있을 때만 수집)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

import budget
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
    today = datetime.now(timezone.utc).date().isoformat()  # 데이터 날짜(다이제스트 주기 등)는 그대로 UTC
    ai_day = budget.nz_today()  # AI 하루 = 오클랜드 00시 리셋 (세 앱 공통)
    lc = cfg["llm"]
    # 공용 예산(My Hub budget.json): 내 보장량 + 공유 예비분 중 오늘 남은 몫. 못 읽으면 내 보장량만 (scripts/budget.py)
    left, binfo = budget.allowance("robotics-radar", usage.used_today(OUT, ai_day), int(lc.get("guaranteed", 3)), ai_day)
    log.info("%s", budget.describe("robotics-radar", left, binfo))
    requests = 0

    if not args.no_news:
        llm = Gemini(cfg)
        over = left < int(lc.get("expected_per_run", 1))
        if over:
            log.warning("AI 예산 부족(오늘 남은 %d회) — 오늘은 분류 없이 제목만", left)
            llm.key = ""
        else:  # 오늘 남은 몫을 넘지 않도록 요청 수를 제한
            llm.max_requests = max(0, min(llm.max_requests, left))
        news = update_news(cfg, read_json(OUT / "news.json", {}), companies, llm, signposts=signposts)
        if over:
            news["warnings"].append("오늘 AI 몫을 모두 써서 새 기사는 분류 없이 제목만 표시합니다. 다음 실행에서 이어서 분류합니다.")
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
    if requests + 1 > left:
        dg_llm.key = ""
    old = read_json(OUT / "digest.json", {})
    if due(old, today, dg_llm.enabled):
        changes = read_json(SRC / "changes.json", {}).get("items", [])
        write_json(OUT / "digest.json", update_digest(old, changes, read_json(OUT / "news.json", {}).get("items", []), dg_llm, today))
        requests += dg_llm.requests
        rc = build.main([]) or rc

    if not args.no_news or requests:
        usage.record(OUT, ai_day, requests, cfg)  # 0회라도 실행 기록 → 허브 카드에 표시
        build.write_usage(today)
    return rc


if __name__ == "__main__":
    sys.exit(main())
