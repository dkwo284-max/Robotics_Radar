"""관련 상장사 주가: Yahoo Finance 차트 API(키 불필요). 날짜별 종가(hist)를 쌓아 두고, 이미 충분히 쌓였으면 최근 10일만 받아 합친다.

- 처음(또는 이력이 60일 미만)에는 3개월을 한 번 받고, 그다음부터는 10일 구간만 받아 날짜별로 덮어쓴다 — 매일 3개월을 다시 받지 않는다.
- 1주·1개월 변화와 추이선은 쌓인 hist 로 계산한다. 실패하면 지난 값을 유지한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from common import log

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
FULL = 60   # 이만큼(거래일) 쌓였으면 최근 구간만 받는다
KEEP = 130  # 약 6개월치 거래일만 보관


def change(closes: list[float], back: int) -> float | None:
    if len(closes) <= back or not closes[-1 - back]:
        return None
    return round((closes[-1] / closes[-1 - back] - 1) * 100, 1)


def series(js: dict) -> tuple[list[tuple[str, float]], str | None]:
    """응답 → ([(날짜, 종가)…], 통화). 종가가 없는 날은 뺀다."""
    res = (js.get("chart") or {}).get("result") or []
    if not res:
        return [], None
    r = res[0]
    ts = r.get("timestamp") or []
    closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    pairs = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), round(c, 2)) for t, c in zip(ts, closes) if c is not None]
    return pairs, (r.get("meta") or {}).get("currency")


def quote_of(pairs: list[tuple[str, float]], currency: str | None) -> dict | None:
    if not pairs:
        return None
    closes = [c for _, c in pairs]
    return {"currency": currency, "last": closes[-1], "date": pairs[-1][0],
            "chg_1w": change(closes, 5), "chg_1m": change(closes, 21), "spark": closes[-60:]}


def parse(js: dict) -> dict | None:
    pairs, cur = series(js)
    return quote_of(pairs, cur)


def update_prices(cfg: dict, old: dict, client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; RoboticsRadar/1.0)"})
    out = dict(old.get("quotes", {}))
    hist = {cid: dict(v) for cid, v in old.get("hist", {}).items()}
    warnings = []
    try:
        for cid, sym in cfg.get("tickers", {}).items():
            have = hist.get(cid, {})
            rng = "10d" if len(have) >= FULL else "3mo"  # 이미 쌓인 종목은 최근 구간만
            try:
                r = client.get(CHART.format(sym=sym, rng=rng))
                r.raise_for_status()
                pairs, cur = series(r.json())
                if not pairs:
                    continue
                have.update(dict(pairs))  # 같은 날짜는 최신 값으로 덮어씀(장중 값 보정)
                have = dict(sorted(have.items())[-KEEP:])
                hist[cid] = have
                q = quote_of(sorted(have.items()), cur or out.get(cid, {}).get("currency"))
                out[cid] = {"symbol": sym, "note": cfg.get("ticker_notes", {}).get(cid, ""), **q}
            except Exception as e:  # noqa: BLE001  — 실패하면 지난 값을 유지
                log.warning("price %s failed: %s", sym, e)
                warnings.append(f"{sym} 주가를 받지 못해 지난 값을 표시합니다.")
    finally:
        if own:
            client.close()
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "quotes": out, "hist": hist, "warnings": warnings}
