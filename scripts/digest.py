"""주간 다이제스트: 지난 7일의 변화 로그 + 주요 소식을 경영진·기술전략·엔지니어 관점으로 한 단락씩.

- 일주일에 한 번(직전 다이제스트가 6일 넘게 지났거나 AI 없이 만든 것이면) Gemini 1회.
- 키가 없거나 상한이면 규칙 기반으로(중요도·최신순 상위 3건) 만든다 — 다음에 AI 를 쓸 수 있을 때 다시 만든다.
- 결과: web/data/digest.json (최근 8주 보관)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from common import log
from llm import Gemini, LLMError
from news import ROLE_BY_TYPE

ROLES = {"exec": "경영진", "strategy": "기술전략", "engineer": "엔지니어"}
ROLE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "bullets": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"text": {"type": "STRING"}, "refs": {"type": "ARRAY", "items": {"type": "STRING"}}},
                                               "required": ["text", "refs"]}},
        "action": {"type": "STRING"},
    },
    "required": ["headline", "bullets", "action"],
}
SCHEMA = {"type": "OBJECT", "properties": {r: ROLE_SCHEMA for r in ROLES}, "required": list(ROLES)}

SYSTEM = """당신은 휴머노이드·피지컬 AI 산업을 한국 제조·부품사에 브리핑하는 애널리스트입니다.
지난 7일의 [변화](큐레이션 데이터 변경)와 [소식](id 가 있는 기사)만 근거로, 세 관점의 주간 요약을 한국어로 씁니다.
- exec(경영진): 고객·경쟁 구도·자금·상장·정책이 우리 회사(부품사)의 매출·투자 판단에 주는 의미
- strategy(기술전략): 제품 출시·양산 일정·로드맵·기술 방향(액추에이터 방식, AI 모델)의 변화
- engineer(엔지니어): 부품·구동 방식·센서·배터리·손·스펙·공급사 변화
각 관점마다 headline(40자 이내, 이번 주 한 줄 결론), bullets 2~3개(각 70자 이내, refs 에 근거 소식 id — 변화 항목이 근거면 빈 배열),
action(50자 이내, 다음 주에 할 일 하나). 근거에 없는 사실·수치를 만들지 마세요. 해당 관점에 의미 있는 변화가 없으면 headline 을 "큰 변화 없음"으로 하고 bullets 는 1개만."""


def due(old: dict, today: str, ai_ready: bool) -> bool:
    items = old.get("items", [])
    if not items:
        return True
    last = items[0]
    if ai_ready and not last.get("ai"):
        return True
    return date.fromisoformat(last["to"]) <= date.fromisoformat(today) - timedelta(days=6)


def gather(changes: list[dict], news: list[dict], start: str) -> tuple[list[dict], list[dict]]:
    ch = [c for c in changes if c["date"] >= start]
    nw = sorted((x for x in news if x["date"] >= start and (x.get("importance", 1) >= 2 or not x.get("ai"))),
                key=lambda x: x["date"], reverse=True)
    nw = sorted(nw, key=lambda x: -x.get("importance", 1))[:40]  # 중요도 순, 같으면 최신 먼저
    return ch, nw


def role_of(x: dict) -> list[str]:
    """AI 가 붙인 대상 → 없으면 유형으로 추정 → AI 분류 전 기사는 경영진."""
    if not x.get("ai"):
        return ["exec"]
    return x.get("audience") or ROLE_BY_TYPE.get(x.get("type"), [])


def fallback(ch: list[dict], nw: list[dict]) -> dict:
    """AI 없이: 역할별로 변화·소식 상위 3건을 그대로 나열."""
    out = {}
    for role in ROLES:
        rows = [{"text": c["title"], "refs": []} for c in ch if role in c.get("roles", [])][:2]
        rows += [{"text": x.get("title_ko") or x["title"], "refs": [x["id"]]} for x in nw if role in role_of(x)][: 3 - len(rows)]
        out[role] = {"headline": f"{len(rows)}건의 주요 변화" if rows else "큰 변화 없음", "bullets": rows,
                     "action": "" if rows else "다음 주 소식을 지켜보세요"}
    return out


def make(changes: list[dict], news: list[dict], llm: Gemini, today: str) -> dict:
    start = (date.fromisoformat(today) - timedelta(days=7)).isoformat()
    ch, nw = gather(changes, news, start)
    ids = {x["id"] for x in nw}
    roles, ai = None, False
    if llm.enabled and (ch or nw):
        user = "[변화]\n" + ("\n".join(f"- {c['date']} {c['title']} (보는 사람: {','.join(c.get('roles', []))})" for c in ch) or "(없음)")
        user += "\n\n[소식]\n" + ("\n".join(f"[{x['id']}] {x['date']} {x.get('title_ko') or x['title']} — {x.get('summary_ko', '')}"
                                           f" (중요도 {x.get('importance', 1)}, 대상 {','.join(role_of(x))})" for x in nw) or "(없음)")
        try:
            roles = llm.json_call(SYSTEM, user, SCHEMA, max_tokens=4000)
            for r in ROLES:
                roles[r]["bullets"] = [{"text": b["text"][:120], "refs": [i for i in b.get("refs", []) if i in ids][:3]}
                                       for b in roles[r].get("bullets", [])][:3]
                roles[r]["headline"] = roles[r].get("headline", "")[:60]
                roles[r]["action"] = roles[r].get("action", "")[:80]
            ai = True
        except (LLMError, KeyError, TypeError) as e:
            log.warning("digest AI failed: %s", e)
            roles = None
    if roles is None:
        roles = fallback(ch, nw)
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "from": start, "to": today,
            "ai": ai, "n_changes": len(ch), "n_news": len(nw), "roles": roles}


def update_digest(old: dict, changes: list[dict], news: list[dict], llm: Gemini, today: str) -> dict:
    d = make(changes, news, llm, today)
    items = [x for x in old.get("items", []) if x["to"] != today]
    return {"items": ([d] + items)[:8]}
