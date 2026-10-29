"""논문 신호(arXiv API, 키 불필요): 기술 층 키워드별 로봇(cs.RO) 논문 수 — 최근 12개월 vs 직전 12개월.

- arXiv 약관: 설명 메타데이터는 CC0, 요청은 3초에 1회·연결 1개. 건수만 세므로 응답이 작다(max_results=1).
- 결과: web/data/papers.json (층별 수집일을 남겨 6일 지난 것만 새로 센다 — 주 1회 약 20회 요청).
- 논문은 특허 출원보다 앞서는 선행 신호일 뿐 산업 동향과 같지 않다. 화면에도 '논문 신호'로 표시한다.

    python scripts/papers.py            # 오래된 층만 갱신
    python scripts/papers.py --force    # 전부 다시 센다
"""
from __future__ import annotations

import argparse
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


class PapersError(RuntimeError):
    pass


def shift_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # 2/29
        return d.replace(year=d.year - n, day=28)


def periods(today: date) -> dict:
    a_start = shift_years(today, 1) + timedelta(days=1)
    b_end = a_start - timedelta(days=1)
    return {"a": (a_start, today), "b": (shift_years(b_end, 1) + timedelta(days=1), b_end)}


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


def collect(cfg: dict, data: dict, ax: Arxiv, today: date, force: bool = False) -> dict:
    per = periods(today)
    data.setdefault("layers", {})
    warnings: list[str] = []
    ttl = int(cfg.get("ttl_days", 6))
    try:
        for layer in [cfg["total"], *cfg["layers"]]:
            cell = data["layers"].get(layer["id"])
            if not force and cell and age_days(cell.get("fetched"), today) < ttl:
                continue
            a = ax.total(expr_of(cfg, layer), *per["a"])
            b = ax.total(expr_of(cfg, layer), *per["b"])
            data["layers"][layer["id"]] = {"a": a, "b": b, "fetched": today.isoformat()}
    except PapersError as e:  # 지금까지 센 것은 보존하고 중단
        warnings.append(f"논문 신호 갱신 중단: {e}"[:200])
        log.warning("papers stopped: %s", e)
    data["windows"] = {k: [v[0].isoformat(), v[1].isoformat()] for k, v in per.items()}
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
    try:
        collect(cfg, data, ax, datetime.now(timezone.utc).date(), args.force)
    finally:
        if data.get("layers"):
            write_json(OUT / "papers.json", data)
    print(f"papers.json: 층 {len(data.get('layers', {}))}개, 요청 {ax.requests}회, 경고 {len(data.get('warnings', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
