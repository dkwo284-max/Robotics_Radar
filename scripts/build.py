"""Robotics Radar 빌드: 큐레이션 데이터(data/*.json) + 자동 수집(web/data/news.json, prices.json) → web/data/dashboard.json

    python scripts/build.py           # 빌드
    python scripts/build.py --check   # 검증만 (경고가 있으면 실패)

표준 라이브러리만 쓴다. 점수·Tier·고객 매력도·자본효율·KPI·경보를 여기서 계산하고,
화면(web/index.html)은 계산된 값만 그린다.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone

from changes import diff, keep_baseline, state_of
import paper_calc
import patent_calc
from common import OUT, SRC, plausible, read_json, write_json

# 경쟁력 점수 축과 만점. 합계 100 → Tier
AXES = {"tech": 30, "scale": 30, "capital": 20, "execution": 20}
# 고객 매력도(부품사 관점): 양산 규모 30 + 조달 개방성 25 + 지정학 접근성 25 + 지불 능력 20
ATTR_AXES = {"open": 25, "geo": 25}
TIERS = [(70, 1), (50, 2), (0, 3)]
IPO_STAGES = ["비상장", "IPO 준비", "신청·심사", "공모·상장 진행", "상장", "상장사 사업부·자회사"]
USAGE_CAP = 2  # 허브와 공유하는 Gemini 하루 상한 (Phase 2 부터 사용)


def load(name: str) -> dict:
    return json.loads((SRC / name).read_text(encoding="utf-8"))


def tier_of(total: int) -> int:
    return next(t for floor, t in TIERS if total >= floor)


def fact_v(c: dict, key: str):
    f = c.get(key)
    return f.get("v") if isinstance(f, dict) else None


def score_company(c: dict, warnings: list[str]) -> dict:
    s = c["scores"]
    for axis, top in {**AXES, **ATTR_AXES}.items():
        v = s.get(axis, [0])[0]
        if not 0 <= v <= top:
            warnings.append(f"{c['id']}: {axis} 점수 {v} 가 0~{top} 범위를 벗어남")
    total = sum(s[a][0] for a in AXES)
    out = {"total": total, "tier": tier_of(total)}
    if c["group"] == "body":
        # 양산 규모(scale)와 지불 능력(capital)은 경쟁력 점수를 그대로 쓴다
        out["attract"] = s["scale"][0] + s["open"][0] + s["geo"][0] + s["capital"][0]
    else:
        out["attract"] = None  # 두뇌 레이어는 부품 구매 고객이 아님
    return out


def efficiency(c: dict) -> dict:
    """자본효율: 밸류 ÷ 누적 출하, 조달액 ÷ 누적 출하 (USD M → 대당 USD)."""
    units = fact_v(c, "cum_units")
    val = fact_v(c, "valuation")
    raised = fact_v(c, "funding_total")
    per = lambda m: round(m * 1e6 / units) if m and units else None  # noqa: E731
    return {"units": units, "val_per_unit": per(val), "raised_per_unit": per(raised)}


def bom_items(bom: dict) -> list[dict]:
    items = []
    for it in bom["items"]:
        asp = None if it.get("module") else round(bom["unit_bom_2026"] * it["share"] / it["qty"])
        items.append({**it, "asp": asp, "per_unit": round(bom["unit_bom_2026"] * it["share"])})
    return items


def months_back(as_of: str, ym: str) -> float:
    d0 = date.fromisoformat(as_of)
    y, m = int(ym[:4]), int(ym[5:7])
    return (d0.year - y) * 12 + (d0.month - m)


def kpis(companies: list[dict], market: dict) -> dict:
    as_of = market["as_of"]
    body = [c for c in companies if c["group"] == "body"]
    stat = {s["k"]: s for s in market["stats"]}
    top = max(body, key=lambda c: c["calc"]["attract"])
    non_cn = [c for c in body if c["scores"]["geo"][0] >= 20 and c["scores"]["open"][0] >= 15]
    raised_12m = sum(r["amount"] for c in companies for r in c.get("funding", [])
                     if r.get("amount") and months_back(as_of, r["date"]) < 12)
    pipeline = [c for c in companies if 1 <= c["listing"]["stage"] <= 3]
    ratios = [c["calc"]["val_per_unit"] for c in body if c["calc"]["val_per_unit"]]
    us = [c["calc"]["val_per_unit"] for c in body if c["calc"]["val_per_unit"] and c["country"] == "US"]
    cn = [c["calc"]["val_per_unit"] for c in body if c["calc"]["val_per_unit"] and c["country"] == "CN"]
    low_exec = [c for c in companies if c["scores"]["execution"][0] < 10]
    return {
        "parts": [
            {"label": "고객 매력도 1위", "value": top["name_ko"], "sub": f"{top['calc']['attract']}점", "id": top["id"]},
            {"label": "비중국 공급처 수요 고객", "value": f"{len(non_cn)}곳", "sub": "지정학 20+ · 개방성 15+"},
            {"label": "2026 글로벌 출하 전망", "value": f"{stat['fy2026_units']['v'] / 1e4:.1f}만 대", "sub": "SAG·Counterpoint 중간"},
            {"label": "중국 업체 출하 점유율", "value": f"{stat['china_share']['v'] * 100:.0f}%", "sub": "2026 상반기"},
        ],
        "invest": [
            {"label": "최근 12개월 공개 조달", "value": f"${raised_12m / 1000:.1f}B", "sub": f"{len(companies)}개사 합계"},
            {"label": "IPO 파이프라인", "value": f"{len(pipeline)}곳", "sub": "준비~공모 진행"},
            {"label": "밸류/누적 출하 (미국÷중국)", "value": f"{_median(us) / _median(cn):.0f}배" if us and cn else "-",
             "sub": "중앙값 비교" if ratios else ""},
            {"label": "실행 신뢰도 10점 미만", "value": f"{len(low_exec)}곳", "sub": "물량 보장 조항 필요"},
        ],
    }


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def validate(companies: list[dict], market: dict, strategy: dict, warnings: list[str]) -> None:
    ids = [c["id"] for c in companies]
    if len(ids) != len(set(ids)):
        warnings.append("회사 id 중복")
    known = set(ids)
    for ins in market["insights"]:
        for e in ins["evidence"]:
            if e not in known:
                warnings.append(f"인사이트 '{ins['title']}': 근거 id {e} 없음")
    for ev in market["events"]:
        for e in ev["ids"]:
            if e not in known:
                warnings.append(f"이벤트 '{ev['title']}': id {e} 없음")
    for sp in strategy["signposts"]:
        for e in sp["ids"]:
            if e not in known:
                warnings.append(f"신호 '{sp['trigger']}': id {e} 없음")
    apps = {a["id"] for a in strategy["applications"]["items"]}
    for cid, row in strategy["applications"]["matrix"].items():
        if cid not in known:
            warnings.append(f"용도 매트릭스: id {cid} 없음")
        for a, v in row.items():
            if a not in apps or not 0 <= v <= 3:
                warnings.append(f"용도 매트릭스 {cid}.{a}={v} 잘못됨")
    axes = {a["id"] for a in strategy["countries"]["axes"]}
    for c in strategy["countries"]["items"]:
        if set(c["scores"]) != axes or not all(0 <= v <= 10 for v in c["scores"].values()):
            warnings.append(f"국가 {c['id']} 점수 축·범위 잘못됨")
    share = sum(i["share"] for i in market["bom"]["items"])
    if not math.isclose(share, 1.0, abs_tol=0.005):
        warnings.append(f"BOM 비중 합계가 {share:.3f} (1.0 이어야 함)")
    for name in ("bear", "base", "bull"):
        sc = market["scenarios"][name]
        if len(sc["units"]) != len(market["scenarios"]["years"]) or len(sc["ex_china"]) != len(sc["units"]):
            warnings.append(f"시나리오 {name} 길이 불일치")


def snapshot(companies: list[dict]) -> dict:
    return {c["id"]: [c["calc"]["total"], c["calc"]["attract"]] for c in companies}


def score_moves(companies: list[dict], history: dict) -> dict:
    """현재 점수와 직전에 달랐던 스냅숏을 비교 → {id: {d_total, d_attract, tier_from}}."""
    cur = snapshot(companies)
    prev = next((s for s in reversed(history.get("snapshots", [])) if s["scores"] != cur), None)
    if not prev:
        return {}
    moves = {}
    for cid, (total, attract) in cur.items():
        old = prev["scores"].get(cid)
        if not old:
            continue
        d_total, d_attract = total - old[0], (attract or 0) - (old[1] or 0)
        if d_total or d_attract:
            moves[cid] = {"d_total": d_total, "d_attract": d_attract, "since": prev["date"],
                          "tier_from": tier_of(old[0]) if tier_of(old[0]) != tier_of(total) else None}
    return moves


def alerts(companies: list[dict], news: dict, prices: dict, moves: dict, as_of: str) -> list[dict]:
    """개요 맨 위 경보: 중요 소식(7일), 검증 대기, 주가 급변(1주 ±10%), 점수·Tier 변화."""
    names = {c["id"]: c["name_ko"] for c in companies}
    week = (date.fromisoformat(as_of) - timedelta(days=7)).isoformat()
    out = []
    key_news = [x for x in news.get("items", []) if x.get("importance", 1) >= 3 and x["date"] >= week]
    for x in key_news[:4]:  # 경보는 최근 핵심 소식 4건까지 — 나머지는 '오늘의 소식'에
        out.append({"level": "high", "kind": "news", "title": x.get("title_ko") or x["title"], "sub": x.get("summary_ko", ""),
                    "ids": x.get("companies", []), "url": x["url"], "date": x["date"]})
    pending = news["proposals"]
    if pending:
        cs = sorted({p["company"] for p in pending})
        out.append({"level": "mid", "kind": "proposal", "title": f"검증 대기 수치 {len(pending)}건",
                    "sub": "AI 가 기사에서 뽑은 값이 큐레이션 값과 다릅니다 — " + ", ".join(names.get(c, c) for c in cs[:5]),
                    "ids": cs[:5], "date": pending[0]["date"]})
    for cid, q in prices.get("quotes", {}).items():
        if q.get("chg_1w") is not None and abs(q["chg_1w"]) >= 10:
            out.append({"level": "mid", "kind": "price", "title": f"{names.get(cid, cid)} 주가 1주 {q['chg_1w']:+.1f}%",
                        "sub": f"{q['symbol']} {q.get('note', '')}".strip(), "ids": [cid], "date": q["date"]})
    for cid, m in moves.items():
        tier = f" · Tier {m['tier_from']}→{tier_of(next(c for c in companies if c['id'] == cid)['calc']['total'])}" if m["tier_from"] else ""
        out.append({"level": "high" if m["tier_from"] else "mid", "kind": "score",
                    "title": f"{names.get(cid, cid)} 경쟁력 {m['d_total']:+d}점{tier}", "sub": f"{m['since']} 대비", "ids": [cid], "date": as_of})
    order = {"high": 0, "mid": 1}
    out.sort(key=lambda a: a["date"], reverse=True)  # 최신 먼저, 그 안에서 중요도 순 (stable sort)
    return sorted(out, key=lambda a: order[a["level"]])[:12]


def news_block(news: dict, days: int = 45) -> list[dict]:
    if not news.get("items"):
        return []
    newest = max(x["date"] for x in news["items"])
    cutoff = (date.fromisoformat(newest) - timedelta(days=days)).isoformat()
    keep = ("id", "date", "title", "title_ko", "summary_ko", "source", "url", "companies", "type", "importance", "ai", "query",
            "audience", "layer", "signpost", "topic")
    return [{k: x.get(k) for k in keep} for x in news["items"] if x["date"] >= cutoff][:600]


RM_NEWS = {"production": {"production", "supply"}, "product": {"product"}, "deploy": {"deploy", "partner"},
           "ipo": {"ipo", "funding"}, "funding": {"funding", "ipo"}}


def roadmap_watch(companies: list[dict], news: list[dict], today: str) -> list[dict]:
    """계획·지연 로드맵 항목 중 최근 30일 관련 소식이 있는 것 → 상태를 확인해 볼 후보."""
    since = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    out = []
    for c in companies:
        for r in c.get("roadmap", []):
            if r["status"] == "done" or r["type"] not in RM_NEWS:
                continue
            hits = [x for x in news if x["date"] >= since and c["id"] in (x.get("companies") or []) and x.get("type") in RM_NEWS[r["type"]]]
            if hits:
                out.append({"company": c["id"], "title": r["title"], "when": r["when"], "status": r["status"], "type": r["type"],
                            "news": [{"id": x["id"], "title": x.get("title_ko") or x["title"], "url": x["url"], "date": x["date"]} for x in hits[:3]]})
    return out


def signpost_moves(strategy: dict, news: list[dict], today: str) -> dict:
    """신호별 최근 30일 관련 소식(AI 가 신호 id 로 짝지은 것)."""
    since = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    out = {}
    for sp in strategy["signposts"]:
        hits = [x for x in news if x.get("signpost") == sp["id"] and x["date"] >= since]
        if hits:
            out[sp["id"]] = {"count": len(hits), "news": [{"id": x["id"], "title": x.get("title_ko") or x["title"], "url": x["url"],
                                                          "date": x["date"], "importance": x.get("importance", 1)} for x in hits[:3]]}
    return out


def pref_state(pref: dict) -> dict:
    """큐레이션 특허 지형의 변화 감지용 요약 — {기업: {포트폴리오(기준별 값), 이슈 제목들}}."""
    out = {}
    for cid, c in pref.get("companies", {}).items():
        out[cid] = {"portfolio": {p["basis"]: p["v"] for p in c.get("portfolio", [])}, "notable": [n["title"] for n in c.get("notable", [])]}
    return out


def change_log(companies: list[dict], strategy: dict, specs: dict, today: str, patents: dict | None = None,
               layer_labels: dict | None = None, pref: dict | None = None, papers: dict | None = None,
               paper_labels: dict | None = None) -> tuple[dict, list[dict], list[dict]]:
    """(현재 상태, 오늘 새로 생긴 변화, 화면용 변화 목록 최근 120일)."""
    cur = state_of(companies, strategy, specs, patents, pref, papers)
    prev = read_json(SRC / "state.json", None)
    ctx = {"names": {c["id"]: c["name_ko"] for c in companies}, "stages": IPO_STAGES,
           "signposts": {s["id"]: s["trigger"] for s in strategy["signposts"]},
           "models": {m["id"]: (m["model"], m["company"]) for m in specs["models"]},
           "layers": layer_labels or {},
           "paper_layers": paper_labels or {},
           "spec_labels": {**{f["id"]: f["label"] for f in specs["fields"]}, "actuator": "구동 방식"}}
    new = diff(prev, cur, ctx, today)
    log_items = read_json(SRC / "changes.json", {"items": []})["items"]
    cutoff = (date.fromisoformat(today) - timedelta(days=120)).isoformat()
    return cur, new, [x for x in new + log_items if x["date"] >= cutoff]


def build(history: dict | None = None) -> tuple[dict, list[str]]:
    raw = load("companies.json")
    market = load("market.json")
    strategy = load("strategy.json")
    specs = load("specs.json")
    pcfg = load("patents_cfg.json")
    pref = load("patents_ref.json")
    pcfg2 = load("papers_cfg.json")
    papers_blk = paper_calc.block(pcfg2, read_json(OUT / "papers.json", {}))
    pblock = patent_calc.block(pcfg, read_json(OUT / "patents.json", {}), market["bom"]["items"])
    news = read_json(OUT / "news.json", {})
    prices = read_json(OUT / "prices.json", {})
    # 검증 대기: 큐레이션 값이 이미 반영됐거나 단위 착오로 보이는 제안은 뺀다
    by_id = {c["id"]: c for c in raw["companies"]}
    news["proposals"] = [{**p, "curated": fact_v(by_id[p["company"]], p["field"])} for p in news.get("proposals", [])
                         if p["company"] in by_id and plausible(p["field"], fact_v(by_id[p["company"]], p["field"]), p["proposed"])]
    history = history if history is not None else read_json(SRC / "history.json", {"snapshots": []})
    warnings: list[str] = []
    companies = raw["companies"]
    for c in companies:
        c["calc"] = {**score_company(c, warnings), **efficiency(c)}
    validate(companies, market, strategy, warnings)
    known = {c["id"] for c in companies}
    for m in specs["models"]:
        if m["company"] not in known or m["actuator"] not in specs["actuators"]:
            warnings.append(f"스펙 {m['id']}: 기업 id 또는 구동 방식 잘못됨")
    layer_ids = {l["id"] for l in pcfg["layers"]}
    for a in pcfg["applicants"]:
        if a.get("company") and a["company"] not in known:
            warnings.append(f"특허 설정: 기업 id {a['company']} 없음")
        for lid in a.get("only", []):
            if lid not in layer_ids:
                warnings.append(f"특허 설정 {a['id']}: 층 {lid} 없음")
    for cid, c in pref.get("companies", {}).items():
        if cid not in known:
            warnings.append(f"특허 지형: 기업 id {cid} 없음")
        for n in c.get("notable", []):
            if n.get("layer") and n["layer"] not in layer_ids:
                warnings.append(f"특허 지형 {cid}: 층 {n['layer']} 없음")
    for it in pref.get("sector", {}).get("items", []):
        if it.get("company") and it["company"] not in known:
            warnings.append(f"특허 지형 sector: 기업 id {it['company']} 없음")
    for l in pcfg2["layers"]:
        for part in l.get("parts", []):
            if part not in {i["id"] for i in market["bom"]["items"]}:
                warnings.append(f"논문 층 {l['id']}: BOM 품목 {part} 없음")
    bom_ids = {i["id"] for i in market["bom"]["items"]}
    for l in pcfg["layers"]:
        for part in l.get("parts", []):
            if part not in bom_ids:
                warnings.append(f"특허 층 {l['id']}: BOM 품목 {part} 없음")
    if len({s.get("id") for s in strategy["signposts"]}) != len(strategy["signposts"]) or not all(s.get("id") for s in strategy["signposts"]):
        warnings.append("신호 id 가 비었거나 중복")
    moves = score_moves(companies, history)
    for c in companies:
        c["calc"]["move"] = moves.get(c["id"])
    # 경쟁력 내림차순, 같으면 고객 매력도
    companies.sort(key=lambda c: (-c["calc"]["total"], -(c["calc"]["attract"] or 0)))
    events = sorted(market["events"], key=lambda e: e["date"], reverse=True)
    k = kpis(companies, market)
    today = datetime.now(timezone.utc).date().isoformat()
    state, new_changes, changes = change_log(companies, strategy, specs, today, patent_calc.state(pblock),
                                             {l["id"]: l["label"] for l in pcfg["layers"]}, pref_state(pref),
                                             paper_calc.state(papers_blk), {l["id"]: l["label"] for l in pcfg2["layers"]})
    nb = news_block(news)
    digest = read_json(OUT / "digest.json", {}).get("items", [])
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M+00:00"),
        "as_of": raw["as_of"],
        "axes": {**AXES, **ATTR_AXES},
        "ipo_stages": IPO_STAGES,
        "companies": companies,
        "kpis": k,
        "insights": market["insights"],
        "events": events,
        "policies": sorted(market["policies"], key=lambda p: p["date"], reverse=True),
        "stats": market["stats"],
        "share_h1_2026": market["share_h1_2026"],
        "scenarios": market["scenarios"],
        "bom": {**{k: v for k, v in market["bom"].items() if k != "items"}, "items": bom_items(market["bom"])},
        "news": nb,
        "coverage": {"news_from": min((x["date"] for x in nb), default=None), "news_to": max((x["date"] for x in nb), default=None),
                     "news_covered_from": news.get("covered_from"),
                     "tracking_since": ((history.get("snapshots") or [{}])[0] or {}).get("date")},
        "changes": changes,
        "roadmap_watch": roadmap_watch(companies, nb, today),
        "signpost_moves": signpost_moves(strategy, nb, today),
        "digest": digest[0] if digest else None,
        "specs": specs,
        "patents": pblock,
        "patent_hub": patent_calc.hub(pcfg),
        "patent_ref": pref,
        "papers": papers_blk,
        "news_meta": {"generated_at": news.get("generated_at"), "ai": news.get("ai"), "warnings": news.get("warnings", [])},
        "proposals": news.get("proposals", []),
        "quotes": prices.get("quotes", {}),
        "alerts": alerts(companies, news, prices, moves, today),
        "strategy": strategy,
        "warnings": warnings,
        "_state": state,
        "_new_changes": new_changes,
    }
    return out, warnings


def record_history(companies: list[dict], today: str) -> None:
    """점수가 바뀐 날만 스냅숏을 남긴다(점수 변화·Tier 이동 경보의 기준)."""
    path = SRC / "history.json"
    hist = read_json(path, {"snapshots": []})
    cur = snapshot(companies)
    if not hist["snapshots"] or hist["snapshots"][-1]["scores"] != cur:
        hist["snapshots"] = (hist["snapshots"] + [{"date": today, "scores": cur}])[-60:]
        write_json(path, hist, indent=0)


def write_usage(today: str) -> None:
    """허브가 읽는 AI 사용량 장부. Phase 1 은 AI 를 쓰지 않으므로 상한만 기록한다."""
    path = OUT / "ai-usage.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {"days": {}}
    data.update(app="robotics-radar", provider="gemini", cap=USAGE_CAP, updated=today)
    data.setdefault("days", {})
    cutoff = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    data["days"] = {k: v for k, v in sorted(data["days"].items()) if k >= cutoff}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    out, warnings = build()
    for w in warnings:
        print("경고:", w, file=sys.stderr)
    if args.check:
        return 1 if warnings else 0
    today = datetime.now(timezone.utc).date().isoformat()
    state, new = out.pop("_state"), out.pop("_new_changes")
    write_json(OUT / "dashboard.json", out)
    # 변화 로그: 오늘 생긴 변화만 덧붙이고 상태를 갱신 (1년 보관)
    log_items = read_json(SRC / "changes.json", {"items": []})["items"]
    if new or not (SRC / "changes.json").exists():
        cutoff = (date.fromisoformat(today) - timedelta(days=365)).isoformat()
        write_json(SRC / "changes.json", {"items": [x for x in new + log_items if x["date"] >= cutoff]}, indent=0)
    prev_state = read_json(SRC / "state.json", None)
    keep = keep_baseline(prev_state, state, new)
    if keep != prev_state:  # 처음이거나 변화가 있거나 특허 기준값이 새로 생겼을 때
        write_json(SRC / "state.json", keep)
    write_usage(today)
    record_history(out["companies"], today)
    tiers = {t: sum(1 for c in out["companies"] if c["calc"]["tier"] == t) for t in (1, 2, 3)}
    print(f"dashboard.json: {len(out['companies'])}개사, Tier {tiers}, 새 변화 {len(new)}, 경고 {len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
