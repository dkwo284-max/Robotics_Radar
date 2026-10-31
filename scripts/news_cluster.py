"""뉴스 품질: 같은 사건을 여러 매체가 낸 기사를 한 건으로 묶고, 휴머노이드·피지컬 AI 와 무관한 시장 질의 기사를 거른다.

- 제목을 글자 2-gram 으로 쪼개 겹치는 정도(자카드)가 높고, 날짜가 며칠 안이며, 제목 속 숫자가 서로 어긋나지 않으면 같은 사건으로 본다.
- 2차: 원문 제목이 매체마다 달라 1차로 못 묶인 기사도, AI 가 붙인 한국어 제목(title_ko)이 비슷하고 같은 기업이 나오며 며칠 안이면 같은 사건으로 본다
  (예: "현대모비스, 아틀라스 부품 시제품 생산" 이 세 매체에서 표현만 다르게 나온 경우 — 화면의 '주요 변화 3건'이 사실은 1건).
- 묶인 기사 중 대표 하나만 남기고 나머지 매체는 also 에 담는다(대표: AI 분류됨 > 중요도 높음 > 한국어 제목 있음 > 먼저 나온 것).
- 원본(news.json)은 건드리지 않고 화면용 데이터를 만들 때만 적용한다.
"""
from __future__ import annotations

import re
from datetime import date

THRESHOLD = 0.58
KO_THRESHOLD = 0.35  # 한국어 제목(AI 가 같은 형식으로 쓴 것)끼리는 표현만 달라도 글자가 많이 겹쳐서 더 낮게 — 실제 데이터로 정함
WINDOW_DAYS = 3
_SUFFIX = re.compile(r"\s[-–—|]\s[^-–—|]{2,30}$")
_NUM = re.compile(r"\d[\d.,]*")
PHYSICAL_RE = re.compile(r"humanoid|휴머노이드|physical ai|피지컬 ?ai|embodied|quadruped|사족|robot hand|로봇 ?손|dexterous|actuator|액추에이터|"
                         r"optimus|atlas|unitree|figure ai|\bvla\b|자연어 명령|로봇 ?ai|ai ?로봇|지능형 로봇|foundation model", re.I)


def _norm(title: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", _SUFFIX.sub("", title).lower())


def _grams(title: str) -> set[str]:
    t = _norm(title)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _nums(title: str) -> set[str]:
    found = {n.strip(".,") for n in _NUM.findall(_SUFFIX.sub("", title))}
    return {n for n in found if len(n) >= 2 and not re.fullmatch(r"(19|20)\d\d", n)}  # 연도는 어느 기사에나 있어 구분 근거가 못 된다


def same_story(a: dict, b: dict, ga: set[str], gb: set[str]) -> bool:
    try:
        if abs((date.fromisoformat(a["date"]) - date.fromisoformat(b["date"])).days) > WINDOW_DAYS:
            return False
    except ValueError:
        return False
    if not ga or not gb or len(ga & gb) / len(ga | gb) < THRESHOLD:
        return False
    na, nb = _nums(a["title"]), _nums(b["title"])
    return not (na and nb and not (na & nb))  # 양쪽에 숫자가 있는데 하나도 안 겹치면 다른 사건(예: 시장 규모 보고서)


def same_story_ko(a: dict, b: dict, ga: set[str], gb: set[str]) -> bool:
    """AI 한국어 제목 기준 2차 판정: 같은 기업 + 며칠 이내 + 제목 유사 + 숫자 일치. (기업이 없는 기사는 묶지 않는다)"""
    if not ga or not gb or not (set(a.get("companies") or []) & set(b.get("companies") or [])):
        return False
    try:
        if abs((date.fromisoformat(a["date"]) - date.fromisoformat(b["date"])).days) > WINDOW_DAYS:
            return False
    except ValueError:
        return False
    if len(ga & gb) / len(ga | gb) < KO_THRESHOLD:
        return False
    na, nb = _nums(a["title_ko"]), _nums(b["title_ko"])
    return not (na and nb and not (na & nb))


def relevant(x: dict) -> bool:
    """시장 전체 질의(_market)로 모은 특허 기사는 휴머노이드·피지컬 AI 단어가 있어야 남긴다. 기업 질의로 모은 것은 그대로 둔다."""
    if x.get("topic") == "patent" and x.get("query") == "_market":
        return bool(PHYSICAL_RE.search(f"{x.get('title', '')} {x.get('title_ko') or ''} {x.get('summary_ko') or ''}"))
    return True


def tidy(items: list[dict]) -> list[dict]:
    """관련 없는 기사를 빼고 같은 사건은 대표 하나로 묶어 돌려준다(최신순 유지). 묶인 매체는 also(이름 목록)·n_src 로 남긴다."""
    items = [x for x in items if relevant(x)]
    grams = [_grams(x["title"]) for x in items]
    kgrams = [_grams(x["title_ko"]) if x.get("ai") and x.get("title_ko") else set() for x in items]  # AI 가 분류한 기사만
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(items)), key=lambda i: items[i]["date"])
    for pos, i in enumerate(order):
        for j in order[pos + 1:]:
            if (date.fromisoformat(items[j]["date"]) - date.fromisoformat(items[i]["date"])).days > WINDOW_DAYS:
                break
            if find(i) != find(j) and (same_story(items[i], items[j], grams[i], grams[j])
                                       or same_story_ko(items[i], items[j], kgrams[i], kgrams[j])):
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idx in groups.values():
        best = min(idx, key=lambda i: (not items[i].get("ai"), -(items[i].get("importance") or 0), not items[i].get("title_ko"), items[i]["date"], i))
        rep = dict(items[best])
        others = [items[i] for i in idx if i != best]
        names = []
        for o in others:
            n = o.get("source") or ""
            if n and n != rep.get("source") and n not in names:
                names.append(n)
        rep["also"] = names[:6]
        rep["n_src"] = 1 + len(others)
        out.append(rep)
    out.sort(key=lambda x: x["date"], reverse=True)
    return out
