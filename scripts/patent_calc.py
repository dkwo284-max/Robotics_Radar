"""특허 수집 결과(web/data/patents.json) → 화면용 블록: 히트맵 행, 산업 전체 기술 층 추이, 변화가 큰 곳, 부품별 출원인 지도, 최근 공개.

수집이 아직 없으면 ready=False 와 참고 수치(보도·분석사)만 내보낸다.
"""
from __future__ import annotations

MIN_MOVER = 8        # 변화가 큰 곳으로 보려면 최근 3년 건수가 이만큼은 있어야 함
MIN_CHANGE = 10      # 변화 로그에 남길 최소 건수 변화
CHANGE_RATIO = 0.25  # … 그리고 직전 값 대비 이 비율 이상


def pa_q(app: dict) -> str:
    """검색 링크용 출원인 검색식 — 예: pa="ubtech" 또는 (pa="xpeng" or pa="xiaopeng")."""
    terms = [f'pa="{p}"' for p in app.get("pa", [])]
    return terms[0] if len(terms) == 1 else "(" + " or ".join(terms) + ")" if terms else ""


def _cell(cells: dict, aid: str, lid: str) -> dict | None:
    c = cells.get(f"{aid}|{lid}")
    return c if c and c.get("a") is not None else None


def _pair(c: dict | None) -> dict | None:
    return {"a": c["a"], "b": c["b"]} if c else None


def block(cfg: dict, data: dict | None, bom_items: list[dict]) -> dict:
    layers = [{k: l[k] for k in ("id", "label", "note", "parts", "cpc")} for l in cfg["layers"]]
    base = {"ready": False, "layers": layers, "ref": cfg.get("ref", []), "ref_note": cfg.get("ref_note", "")}
    if not data or not data.get("cells"):
        return base
    cells, rec = data["cells"], data.get("applicants", {})
    rows, recent = [], []
    for app in cfg["applicants"]:
        if app["kind"] != "company":
            continue
        ls = {l["id"]: _pair(_cell(cells, app["id"], l["id"])) for l in cfg["layers"]}
        tot = _pair(_cell(cells, app["id"], "total"))
        if not tot and not any(ls.values()):
            continue
        r = rec.get(app["id"], {})
        rows.append({"id": app["company"], "name": app["name"], "home": app.get("home"), "q": pa_q(app), "total": tot,
                     "layers": {k: v for k, v in ls.items() if v}, "quality": r.get("quality"),
                     "recent": r.get("recent", []), "recent_total": r.get("recent_total")})
        recent += [{**it, "company": app["company"]} for it in r.get("recent", []) if it.get("title") or it.get("number")]
    recent.sort(key=lambda x: x.get("date", ""), reverse=True)

    industry = []
    tot_a = sum(r["total"]["a"] for r in rows if r["total"])
    tot_b = sum(r["total"]["b"] for r in rows if r["total"])
    for l in cfg["layers"]:
        a = sum(r["layers"][l["id"]]["a"] for r in rows if l["id"] in r["layers"])
        b = sum(r["layers"][l["id"]]["b"] for r in rows if l["id"] in r["layers"])
        industry.append({"id": l["id"], "a": a, "b": b, "share_a": round(a / tot_a, 4) if tot_a else None,
                         "share_b": round(b / tot_b, 4) if tot_b else None})
    movers = []
    for r in rows:
        for lid, p in r["layers"].items():
            if p["a"] >= MIN_MOVER and (p["b"] == 0 or p["a"] / p["b"] >= 1.3):
                movers.append({"company": r["id"], "layer": lid, "a": p["a"], "b": p["b"], "delta": p["a"] - p["b"]})
    movers.sort(key=lambda m: -m["delta"])

    by_part: dict[str, list[str]] = {}
    for l in cfg["layers"]:
        for part in l.get("parts", []):
            by_part.setdefault(part, []).append(l["id"])
    parts = {}
    for part, lids in by_part.items():
        ranked = []
        for app in cfg["applicants"]:
            ps = [_cell(cells, app["id"], lid) for lid in lids]
            ps = [p for p in ps if p]
            if ps:
                ranked.append({"id": app["id"], "name": app["name"], "kind": app["kind"], "home": app.get("home"), "company": app.get("company"), "q": pa_q(app),
                               "a": sum(p["a"] for p in ps), "b": sum(p["b"] for p in ps)})
        ranked = [x for x in ranked if x["a"] or x["b"]]
        ranked.sort(key=lambda x: -x["a"])
        parts[part] = {"layers": lids, "top": ranked[:7], "kr": [x for x in ranked if x["home"] == "KR"][:4]}
    st = data.get("status", {})
    u = data.get("usage") or {}
    mb = lambda k: round(u.get(k, 0) / 1e6, 1)  # noqa: E731
    quota = {"week_mb": mb("bytes"), "week_cap_mb": round(mb("week_cap")), "day_mb": mb("day_bytes"), "day_cap_mb": round(mb("day_cap")),
             "free_mb": round(mb("free_week")), "week": u.get("week")} if u else None
    return {**base, "ready": True, "quota": quota, "generated_at": data.get("generated_at"), "windows": data.get("windows"), "source": data.get("source"),
            "coverage": {"cells": st.get("cells", 0), "expected": st.get("expected", 0), "pending": st.get("pending", 0)},
            "warnings": data.get("warnings", []), "rows": rows, "industry": industry, "total": {"a": tot_a, "b": tot_b},
            "movers": movers[:8], "parts": parts, "recent": recent[:60]}


def hub(cfg: dict) -> dict:
    """조회 허브: 수집 데이터 없이 설정만으로 만든다 — 기업 × 기술 층 검색 링크의 재료(출원인 검색식·층별 CPC)."""
    layers = [{k: l[k] for k in ("id", "label", "note", "parts", "cpc")} for l in cfg["layers"]]
    rows = [{"id": a["id"], "company": a.get("company"), "name": a["name"], "kind": a["kind"], "home": a.get("home"), "scope": a.get("scope"),
             "q": pa_q(a), "assignee": (a.get("pa") or [""])[0], "only": a.get("only")} for a in cfg["applicants"]]
    return {"layers": layers, "total": cfg["total"], "rows": rows}


def state(blk: dict) -> dict:
    """변화 로그용: {기업 id: {층: 최근 3년 건수}} — 수집 전이면 빈 dict."""
    if not blk.get("ready"):
        return {}
    return {r["id"]: {lid: p["a"] for lid, p in r["layers"].items()} for r in blk["rows"]}


def changed(prev: int, cur: int) -> bool:
    delta = abs(cur - prev)
    return delta >= MIN_CHANGE and (prev == 0 or delta / prev >= CHANGE_RATIO)
