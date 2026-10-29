"""변화 추적: 큐레이션 데이터의 '상태 스냅숏'을 만들고, 직전 스냅숏과 비교해 변화 목록을 만든다.

- 상태 = 기업별 점수·Tier·상장 단계·핵심 수치·로드맵 항목 상태 + 신호 상태 + 로봇 스펙
- 변화 항목마다 누가 봐야 하는지(roles: exec 경영진 / strategy 기술전략 / engineer 엔지니어)를 붙인다.
- data/state.json(마지막 상태)과 data/changes.json(누적 로그)은 build.py 가 저장한다.
"""
from __future__ import annotations

import copy

FACTS = {  # 필드 → (한국어, 단위, 보는 사람)
    "valuation": ("밸류", "USD_M", ["exec"]), "funding_total": ("누적 조달", "USD_M", ["exec"]),
    "revenue": ("매출", "USD_M", ["exec"]), "orders": ("수주", "USD_M", ["exec"]),
    "cum_units": ("누적 출하", "units", ["exec", "strategy"]), "capacity": ("생산능력", "units", ["exec", "strategy"]),
    "target_2026": ("2026 목표", "units", ["exec", "strategy"]), "price": ("판매가", "USD", ["exec", "strategy", "engineer"]),
}
STATUS = {"done": "완료", "planned": "계획", "delayed": "지연·변경"}
SIGN = {"watch": "주시", "progress": "진행 중", "happened": "발생"}
from patent_calc import changed as patent_changed  # noqa: E402

SPEC_LAYER = {"hand_dof": "hand", "runtime_h": "battery", "actuator": "actuator", "payload_kg": "actuator", "price_usd": "cost"}


def fmt(v, unit: str) -> str:
    if v is None:
        return "없음"
    if unit == "USD_M":
        return f"${v / 1000:.1f}B" if v >= 1000 else f"${v:,.0f}M"
    if unit == "units":
        return f"{v / 1e4:.1f}만 대" if v >= 1e4 else f"{v:,.0f}대"
    if unit == "USD":
        return f"${v:,.0f}"
    return f"{v}{unit}"


def rm_key(r: dict) -> str:
    return f"{r['type']}|{r['title']}"


def state_of(companies: list[dict], strategy: dict, specs: dict, patents: dict | None = None) -> dict:
    comp = {}
    for c in companies:
        calc = c["calc"]
        comp[c["id"]] = {
            "total": calc["total"], "attract": calc["attract"], "tier": calc["tier"], "stage": c["listing"]["stage"],
            "facts": {f: c[f].get("v") for f in FACTS if isinstance(c.get(f), dict)},
            "roadmap": {rm_key(r): [r["status"], r["when"]] for r in c.get("roadmap", [])},
        }
    return {
        "companies": comp,
        "signposts": {s["id"]: s["status"] for s in strategy.get("signposts", [])},
        "specs": {m["id"]: {k: m.get(k) for k in [f["id"] for f in specs.get("fields", [])] + ["actuator"]} for m in specs.get("models", [])},
        "patents": patents or {},
    }


def keep_baseline(prev: dict | None, cur: dict, new: list[dict]) -> dict:
    """저장할 상태. 특허 건수는 새로 생긴 칸이거나 변화로 기록된 칸만 기준값을 갱신한다 —
    작은 변화가 조금씩 쌓여 임계값을 한 번도 못 넘은 채 기준이 따라 움직이는 일을 막기 위해서."""
    out = copy.deepcopy(cur)
    old = (prev or {}).get("patents") or {}
    logged = {(c["company"], c["layer"]) for c in new if c.get("kind") == "patent"}
    for cid, layers in cur.get("patents", {}).items():
        for lid in layers:
            if lid in old.get(cid, {}) and (cid, lid) not in logged:
                out["patents"][cid][lid] = old[cid][lid]
    return out


def diff(prev: dict, cur: dict, ctx: dict, today: str) -> list[dict]:
    """ctx: names(기업 id→이름), stages(상장 단계 이름), signposts(id→trigger), models(id→(모델명, 기업 id)), spec_labels."""
    if not prev:
        return []
    out: list[dict] = []
    add = lambda **e: out.append({"date": today, **e})  # noqa: E731
    names = ctx["names"]
    for cid, c in cur["companies"].items():
        p = prev["companies"].get(cid)
        if not p:
            continue
        n = names.get(cid, cid)
        if c["tier"] != p["tier"]:
            add(kind="tier", company=cid, title=f"{n} Tier {p['tier']} → {c['tier']}", roles=["exec", "strategy"], frm=p["tier"], to=c["tier"])
        elif c["total"] != p["total"]:
            add(kind="score", company=cid, title=f"{n} 경쟁력 {p['total']} → {c['total']}점", roles=["exec"], frm=p["total"], to=c["total"])
        if c["attract"] is not None and p["attract"] is not None and c["attract"] != p["attract"]:
            add(kind="attract", company=cid, title=f"{n} 고객 매력도 {p['attract']} → {c['attract']}점", roles=["exec"], frm=p["attract"], to=c["attract"])
        if c["stage"] != p["stage"]:
            st = ctx["stages"]
            add(kind="listing", company=cid, title=f"{n} 상장 단계: {st[p['stage']]} → {st[c['stage']]}", roles=["exec"], frm=p["stage"], to=c["stage"])
        for f, v in c["facts"].items():
            old = p["facts"].get(f)
            if v != old and not (v is None and old is None):
                label, unit, roles = FACTS[f]
                add(kind="fact", company=cid, field=f, title=f"{n} {label} {fmt(old, unit)} → {fmt(v, unit)}", roles=roles, frm=old, to=v)
        for k, (status, when) in c["roadmap"].items():
            title = k.split("|", 1)[1]
            typ = k.split("|", 1)[0]
            roles = ["strategy", "exec"] if typ in ("production", "ipo") else ["strategy"]
            old = p["roadmap"].get(k)
            if old is None:
                add(kind="roadmap", company=cid, title=f"{n} 새 로드맵: {title} ({when})", roles=roles, frm=None, to=status)
            elif old[0] != status or old[1] != when:
                what = f"{STATUS[old[0]]} → {STATUS[status]}" if old[0] != status else f"일정 {old[1]} → {when}"
                add(kind="roadmap", company=cid, title=f"{n} '{title}' {what}", roles=roles, frm=old[0], to=status)
    for sid, status in cur["signposts"].items():
        old = prev["signposts"].get(sid)
        if old and old != status:
            add(kind="signpost", ref=sid, title=f"신호 '{ctx['signposts'].get(sid, sid)}': {SIGN[old]} → {SIGN[status]}", roles=["exec", "strategy"], frm=old, to=status)
    for cid, layers in (cur.get("patents") or {}).items():  # 특허: 기술 층별 최근 3년 건수가 크게 바뀐 곳
        before = (prev.get("patents") or {}).get(cid)
        if not before:
            continue
        for lid, n in layers.items():
            if lid in before and patent_changed(before[lid], n):
                lab = ctx.get("layers", {}).get(lid, lid)
                add(kind="patent", company=cid, layer=lid, title=f"{names.get(cid, cid)} 특허({lab}) 최근 3년 {before[lid]} → {n}건",
                    roles=["engineer", "strategy"], frm=before[lid], to=n)
    for mid, spec in cur["specs"].items():
        old = prev.get("specs", {}).get(mid)
        model, cid = ctx["models"].get(mid, (mid, None))
        if old is None:
            add(kind="spec", ref=mid, company=cid, title=f"스펙 추적 추가: {model}", roles=["engineer"], frm=None, to=None)
            continue
        for k, v in spec.items():
            if v != old.get(k):
                label = ctx["spec_labels"].get(k, k)
                add(kind="spec", ref=mid, company=cid, field=k, layer=SPEC_LAYER.get(k), title=f"{model} {label} {old.get(k) if old.get(k) is not None else '미공개'} → {v if v is not None else '미공개'}",
                    roles=["engineer", "strategy"], frm=old.get(k), to=v)
    return out
