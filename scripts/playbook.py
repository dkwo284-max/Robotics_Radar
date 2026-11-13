"""'최상급이 되려면' — 한 기업이 경쟁력 총점(기술 30·양산 30·자본 20·실행 20) 1위가 되려면 무엇을 해야 하고, 모회사는 무엇을 뒷받침해야 하나.

규칙으로만 만든다(AI 0회). 큐레이션 점수·수치·로드맵·최근 소식에서:
 ① 격차 진단: 축마다 그 축 1위 기업과의 점수 차이
 ② 행동 제안: 격차가 있는 축마다 정해진 행동 틀을, 이 기업과 1위 기업의 실제 수치로 채운다. 예상 점수 = 그 축의 격차를 행동별 비중으로 나눈 값(추정)
 ③ 모회사 지원: 행동마다 모회사(parent)가 할 일. 모회사가 없으면 전략 투자자·핵심 고객이 대신할 일
 ⑤ 선례: 그 축 1위 기업이 점수를 받은 이유   ⑥ 시점: 6·12·24개월   ⑦ 위험   ⑧ 진척: 최근 30일 관련 소식
점수는 이 앱의 큐레이션 체계 기준이라 실제 사업 판단과 다를 수 있다 — 화면에 그렇게 밝힌다.
"""
from __future__ import annotations

from datetime import date, timedelta

AXES = ("tech", "scale", "capital", "execution")
AX_KO = {"tech": "기술", "scale": "양산", "capital": "자본", "execution": "실행 신뢰도"}
DEFAULT = "bd"


def _units(v) -> str:
    return "미공개" if v is None else f"{v / 10000:.1f}만 대" if v >= 10000 else f"{int(v):,}대"


def _fv(c: dict, k: str):
    f = c.get(k)
    return f.get("v") if isinstance(f, dict) else None


# 행동 틀: (id, 축, 비중, 시점(개월), 제목, 상세(기업 c·축 1위 L 로 채움), 모회사 지원, 모회사가 없을 때, 위험, 진척을 찾을 낱말)
TEMPLATES = [
    ("S1", "scale", 0.40, 12, "실제 출하 실적을 만들고 숫자로 공개",
     lambda c, L: f"누적 출하 {_units(_fv(c, 'cum_units'))} → 양산 1위 {L['name_ko']}은 {_units(_fv(L, 'cum_units'))}. 소량 시범이 아니라 분기마다 세 자릿수 이상 출하가 이어져야 양산 점수가 오릅니다.",
     "그룹 공장·물류 현장에 '언제까지 몇 대'를 확약해 초기 출하 물량을 만들어 준다",
     "핵심 고객 한두 곳과 다년 물량 계약으로 초기 출하를 확보한다",
     "초기 품질·안전 사고가 나면 실적보다 신뢰 손실이 더 크다", ["출하", "shipment", "shipped", "deliver", "납품", "배치"]),
    ("S2", "scale", 0.35, 24, "발표한 생산능력을 실제로 돌아가는 라인으로",
     lambda c, L: f"생산능력 {_units(_fv(c, 'capacity'))}{'(계획: ' + c['capacity']['note'] + ')' if isinstance(c.get('capacity'), dict) and c['capacity'].get('note') else ''}. 계획이 아니라 가동 중인 전용 라인과 시간당 생산 속도를 보여 줘야 합니다.",
     "공장 부지·설비 투자와 자동차 양산 기술 인력을 지원해 라인 가동 시점을 앞당긴다",
     "위탁생산 파트너와 전용 라인 계약을 맺는다",
     "수요가 따라오지 않으면 고정비 부담이 커진다", ["공장", "라인", "양산", "factory", "production line", "capacity", "생산능력"]),
    ("S3", "scale", 0.25, 12, "그룹 밖 유료 고객 확보",
     lambda c, L: f"공개된 고객: {', '.join(c.get('customers') or []) or '없음'}. 모회사·계열사 밖의 유료 고객이 있어야 수요가 검증됩니다.",
     "계열사 밖 판매를 허용하고, 협력사·물류 고객을 첫 외부 레퍼런스로 연결한다",
     "전략 투자자의 고객망을 통해 첫 유료 배치를 만든다",
     "외부 판매는 서비스·유지보수 조직이 먼저 갖춰져야 한다", ["고객", "계약", "customer", "contract", "수주", "order", "도입"]),
    ("E1", "execution", 0.50, 6, "발표한 일정을 지킨다 (지연·기한 경과 0건)",
     lambda c, L: f"실행 신뢰도 근거: {c['scores']['execution'][1] or '기록 없음'}. 남은 예정 일정 {sum(1 for r in c.get('roadmap', []) if r.get('status') == 'planned')}건을 발표대로 끝내는 것이 가장 빠른 길입니다.",
     "일정에 필요한 투자 집행을 앞당기고, 목표를 연 단위가 아니라 분기 단위로 나눠 공개한다",
     "이사회가 분기 단위 마일스톤을 공개 약속으로 관리한다",
     "일정을 맞추려 무리하면 품질 문제가 생긴다", ["연기", "지연", "delay", "postpone", "일정", "예정대로"]),
    ("E2", "execution", 0.50, 6, "분기마다 출하·배치 수치를 공개",
     lambda c, L: f"실행 1위 {L['name_ko']}: {L['scores']['execution'][1] or '발표와 실적이 일치'}. 발표 대비 실적을 외부에서 확인할 수 있어야 신뢰 점수가 붙습니다.",
     "그룹 실적 발표(IR)에 로봇 부문 출하·매출을 따로 공개한다",
     "투자자 서한·보도자료로 분기 실적을 정례 공개한다",
     "부진한 분기도 그대로 드러난다", ["실적", "분기", "공개", "results", "quarter", "revenue", "매출"]),
    ("C1", "capital", 1.00, 24, "적자 구간을 버틸 전용 성장 자금을 확보",
     lambda c, L: f"자본 근거: {c['scores']['capital'][1] or '기록 없음'}{' · ' + c['listing']['note'] if c.get('listing', {}).get('note') else ''}. 외부 투자 유치·상장·증자 중 하나로 양산 투자 재원을 명확히 해야 합니다.",
     "증자·지분 투자로 양산 전까지의 자금을 보장하고, 상장 여부와 시점을 분명히 한다",
     "대형 라운드나 상장으로 양산 자금을 확보한다",
     "외부 자금이 들어오면 지배구조·기술 통제권이 달라질 수 있다", ["투자", "funding", "IPO", "상장", "증자", "raise", "밸류"]),
    ("T1", "tech", 0.60, 12, "범용 조작 AI(로봇 파운데이션 모델) 격차를 줄인다",
     lambda c, L: f"기술 근거: {c['scores']['tech'][1] or '기록 없음'} ↔ 기술 1위 {L['name_ko']}: {L['scores']['tech'][1] or ''}. 걷는 능력보다 '손으로 일하는 능력'이 점수를 가릅니다.",
     "그룹 공장의 작업 데이터와 시뮬레이션·연산 자원을 학습용으로 제공한다",
     "AI 연구소·클라우드 사업자와 모델 공동 개발 계약을 맺는다",
     "외부 모델에 기대면 핵심 역량이 파트너에게 남는다", ["VLA", "foundation model", "파운데이션", "AI 모델", "Gemini", "GR00T", "학습"]),
    ("T2", "tech", 0.40, 24, "핵심 부품(액추에이터·손)을 내재화하거나 전략 공급사를 확보",
     lambda c, L: f"조달 방식: {c.get('sourcing', {}).get('mode') or '미공개'}. 원가의 절반 이상인 구동부를 안정적으로 확보해야 가격과 성능을 함께 잡습니다.",
     "계열 부품사와 공동 개발하고 전용 공급 라인을 만든다",
     "핵심 부품사에 지분 투자하거나 장기 공급 계약을 맺는다",
     "특정 공급사에 묶이면 원가 협상력이 떨어진다", ["액추에이터", "actuator", "감속기", "reducer", "hand", "손", "부품"]),
]


def _progress(c: dict, parent: dict | None, kws: list[str], news: list[dict], today: str) -> dict:
    """최근 30일 이 기업(또는 모회사) 소식 중 행동과 관련된 낱말이 든 기사 수와 가장 최근 기사. n7/n_prev7 = 최근 7일 / 그 전 7일."""
    t = date.fromisoformat(today)
    cutoff = (t - timedelta(days=30)).isoformat()
    d7, d14 = (t - timedelta(days=7)).isoformat(), (t - timedelta(days=14)).isoformat()
    ids = {c["id"]} | ({parent["id"]} if parent else set())
    hits = [x for x in news if x.get("date", "") >= cutoff and ids & set(x.get("companies") or [])
            and any(k.lower() in f"{x.get('title', '')} {x.get('title_ko', '')} {x.get('summary_ko', '')}".lower() for k in kws)]
    hits.sort(key=lambda x: (x.get("importance", 0), x["date"]), reverse=True)
    top = hits[0] if hits else None
    return {"n": len(hits), "n7": sum(1 for x in hits if x["date"] > d7), "n_prev7": sum(1 for x in hits if d14 < x["date"] <= d7), "title": (top.get("title_ko") or top.get("title")) if top else "", "url": top.get("url", "") if top else "", "date": top["date"] if top else ""}


def _week(c: dict, companies: list[dict], history: dict | None, today: str) -> dict | None:
    """지난주 대비: 7일 전(또는 그 이전 가장 가까운) 점수 스냅숏과 비교한 총점·순위·1위와의 격차. 스냅숏이 없으면 None."""
    snaps = (history or {}).get("snapshots") or []
    cut = (date.fromisoformat(today) - timedelta(days=7)).isoformat()
    old = next((s for s in reversed(snaps) if s.get("date", "") <= cut), None)
    if not old or c["id"] not in (old.get("scores") or {}):
        return None
    ids = {x["id"] for x in companies}
    prev = {k: v[0] for k, v in old["scores"].items() if k in ids and v and v[0] is not None}
    ranked = sorted(prev, key=lambda k: -prev[k])
    lead = next((k for k in ranked if k != c["id"]), None)
    return {"since": old["date"], "total_from": prev[c["id"]], "rank_from": ranked.index(c["id"]) + 1,
            "gap_from": (prev[lead] - prev[c["id"]]) if lead else None, "leader_from": lead}


def for_company(c: dict, companies: list[dict], news: list[dict], today: str, history: dict | None = None) -> dict:
    by_id = {x["id"]: x for x in companies}
    parent = by_id.get(c.get("parent") or "")
    total = lambda x: sum(x["scores"][k][0] for k in AXES)  # noqa: E731
    ranked = sorted(companies, key=lambda x: -total(x))
    gaps, actions = [], []
    for k in AXES:
        L = max((x for x in companies if x["id"] != c["id"]), key=lambda x: x["scores"][k][0])
        gap = max(0, L["scores"][k][0] - c["scores"][k][0])
        gaps.append({"axis": k, "score": c["scores"][k][0], "why": c["scores"][k][1], "leader": L["id"], "leader_score": L["scores"][k][0], "leader_why": L["scores"][k][1], "gap": gap})
        if not gap:
            continue
        tmpl = [t for t in TEMPLATES if t[1] == k]
        left = gap
        for i, (aid, _, share, months, title, detail, sup, alt, risk, kws) in enumerate(tmpl):
            gain = left if i == len(tmpl) - 1 else min(left, max(1, round(gap * share)))  # 마지막 행동이 남은 점수를 가져가 합이 격차와 같게
            left -= gain
            if gain <= 0:
                continue
            actions.append({"id": aid, "axis": k, "title": title, "detail": detail(c, L), "gain": gain, "months": months,
                            "support": sup if parent else alt, "has_parent": bool(parent),
                            "precedent": {"company": L["id"], "text": L["scores"][k][1]}, "risk": risk,
                            "progress": _progress(c, parent, kws, news, today)})
    actions.sort(key=lambda a: (-a["gain"], a["months"]))
    # 1위가 되는 가장 짧은 조합: 점수가 큰 행동부터 더해 1위 총점을 넘는 지점
    lead = next((x for x in ranked if x["id"] != c["id"]), None)
    need, picked, acc = (total(lead) - total(c) + 1) if lead else 0, [], 0
    for a in actions:
        if acc >= need:
            break
        picked.append(a["id"])
        acc += a["gain"]
    return {"id": c["id"], "parent": parent["id"] if parent else None, "total": total(c), "rank": [x["id"] for x in ranked].index(c["id"]) + 1,
            "leader": lead["id"] if lead else None, "leader_total": total(lead) if lead else None, "gaps": gaps, "actions": actions,
            "shortest": picked if acc >= need and need > 0 else [], "reachable": total(c) + sum(a["gain"] for a in actions),
            "risks": c.get("risks", []), "roadmap": [r for r in c.get("roadmap", []) if r.get("status") == "planned"],
            "week": _week(c, companies, history, today)}


def build(companies: list[dict], news: list[dict], today: str, history: dict | None = None) -> dict:
    # 로봇 본체를 만드는 기업끼리만 비교한다 (칩·모델 공급사는 사업 성격이 달라 '로봇 사업 1위' 비교 대상이 아니다)
    body = [c for c in companies if c.get("group", "body") == "body" and all(k in c.get("scores", {}) for k in AXES)]
    return {"default": DEFAULT if any(c["id"] == DEFAULT for c in body) else (body[0]["id"] if body else None), "axes": AX_KO,
            "totals": {c["id"]: sum(c["scores"][k][0] for k in AXES) for c in body},
            "targets": {c["id"]: for_company(c, body, news, today, history) for c in body}}
