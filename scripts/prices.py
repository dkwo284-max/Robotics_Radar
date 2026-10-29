"""관련 상장사 주가: Yahoo Finance 차트 API(키 불필요)에서 3개월 일봉 종가를 받아 1주·1개월 변화와 추이를 만든다."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from common import log

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d"


def change(closes: list[float], back: int) -> float | None:
    if len(closes) <= back or not closes[-1 - back]:
        return None
    return round((closes[-1] / closes[-1 - back] - 1) * 100, 1)


def parse(js: dict) -> dict | None:
    res = (js.get("chart") or {}).get("result") or []
    if not res:
        return None
    r = res[0]
    ts = r.get("timestamp") or []
    closes_raw = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    pairs = [(t, c) for t, c in zip(ts, closes_raw) if c is not None]
    if not pairs:
        return None
    closes = [round(c, 2) for _, c in pairs]
    return {"currency": r.get("meta", {}).get("currency"), "last": closes[-1],
            "date": datetime.fromtimestamp(pairs[-1][0], timezone.utc).date().isoformat(),
            "chg_1w": change(closes, 5), "chg_1m": change(closes, 21), "spark": closes[-60:]}


def update_prices(cfg: dict, old: dict, client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; RoboticsRadar/1.0)"})
    out = dict(old.get("quotes", {}))
    warnings = []
    try:
        for cid, sym in cfg.get("tickers", {}).items():
            try:
                r = client.get(CHART.format(sym=sym))
                r.raise_for_status()
                q = parse(r.json())
                if q:
                    out[cid] = {"symbol": sym, "note": cfg.get("ticker_notes", {}).get(cid, ""), **q}
            except Exception as e:  # noqa: BLE001  — 실패하면 지난 값을 유지
                log.warning("price %s failed: %s", sym, e)
                warnings.append(f"{sym} 주가를 받지 못해 지난 값을 표시합니다.")
    finally:
        if own:
            client.close()
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "quotes": out, "warnings": warnings}
