"""논문 신호(arXiv API, 키 불필요): 기술 층 키워드별 로봇(cs.RO) 논문 수 — 월별 24개월 시계열.

- arXiv 약관: 설명 메타데이터는 CC0, 요청은 3초에 1회·연결 1개. 건수만 세므로 응답이 작다(max_results=1).
- 달(月) 단위로 세어 쌓는다: 끝난 지 8일이 지난 달은 확정(다시 세지 않음), 최근 달만 6일마다 갱신.
  처음에는 층 11개 × 24개월 ≈ 264회(약 15분), 그다음부터는 주 1회 20회 안팎.
- 최근 12개월(A) vs 직전 12개월(B)은 이 월별 값을 합쳐 계산한다(제출일 기준이라 합이 정확하다).
- 논문은 특허 출원보다 앞서는 선행 신호일 뿐 산업 동향과 같지 않다. 화면에도 '논문 신호'로 표시한다.

    python scripts/papers.py            # 필요한 달만 갱신
    python scripts/papers.py --force    # 전부 다시 센다
"""
from __future__ import annotations

import argparse
import calendar
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from common import OUT, SRC, log, read_json, write_json

API = "https://export.arxiv.org/api/query"
UA = "RoboticsRadar/1.0 (personal dashboard; respects arXiv API terms of use)"
TOTAL_RE = re.compile(r"<opensearch:totalResults[^>]*>\s*(\d+)\s*<")
SETTLE_DAYS = 8  # 달이 끝난 뒤 이만큼 지나면 확정(늦게 올라오는 제출 반영)


class PapersError(RuntimeError):
    pass


def month_list(today: date, n: int = 24) -> list[str]:
    """오늘 기준 '끝난 달' n개(오래된 순) — 예: 오늘이 2026-10-29 이면 마지막은 2026-09."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    return out[::-1]


def month_range(ym: str) -> tuple[date, date]:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def is_final(cell: list | None, ym: str) -> bool:
    """cell = [건수, 센 날짜]. 달이 끝난 지 SETTLE_DAYS 가 지난 뒤에 센 값이면 확정."""
    try:
        return date.fromisoformat(cell[1]) >= month_range(ym)[1] + timedelta(days=SETTLE_DAYS)
    except (TypeError, ValueError, IndexError):
        return False


class Arxiv:
    def __init__(self, client: httpx.Client | None = None, pause: float = 3.5, sleep=time.sleep):
        self.client = client or httpx.Client(timeout=60, headers={"User-Agent": UA})
        self.pause, self.sleep = pause, sleep
        self.requests = 0
        self._last = 0.0

    def total(self, expr: str, start: date, end: date) -> int:
        q = f"{expr} AND submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]"
        for attempt in range(4):
            wait = self.pause - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            r = self.client.get(API, params={"search_query": q, "max_results": 1})
            if r.status_code in (429, 503):  # 혼잡 — 약관대로 천천히 재시도
                self.sleep(10 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise PapersError(f"HTTP {r.status_code}: {r.text[:120]}")
            m = TOTAL_RE.search(r.text)
            if not m:
                raise PapersError("응답에 totalResults 가 없습니다")
            return int(m.group(1))
        raise PapersError("arXiv 가 혼잡해 중단")


def expr_of(cfg: dict, layer: dict) -> str:
    return f"{cfg['base']} AND {layer['q']}" if layer.get("q") else cfg["base"]


def age_days(stamp: str | None, today: date) -> int:
    try:
        return (today - date.fromisoformat(stamp)).days
    except (TypeError, ValueError):
        return 10_000


def collect(cfg: dict, data: dict, ax: Arxiv, today: date, force: bool = False, on_layer_done=None) -> dict:
    """data["months"][층][YYYY-MM] = [건수, 센 날짜] 를 채운다. 확정된 달은 건너뛰고 실패하면 지금까지 것을 보존한다."""
    months = month_list(today, int(cfg.get("months", 24)))
    data["month_list"] = months  # 중간 저장본도 읽을 수 있게 먼저 기록
    data.pop("layers", None)  # 이전(A/B 2기간) 형식은 버린다
    rows = data.setdefault("months", {})
    ttl = int(cfg.get("ttl_days", 6))
    warnings: list[str] = []
    try:
        for layer in [cfg["total"], *cfg["layers"]]:
            row = rows.setdefault(layer["id"], {})
            for ym in months:
                cell = row.get(ym)
                if not force and cell and (is_final(cell, ym) or age_days(cell[1], today) < ttl):
                    continue
                start, end = month_range(ym)
                row[ym] = [ax.total(expr_of(cfg, layer), start, end), today.isoformat()]
            for ym in [k for k in row if k < months[0]]:  # 24개월보다 오래된 달은 버린다
                del row[ym]
            if on_layer_done:
                on_layer_done()
    except PapersError as e:  # 지금까지 센 것은 보존하고 중단
        warnings.append(f"논문 신호 갱신 중단: {e}"[:200])
        log.warning("papers stopped: %s", e)
    data["warnings"] = warnings
    data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    data["source"] = "arXiv API — cs.RO, 제출일 기준 · 설명 메타데이터 CC0"
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = read_json(SRC / "papers_cfg.json", {})
    if not cfg:
        log.warning("papers_cfg.json 이 없어 논문 신호를 건너뜁니다")
        return 0
    data = read_json(OUT / "papers.json", {})
    ax = Arxiv(pause=float(cfg.get("pause_seconds", 3.5)))
    save = lambda: write_json(OUT / "papers.json", data)  # noqa: E731  — 층마다 저장해 중간에 멈춰도 이어서 채운다
    try:
        collect(cfg, data, ax, datetime.now(timezone.utc).date(), args.force, on_layer_done=save)
    finally:
        if data.get("months"):
            save()
    done = sum(len(v) for v in data.get("months", {}).values())
    print(f"papers.json: 월별 값 {done}개, 요청 {ax.requests}회, 경고 {len(data.get('warnings', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
