"""기업별 소식: Google 뉴스 RSS 로 모으고, Gemini 가 하루 1회 배치로 분류·요약·수치 추출을 한다.

- 이미 처리한 기사는 다시 AI 에 보내지 않는다(누적, keep_days 일 보관).
- 기사 본문은 저장하지 않는다. RSS 에는 보통 제목·짧은 설명만 있어 추출 근거도 그 범위다.
- AI 가 뽑은 수치는 큐레이션 값을 덮어쓰지 않는다. 다르면 '검증 대기'(proposals)로만 쌓는다.
- 키가 없거나 하루 상한을 넘으면 제목만 저장하고 분류는 건너뛴다.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

from common import log, plausible
from llm import Gemini, LLMError

RSS = {
    "en": "https://news.google.com/rss/search?q={q}+when:{d}d&hl=en-US&gl=US&ceid=US:en",
    "ko": "https://news.google.com/rss/search?q={q}+when:{d}d&hl=ko&gl=KR&ceid=KR:ko",
}
TYPES = ["funding", "ipo", "production", "product", "deploy", "partner", "supply", "policy", "org", "patent", "other"]
ROLES = ["exec", "strategy", "engineer"]
LAYERS = ["actuator", "hand", "battery", "sensor", "ai", "safety", "cost", "none"]
# AI 를 못 쓴 기사의 역할 추정(유형 기준)
ROLE_BY_TYPE = {"funding": ["exec"], "ipo": ["exec"], "policy": ["exec"], "org": ["exec"], "production": ["exec", "strategy"],
                "product": ["strategy", "engineer"], "deploy": ["strategy"], "partner": ["exec", "strategy"], "supply": ["exec", "engineer"],
                "patent": ["exec", "strategy", "engineer"], "other": []}
FIELDS = {  # 추출 대상 필드 → 단위
    "valuation": "USD_M", "funding_total": "USD_M", "revenue": "USD_M", "orders": "USD_M",
    "cum_units": "units", "capacity": "units", "target_2026": "units", "price": "USD",
}

def schema(signpost_ids: list[str]) -> dict:
    s = json.loads(json.dumps(SCHEMA))
    item = s["properties"]["items"]["items"]
    item["properties"]["signpost"] = {"type": "STRING", "enum": signpost_ids + ["none"]}
    item["required"].append("signpost")
    return s


SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "relevant": {"type": "BOOLEAN"},
                    "companies": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "type": {"type": "STRING", "enum": TYPES},
                    "title_ko": {"type": "STRING"},
                    "summary_ko": {"type": "STRING"},
                    "importance": {"type": "INTEGER"},
                    "audience": {"type": "ARRAY", "items": {"type": "STRING", "enum": ROLES}},
                    "layer": {"type": "STRING", "enum": LAYERS},
                    "facts": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "company": {"type": "STRING"},
                                "field": {"type": "STRING", "enum": list(FIELDS)},
                                "value": {"type": "NUMBER"},
                                "as_of": {"type": "STRING"},
                            },
                            "required": ["company", "field", "value"],
                        },
                    },
                },
                "required": ["id", "relevant", "companies", "type", "title_ko", "summary_ko", "importance", "audience", "layer", "facts"],
            },
        }
    },
    "required": ["items"],
}

SYSTEM = """당신은 휴머노이드·피지컬 AI 산업을 한국 제조·부품사 경영진에게 브리핑하는 애널리스트입니다. 각 기사(id)마다:
- relevant: 아래 추적 기업이나 휴머노이드 산업(시장·정책·공급망)에 대한 실질적 소식이면 true. 홍보성 행사 사진, 주가 단순 등락, 동명이인·무관한 회사면 false.
- companies: 기사가 다루는 추적 기업 id 목록(목록에 있는 id 만). 산업 전반이면 빈 배열.
- type: funding(투자 유치) / ipo(상장) / production(양산·생산능력) / product(제품·모델 공개) / deploy(현장 배치·고객) / partner(제휴) / supply(부품·공급망) / policy(정책·규제) / org(경영진·조직) / patent(특허 소송·분쟁·라이선스·대형 출원·등록) / other.
- title_ko: 자연스러운 한국어 제목(45자 이내).
- summary_ko: 한국 부품사·투자 관점에서 왜 중요한지 한 문장(80자 이내). 주어진 제목·설명에 있는 사실만 쓰고 없는 수치를 지어내지 마세요.
- title_ko·summary_ko 는 한글로만 쓰세요. 중국어·영어·스페인어 단어를 섞지 말고 고유명사도 한글로 표기합니다(예: Boston Dynamics → 보스턴 다이나믹스, 固态电池 → 전고체 배터리).
- importance: 1(참고) 2(주목) 3(의사결정에 영향 — 1억 달러 이상 조달, 상장 단계 변화, 양산 일정 변경, 대형 고객 계약, 규제 통과).
  3 은 드물게(전체의 10% 이내) 주세요. 신제품 시연·행사·채용·전망 기사는 1~2 입니다.
- facts: 기사에 명시된 회사 전체 수치만. field 는 valuation·funding_total·revenue·orders(모두 금액, USD 백만으로 환산 — 위안은 7.1, 원은 1400, 홍콩달러 7.8 로 나눔.
  대수로 된 주문은 넣지 마세요), cum_units(회사의 누적 출하·생산 총계 — 행사·시연에 동원된 대수나 한 고객 납품 대수는 아님),
  capacity(연간 생산능력 대수), target_2026(2026 출하·생산 목표 대수), price(대당 판매가 USD).
  as_of 는 수치 기준 시점(YYYY-MM 또는 YYYY). 확실하지 않으면 넣지 말고, 명시된 수치가 없으면 빈 배열.
- audience: 이 소식을 꼭 봐야 하는 사람(복수 가능). exec(경영진 — 자금·상장·고객·경쟁 구도·정책),
  strategy(기술전략 — 제품 출시·양산 일정·로드맵·기술 방향), engineer(엔지니어 — 부품·구동 방식·센서·배터리·스펙·공급사).
- layer: 기술 층 actuator(모터·감속기·스크류) / hand(손) / battery / sensor(카메라·촉각·힘) / ai(모델·칩) / safety(안전·표준) / cost(원가·가격) / none.
- signpost: 아래 [주시할 신호] 중 이 기사가 직접 관련된 신호 id. 없으면 "none".
모든 id 를 한 번씩 반환하세요."""


# 특허·지재권 질의로 모은 기사는 제목·설명에 이런 단어가 있을 때만 남긴다 — 구글 뉴스는 본문 일치도 잡아서 일반 기사가 섞인다
PATENT_RE = re.compile(r"patent|lawsuit|litigation|licens|infring|trade secret|intellectual propert|특허|지재권|지식재산|침해|소송|专利|诉讼", re.I)


ROBOT_RE = re.compile(r"robot|humanoid|optimus|atlas|actuator|gripper|exoskeleton|embodied|physical ai|로봇|휴머노이드|피지컬|액추에이터|机器人", re.I)


def item_id(link: str, title: str) -> str:
    return hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:12]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_feed(raw: bytes | str, company: str, lookback_days: int, lang: str) -> list[dict]:
    feed = feedparser.parse(raw)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    out = []
    for e in feed.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        when = datetime(*t[:6], tzinfo=timezone.utc) if t else None
        if when and when < cutoff:
            continue
        title = _clean(e.get("title", ""))
        source = _clean((e.get("source") or {}).get("title", "")) if isinstance(e.get("source"), dict) else ""
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        desc = _clean(e.get("summary", ""))
        if desc.startswith(title):
            desc = desc[len(title):].strip(" -–")
        if desc == source:
            desc = ""
        out.append({"id": item_id(e.get("link", ""), title), "query": company, "lang": lang, "title": title, "source": source,
                    "url": e.get("link", ""), "date": (when or datetime.now(timezone.utc)).date().isoformat(), "desc": desc})
    return out


def collect(cfg: dict, client: httpx.Client, known: set[str]) -> list[dict]:
    """일반 소식(queries)과 특허·지재권 소식(patent_queries, topic=patent)을 모은다. 둘 다 키가 필요 없는 구글 뉴스 RSS."""
    ncfg = cfg["news"]
    fresh: list[dict] = []
    seen_titles: set[str] = set()
    for topic, per, by_company, days in (("news", int(ncfg.get("per_company", 3)), ncfg["queries"], int(ncfg.get("lookback_days", 7))),
                                         ("patent", int(ncfg.get("per_company_patent", 2)), ncfg.get("patent_queries", {}),
                                          int(ncfg.get("lookback_days_patent", ncfg.get("lookback_days", 7))))):
        for company, queries in by_company.items():
            if company.startswith("_") and company != "_market":
                continue
            got = 0
            for q, lang in queries:
                try:
                    r = client.get(RSS[lang].format(q=quote_plus(q), d=days))
                    r.raise_for_status()
                    items = parse_feed(r.content, company, days, lang)
                except Exception as e:  # noqa: BLE001
                    log.warning("news %s/%s failed: %s", topic, company, e)
                    continue
                for x in sorted(items, key=lambda x: x["date"], reverse=True):
                    key = re.sub(r"\W+", "", x["title"].lower())[:50]
                    if x["id"] in known or key in seen_titles:
                        continue
                    if topic == "patent":
                        text = f"{x['title']} {x.get('desc', '')}"
                        if not (PATENT_RE.search(text) and ROBOT_RE.search(text)):
                            continue  # 특허·지재권 단어와 로봇 단어가 함께 있어야 한다(일반 소송·라이선스 기사 제외)
                    seen_titles.add(key)
                    fresh.append({**x, "topic": topic})
                    got += 1
                    if got >= per:
                        break
    return fresh


def classify(items: list[dict], companies: list[dict], llm: Gemini, limit: int,
             signposts: list[dict] | None = None) -> tuple[list[dict], str | None, list[str]]:
    """AI 분류 → (저장할 기사, 경고, 관련 없다고 본 id). 실패하거나 키가 없으면 제목만."""
    signposts = signposts or []
    plain = lambda x: {**x, "ai": False, "companies": [] if x["query"] == "_market" else [x["query"]], "type": "patent" if x.get("topic") == "patent" else "other",  # noqa: E731
                       "title_ko": "", "summary_ko": "", "importance": 1, "audience": [], "layer": None, "signpost": None, "facts": []}  # layer None = 아직 분류 전
    if not items:
        return [], None, []
    if not llm.enabled:
        return [plain(x) for x in items], "AI 키가 없어 분류 없이 제목만 표시합니다.", []
    ids = {c["id"] for c in companies}
    roster = ", ".join(f"{c['id']}={c['name']}({c['name_ko']})" for c in companies)
    todo = items[:limit]
    signs = "; ".join(f"{s['id']}={s['trigger']}" for s in signposts) or "(없음)"
    user = f"[추적 기업 id] {roster}\n[주시할 신호] {signs}\n\n" + "\n\n".join(
        f"[id] {x['id']}\n[검색 기업] {x['query']}\n[제목] {x['title']}\n[출처] {x['source']} · {x['date']}"
        + (f"\n[설명] {x['desc'][:300]}" if x["desc"] else "") for x in todo)
    warn = None
    rows: dict[str, dict] = {}
    try:
        rows = {r.get("id"): r for r in llm.json_call(SYSTEM, user, schema([s["id"] for s in signposts])).get("items", [])}
    except LLMError as e:
        log.warning("news AI failed: %s", e)
        warn = "AI 분류에 실패해 제목만 표시합니다."
    out, irrelevant = [], []
    for x in todo:
        r = rows.get(x["id"])
        if r is None:
            out.append(plain(x))
            continue
        if not r.get("relevant", True):
            irrelevant.append(x["id"])
            continue
        facts = [{"company": f["company"], "field": f["field"], "value": f["value"], "as_of": str(f.get("as_of", ""))[:7]}
                 for f in r.get("facts", []) if f.get("company") in ids and f.get("field") in FIELDS and isinstance(f.get("value"), (int, float)) and f["value"] > 0]
        out.append({**x, "ai": True, "companies": [c for c in r.get("companies", []) if c in ids],
                    "type": r.get("type") if r.get("type") in TYPES else "other",
                    "title_ko": r.get("title_ko", "")[:80], "summary_ko": r.get("summary_ko", "")[:140],
                    "importance": min(3, max(1, int(r.get("importance", 1)))),
                    "audience": [a for a in r.get("audience", []) if a in ROLES] or ROLE_BY_TYPE.get(r.get("type"), []),
                    "layer": r.get("layer") if r.get("layer") in LAYERS else "none",
                    "signpost": r.get("signpost") if r.get("signpost") in {s["id"] for s in signposts} else None, "facts": facts})
    # 한도를 넘어 미룬 기사는 저장하지 않는다(다음 실행에서 새 기사로 다시 잡힘)
    if len(items) > limit:
        log.info("news: %d item(s) deferred to next run", len(items) - limit)
    return out, warn, irrelevant


def proposals(items: list[dict], companies: list[dict], old: list[dict], keep_days: int = 90) -> list[dict]:
    """AI 추출 수치가 큐레이션 값과 10% 넘게 다르거나 큐레이션 값이 비어 있으면 '검증 대기'로."""
    by_id = {c["id"]: c for c in companies}
    out = {(p["company"], p["field"], p["proposed"]): p for p in old}
    for x in items:
        for f in x.get("facts", []):
            c = by_id.get(f["company"])
            if not c:
                continue
            cur = (c.get(f["field"]) or {}).get("v") if isinstance(c.get(f["field"]), dict) else None
            if not plausible(f["field"], cur, f["value"]):
                continue
            key = (f["company"], f["field"], f["value"])
            out.setdefault(key, {"company": f["company"], "field": f["field"], "unit": FIELDS[f["field"]], "curated": cur,
                                 "proposed": f["value"], "as_of": f.get("as_of", ""), "date": x["date"],
                                 "title": x.get("title_ko") or x["title"], "url": x["url"], "news_id": x["id"]})
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    return sorted((p for p in out.values() if p["date"] >= cutoff), key=lambda p: p["date"], reverse=True)


def needs_retry(x: dict) -> bool:
    """AI 로 분류되지 않았거나, 역할·기술 층·신호 태그가 생기기 전에 분류돼 태그가 없는 기사는 다시 분류한다."""
    return not x.get("ai") or "layer" not in x


def update_news(cfg: dict, old: dict, companies: list[dict], llm: Gemini, client: httpx.Client | None = None,
                signposts: list[dict] | None = None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; RoboticsRadar/1.0)"})
    try:
        items = {x["id"]: x for x in old.get("items", [])}
        fresh = collect(cfg, client, set(items) | set(old.get("dropped", [])))
        # 키가 없거나 상한에 걸려 제목만 저장된 최근 기사는 AI 를 쓸 수 있을 때 다시 분류한다(새 기사 먼저)
        since = (date.today() - timedelta(days=int(cfg["news"].get("lookback_days", 7)))).isoformat()
        retry = [{**x, "desc": ""} for x in items.values() if needs_retry(x) and x["date"] >= since] if llm.enabled else []
        limit = int(cfg["news"].get("max_ai_items", 40))
        todo = fresh + retry  # 새 기사 먼저, 그다음 태그가 없는 지난 기사
        done, dropped, warn = [], [], None
        for start in range(0, len(todo), limit):
            if llm.enabled and llm.requests >= llm.max_requests:
                break  # 오늘 쓸 수 있는 AI 요청을 다 썼다 — 나머지는 다음 실행에서 이어서 분류
            out, w, drp = classify(todo[start:start + limit], companies, llm, limit, signposts)
            done += out
            dropped += drp
            warn = warn or w
        for i in dropped:
            items.pop(i, None)
    finally:
        if own:
            client.close()
    for x in done:
        x.pop("desc", None)
        items[x["id"]] = x
    cutoff = (date.today() - timedelta(days=int(cfg["news"].get("keep_days", 120)))).isoformat()
    live = sorted((x for x in items.values() if x["date"] >= cutoff), key=lambda x: (x["date"], x["id"]), reverse=True)
    log.info("news: %d new, %d kept, %d dropped", len(done), len(live), len(dropped))
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "ai": "gemini" if llm.enabled else "none", "items": live,
            "proposals": proposals(done, companies, old.get("proposals", [])),
            "dropped": (old.get("dropped", []) + dropped)[-2000:], "warnings": [warn] if warn else []}
