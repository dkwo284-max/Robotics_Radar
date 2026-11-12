"""검증 대기 수치 자동 반영 — 손으로 고치지 않아도 오래된 큐레이션 값이 갱신되게 한다.

큐레이션 원본(data/companies.json)은 건드리지 않고, 자동으로 확인된 값만 data/auto_updates.json 에 '덧씌움(overlay)'으로 쌓는다.
빌드할 때 덧씌움의 기준일이 큐레이션 기준일보다 새로울 때만 그 값을 쓴다 → 나중에 손으로 더 새 값을 넣으면 손으로 넣은 값이 이긴다.
되돌리려면 auto_updates.json 의 해당 항목만 지우면 된다.

AI 가 기사에서 뽑은 수치는 틀릴 수 있어서(다른 회사·다른 뜻의 숫자), 아래를 '모두' 통과해야 반영한다:
 ① 서로 다른 기사 2건 이상이 15% 이내로 같은 값을 말한다
 ② 그 기사들의 제목에 해당 기업 이름이 들어 있다 (다른 회사 기사에서 잘못 붙은 숫자 차단)
 ③ 기준 시점이 지금 큐레이션 값보다 새롭다
 ④ AI 재확인(묶어서 요청 1회): 숫자가 그 기업의 그 항목 정의에 맞는가 — AI 를 못 쓰는 날은 반영하지 않고 다음 실행으로 미룬다
한 번 판정한 후보는 다시 묻지 않는다(checked).
"""
from __future__ import annotations

import re
from datetime import date

from common import SRC, log, read_json, write_json

OVERLAY = SRC / "auto_updates.json"
MIN_SOURCES = 2
AGREE = 0.15
FIELD_DEF = {
    "valuation": "기업가치(가장 최근 투자 라운드 뒤 밸류 또는 상장사 시가총액), 백만 달러",
    "funding_total": "그 기업이 지금까지 유치한 누적 투자금, 백만 달러 (한 번의 라운드 금액·다른 회사가 받은 투자·인수 금액은 아님)",
    "revenue": "그 기업의 연 매출, 백만 달러 (분기·반기 매출이나 부문 매출은 아님)",
    "orders": "그 기업의 로봇 수주 잔고·수주액, 백만 달러",
    "cum_units": "그 기업 '휴머노이드' 로봇의 누적 출하 대수 (연간 생산량, 사족 로봇·로봇청소기 등 다른 제품 포함 수치, 시연에 동원된 대수는 아님)",
    "capacity": "그 기업의 휴머노이드 연 생산능력(대)",
    "target_2026": "그 기업이 밝힌 2026년 휴머노이드 출하·생산 목표(대)",
    "price": "그 기업 휴머노이드 1대 판매가, 달러",
}
VERIFY_SCHEMA = {"type": "OBJECT", "properties": {"items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "key": {"type": "STRING"}, "ok": {"type": "BOOLEAN"}, "reason": {"type": "STRING"}}, "required": ["key", "ok", "reason"]}}}, "required": ["items"]}
VERIFY_SYSTEM = """로봇 기업 데이터의 검수자입니다. 각 후보는 뉴스 기사에서 자동으로 뽑은 숫자입니다.
이미 확인된 것: 서로 다른 기사 2건 이상이 15% 이내로 같은 값을 말했고, 값은 달러(백만 달러 또는 대수)로 환산돼 있으며, 기사 제목에 그 기업 이름이 있습니다.
환율 환산의 작은 차이나 기사 간 몇 % 차이는 문제 삼지 마세요. 당신이 판단할 것은 두 가지뿐입니다.
 (1) 숫자가 정말 '해당 기업'의 것인가 (모회사·경쟁사·인수 대상의 숫자가 아닌가)
 (2) 숫자의 뜻이 '해당 항목 정의'와 같은가 (예: 누적이 아닌 연간 수치, 휴머노이드가 아닌 전체 제품 수치, 한 라운드 금액을 누적 조달로 본 것은 정의와 다름)
둘 다 맞으면 ok=true, 하나라도 기사 내용과 어긋나면 ok=false. reason 은 한국어 한 문장(40자 이내). 모든 key 에 한 번씩 답하세요."""


def _stamp(s: str) -> str:
    """기준 시점을 YYYY-MM 으로 (연도만이면 12월, 반기·분기는 그 끝 달)."""
    m = re.match(r"(\d{4})(?:-(H1|H2|Q[1-4]|\d{2}))?", str(s or ""))
    if not m:
        return ""
    x = m.group(2)
    mm = "12" if not x else "06" if x == "H1" else "12" if x == "H2" else f"{int(x[1]) * 3:02d}" if x[0] == "Q" else x
    return f"{m.group(1)}-{mm}"


def names_of(c: dict) -> list[str]:
    """기사 제목에서 찾을 기업 이름 조각 (영문 첫 낱말, 한글 이름 첫 낱말, 지정된 별칭)."""
    out = [c.get("name", "").split()[0], re.sub(r"[\(（].*", "", c.get("name_ko", "")).split()[0] if c.get("name_ko") else "", *c.get("aliases", [])]
    return [n.lower() for n in out if len(n) >= 2]


def candidates(proposals: list[dict], companies: list[dict], news_items: list[dict]) -> list[dict]:
    """①②③을 통과한 후보: [{key, company, field, value, as_of, sources: [{title, url, date}], prev}]."""
    by_id = {c["id"]: c for c in companies}
    news = {x["id"]: x for x in news_items}
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in proposals:
        c = by_id.get(p["company"])
        if not c:
            continue
        n = news.get(p.get("news_id"), {})
        titles = " ".join([p.get("title", ""), n.get("title", ""), n.get("title_ko", "")]).lower()
        if not any(nm in titles for nm in names_of(c)):
            continue  # ② 제목에 기업 이름이 없다
        groups.setdefault((p["company"], p["field"]), []).append({**p, "summary": n.get("summary_ko", "")})
    out = []
    for (cid, field), ps in groups.items():
        ps.sort(key=lambda p: p["proposed"])
        best: list[dict] = []
        for i, p in enumerate(ps):  # 값이 15% 안에서 모이는 가장 큰 묶음 (기사 id 가 서로 달라야 한다)
            grp, seen = [], set()
            for q in ps[i:]:
                if q["proposed"] <= p["proposed"] * (1 + AGREE) and q.get("news_id") not in seen:
                    seen.add(q.get("news_id"))
                    grp.append(q)
            if len(grp) > len(best):
                best = grp
        if len(best) < MIN_SOURCES:
            continue  # ① 서로 다른 기사 2건 이상
        cur = by_id[cid].get(field) if isinstance(by_id[cid].get(field), dict) else {}
        latest = max(best, key=lambda p: p["date"])
        as_of = max((_stamp(p.get("as_of")) for p in best), default="") or latest["date"][:7]
        if as_of > latest["date"][:7]:
            as_of = latest["date"][:7]  # 미래 시점으로 적힌 값은 기사 날짜로
        if cur.get("as_of") and as_of <= _stamp(cur["as_of"]):
            continue  # ③ 지금 값보다 새롭지 않다
        vals = sorted(p["proposed"] for p in best)
        value = vals[len(vals) // 2]
        out.append({"key": f"{cid}|{field}|{round(value)}", "company": cid, "field": field, "value": round(value, 2) if value < 100 else round(value),
                    "as_of": as_of, "prev": {"v": cur.get("v"), "as_of": cur.get("as_of")},
                    "sources": [{"title": p["title"], "url": p["url"], "date": p["date"], "summary": p.get("summary", "")} for p in sorted(best, key=lambda p: p["date"], reverse=True)[:4]]})
    return out


def verify(cands: list[dict], companies: list[dict], llm) -> dict[str, dict]:
    """④ AI 재확인 (요청 1회). 실패하면 빈 dict → 이번에는 아무것도 반영하지 않는다."""
    by_id = {c["id"]: c for c in companies}
    user = "\n\n".join(
        f"[key] {c['key']}\n[기업] {by_id[c['company']]['name']} ({by_id[c['company']]['name_ko']})\n[항목] {c['field']} — {FIELD_DEF[c['field']]}\n"
        f"[뽑힌 값] {c['value']} (기준 {c['as_of']}) · 지금 값 {c['prev']['v']} (기준 {c['prev']['as_of']})\n"
        + "\n".join(f"[기사] {s['date']} {s['title']} — {s['summary']}" for s in c["sources"]) for c in cands)
    try:
        out = llm.json_call(VERIFY_SYSTEM, user, VERIFY_SCHEMA, max_tokens=4000)
    except Exception as e:  # noqa: BLE001
        log.warning("auto-apply: AI 재확인 실패 — 이번에는 반영하지 않음 (%s)", e)
        return {}
    return {r.get("key"): {"ok": bool(r.get("ok")), "reason": str(r.get("reason", ""))[:80]} for r in out.get("items", [])}


def run(companies: list[dict], news: dict, llm, today: str | None = None) -> int:
    """새 후보를 판정해 덧씌움 파일을 갱신한다. 반영한 건수를 돌려준다. AI 를 못 쓰면 아무것도 하지 않는다."""
    today = today or date.today().isoformat()
    ov = read_json(OVERLAY, {})
    ov.setdefault("applied", {})
    ov.setdefault("checked", {})
    cands = [c for c in candidates(news.get("proposals", []), companies, news.get("items", [])) if c["key"] not in ov["checked"]]
    if not cands:
        return 0
    if llm is None or not getattr(llm, "enabled", False):
        log.info("auto-apply: 후보 %d건, AI 를 쓸 수 없어 다음 실행으로 미룸", len(cands))
        return 0
    verdicts = verify(cands, companies, llm)
    n = 0
    for c in cands:
        v = verdicts.get(c["key"])
        if v is None:
            continue
        ov["checked"][c["key"]] = {"date": today, **v}
        if not v["ok"]:
            continue
        ov["applied"][f"{c['company']}|{c['field']}"] = {
            "company": c["company"], "field": c["field"], "v": c["value"], "as_of": c["as_of"], "kind": "reported",
            "note": f"자동 반영 — 보도 {len(c['sources'])}건이 같은 값({v['reason']})", "src": c["sources"][0]["url"],
            "auto": {"date": today, "prev": c["prev"], "sources": [{k: s[k] for k in ("title", "url", "date")} for s in c["sources"]]}}
        n += 1
    write_json(OVERLAY, ov, indent=1)
    log.info("auto-apply: 후보 %d건 중 %d건 반영", len(cands), n)
    return n


def apply_overlay(companies: list[dict], overlay: dict | None = None) -> list[dict]:
    """빌드할 때: 덧씌움의 기준일이 큐레이션 기준일보다 새로울 때만 값을 바꾼다. 반영된 항목 목록을 돌려준다."""
    overlay = overlay if overlay is not None else read_json(OVERLAY, {})
    by_id = {c["id"]: c for c in companies}
    used = []
    for a in (overlay.get("applied") or {}).values():
        c = by_id.get(a.get("company"))
        if not c:
            continue
        cur = c.get(a["field"]) if isinstance(c.get(a["field"]), dict) else {}
        if cur.get("as_of") and _stamp(cur["as_of"]) >= _stamp(a["as_of"]):
            continue  # 손으로 더 새 값을 넣었다 → 큐레이션 값이 이긴다
        c[a["field"]] = {k: a[k] for k in ("v", "as_of", "kind", "note", "src", "auto")}
        used.append({"company": a["company"], "field": a["field"], "v": a["v"], "as_of": a["as_of"], **a["auto"]})
    return sorted(used, key=lambda x: x["date"], reverse=True)
