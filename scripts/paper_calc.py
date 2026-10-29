"""논문 신호(web/data/papers.json) → 화면용 블록: 층별 비중·증가 배수, 표본 작음 표시, 부품 연결, 변화 감지용 요약."""
from __future__ import annotations

from urllib.parse import quote_plus

MIN_CHANGE = 20      # 변화 로그에 남길 최소 편수 변화
CHANGE_RATIO = 0.25  # … 그리고 직전 값 대비 이 비율 이상


def arxiv_link(layer: dict) -> str:
    return f"https://arxiv.org/search/?query={quote_plus(layer['link'])}&searchtype=abstract&order=-announced_date_first"


def block(cfg: dict, data: dict | None) -> dict:
    layers = [{"id": l["id"], "label": l["label"], "note": l["note"], "parts": l.get("parts", []), "link": arxiv_link(l)} for l in cfg["layers"]]
    base = {"ready": False, "layers": layers}
    cells = (data or {}).get("layers") or {}
    tot = cells.get("total")
    if not tot or not tot.get("a"):
        return base
    min_sample = int(cfg.get("min_sample", 30))
    rows = []
    for l in cfg["layers"]:
        c = cells.get(l["id"])
        if not c:
            continue
        a, b = c["a"], c["b"]
        rows.append({"id": l["id"], "label": l["label"], "note": l["note"], "parts": l.get("parts", []), "link": arxiv_link(l), "a": a, "b": b,
                     "share_a": round(a / tot["a"], 5), "share_b": round(b / tot["b"], 5) if tot.get("b") else None,
                     "growth": round(a / b, 2) if b else None, "small": a < min_sample})
    hum = next((r for r in rows if r["id"] == "humanoid"), None)
    return {**base, "ready": True, "generated_at": data.get("generated_at"), "windows": data.get("windows"), "source": data.get("source"),
            "total": {"a": tot["a"], "b": tot["b"], "growth": round(tot["a"] / tot["b"], 2) if tot.get("b") else None},
            "baseline_growth": hum["growth"] if hum else None, "rows": rows, "warnings": data.get("warnings", [])}


def state(blk: dict) -> dict:
    """변화 로그용: {층: 최근 12개월 편수} — 수집 전이면 빈 dict."""
    return {r["id"]: r["a"] for r in blk.get("rows", [])} if blk.get("ready") else {}


def changed(prev: int, cur: int) -> bool:
    delta = abs(cur - prev)
    return delta >= MIN_CHANGE and (prev == 0 or delta / prev >= CHANGE_RATIO)
