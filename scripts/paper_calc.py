"""논문 신호(web/data/papers.json) → 화면용 블록: 층별 비중·증가 배수, 표본 작음 표시, 부품 연결, 변화 감지용 요약."""
from __future__ import annotations

from urllib.parse import quote_plus

MIN_CHANGE = 20      # 변화 로그에 남길 최소 편수 변화
CHANGE_RATIO = 0.25  # … 그리고 직전 값 대비 이 비율 이상


def arxiv_link(layer: dict) -> str:
    return f"https://arxiv.org/search/?query={quote_plus(layer['link'])}&searchtype=abstract&order=-announced_date_first"


def block(cfg: dict, data: dict | None) -> dict:
    """월별 값(data['months'])을 최근 12개월(A)·직전 12개월(B)로 합치고, 층별 월별 시계열(series)을 함께 낸다."""
    layers = [{"id": l["id"], "label": l["label"], "note": l["note"], "parts": l.get("parts", []), "link": arxiv_link(l)} for l in cfg["layers"]]
    base = {"ready": False, "layers": layers}
    months = (data or {}).get("month_list") or []
    cells = (data or {}).get("months") or {}
    n = int(cfg.get("months", 24))
    half = n // 2

    def series(lid: str):
        row = cells.get(lid)
        if not row or len(months) < n or any(m not in row for m in months):
            return None  # 아직 다 못 센 층은 화면에 올리지 않는다
        return [row[m][0] for m in months]

    ts = series("total")
    if not ts or not sum(ts[half:]):
        return base
    ta, tb = sum(ts[half:]), sum(ts[:half])
    min_sample = int(cfg.get("min_sample", 30))
    rows = []
    for l in cfg["layers"]:
        sr = series(l["id"])
        if sr is None:
            continue
        a, b = sum(sr[half:]), sum(sr[:half])
        rows.append({"id": l["id"], "label": l["label"], "note": l["note"], "parts": l.get("parts", []), "link": arxiv_link(l), "a": a, "b": b,
                     "share_a": round(a / ta, 5), "share_b": round(b / tb, 5) if tb else None,
                     "growth": round(a / b, 2) if b else None, "small": a < min_sample, "series": sr})
    hum = next((r for r in rows if r["id"] == "humanoid"), None)
    return {**base, "ready": True, "generated_at": data.get("generated_at"), "source": data.get("source"), "months": months,
            "windows": {"a": [months[half], months[-1]], "b": [months[0], months[half - 1]]},
            "total": {"a": ta, "b": tb, "growth": round(ta / tb, 2) if tb else None, "series": ts},
            "baseline_growth": hum["growth"] if hum else None, "rows": rows, "warnings": data.get("warnings", [])}


def state(blk: dict) -> dict:
    """변화 로그용: {층: 최근 12개월 편수} — 수집 전이면 빈 dict."""
    return {r["id"]: r["a"] for r in blk.get("rows", [])} if blk.get("ready") else {}


def changed(prev: int, cur: int) -> bool:
    delta = abs(cur - prev)
    return delta >= MIN_CHANGE and (prev == 0 or delta / prev >= CHANGE_RATIO)
