"""특허 수집(EPO OPS, 무료 키 필요): 출원인 × 기술 층 건수(최근 3년 vs 직전 3년), 최근 공개 특허, 출원 품질 지표.

- AI 를 쓰지 않는다. 결과는 web/data/patents.json (셀별 수집일을 남겨 이어서 채운다).
- 한 번에 쓰는 검색 수(budget.max_searches)와 시간(max_minutes)에 상한이 있고, 오래된 셀부터 갱신한다.
  처음엔 며칠에 걸쳐 채워지고, 그다음부터는 매일 조금씩만 새로 고친다(셀 28일, 최근 공개·품질 6일).
- OPS 응답 구조는 문서가 빈약해 관대하게 파싱한다. `--probe` 로 키·검색식·응답 형태를 먼저 점검할 수 있다.

    python scripts/patents.py --probe     # 대표 질의 몇 개만 실행해 건수·구조 출력 (저장 안 함)
    python scripts/patents.py             # 수집 (EPO_OPS_KEY, EPO_OPS_SECRET 필요)
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from common import OUT, SRC, log, read_json, write_json

API = "https://ops.epo.org/3.2"
AUTH = f"{API}/auth/accesstoken"
SEARCH = f"{API}/rest-services/published-data/search"
GRANTED = ("B", "C", "T")  # 등록 공고 종류 코드: US B1·B2, EP B1, CN B·C, KR B1, JP B2 …
UTILITY = ("U", "Y")       # 실용신안(중국 U, 독일 U1 …) — 심사가 가벼워 건수 해석에 주의


MB = 1_000_000
FREE_WEEKLY_MB = 4000   # EPO OPS 무료 한도(주 4GB, 월요일 00시~일요일 24시 GMT). EPO 가 바꿀 수 있어 설정으로 더 낮춰 쓴다
HARD_FRACTION = 0.8     # 설정을 잘못 높여도 무료 한도의 80% 를 넘기지 못하게 하는 절대 상한
MIN_ROOM = 300_000      # 이만큼의 여유도 없으면 인증조차 보내지 않는다


class OPSError(RuntimeError):
    pass


class QuotaExceeded(OPSError):
    """무료 한도 보호: 한도를 넘길 것 같거나 OPS 가 한도 초과로 거부해 즉시 중단."""


class OPSQueryError(OPSError):
    """검색식 자체가 거부됨(HTTP 400)."""


class Quota:
    """받은 바이트를 주·일 단위 장부(usage)에 쌓고, 상한을 넘길 것 같으면 요청을 막는다.
    장부는 patents.json 의 usage 에 저장되어 실행 사이에 이어진다. 주는 EPO 집계와 같이 월요일(GMT)에 시작한다."""

    def __init__(self, usage: dict | None, today: date, week_cap: int, day_cap: int):
        self.u = usage if isinstance(usage, dict) else {}
        self.week_cap = min(int(week_cap), int(FREE_WEEKLY_MB * HARD_FRACTION * MB))
        self.day_cap = min(int(day_cap), self.week_cap)
        wk, dy = self.week_id(today), today.isoformat()
        if self.u.get("week") != wk:
            self.u.update(week=wk, bytes=0)
        if self.u.get("day") != dy:
            self.u.update(day=dy, day_bytes=0)
        self.u.setdefault("bytes", 0)
        self.u.setdefault("day_bytes", 0)
        self.u.update(week_cap=self.week_cap, day_cap=self.day_cap, free_week=FREE_WEEKLY_MB * MB)

    @staticmethod
    def week_id(d: date) -> str:
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"

    def add(self, n: int) -> None:
        self.u["bytes"] += n
        self.u["day_bytes"] += n

    def room(self) -> int:
        return min(self.week_cap - self.u["bytes"], self.day_cap - self.u["day_bytes"])

    def check(self, est: int) -> None:
        if self.room() < est:
            raise QuotaExceeded(
                f"무료 한도 보호 — 이번 주 {self.u['bytes'] / MB:.0f}/{self.week_cap / MB:.0f}MB, 오늘 {self.u['day_bytes'] / MB:.0f}/{self.day_cap / MB:.0f}MB. "
                "한도를 넘길 수 있어 요청을 보내지 않고 중단합니다(다음 날·다음 주에 이어서 수집)")


def listify(x):
    return x if isinstance(x, list) else [] if x is None else [x]


def val(x):
    return x.get("$") if isinstance(x, dict) else x


# ---------- 응답 해석 (관대하게) ----------
def total_count(js: dict) -> int:
    try:
        return int(js["ops:world-patent-data"]["ops:biblio-search"]["@total-result-count"])
    except (KeyError, TypeError, ValueError) as e:
        raise OPSError("예상 밖 응답 구조(@total-result-count 없음)") from e


def _search_result(js: dict) -> dict:
    return ((js.get("ops:world-patent-data") or {}).get("ops:biblio-search") or {}).get("ops:search-result") or {}


def parse_refs(js: dict | None) -> list[dict]:
    """검색 결과의 공개번호 목록 → [{country, number, kind}]."""
    out = []
    for pr in listify(_search_result(js or {}).get("ops:publication-reference")):
        try:
            d = listify(pr.get("document-id"))[0]
            out.append({"country": val(d["country"]), "number": val(d["doc-number"]), "kind": val(d.get("kind")) or ""})
        except (KeyError, IndexError, AttributeError, TypeError):
            continue
    return out


def _ymd(s) -> str:
    s = str(s or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else ""


def parse_biblio(js: dict | None) -> list[dict]:
    """biblio 검색 결과 → [{country, number, kind, date, title, applicant}] — 구조가 달라도 가능한 만큼만."""
    docs = []
    for e in listify(_search_result(js or {}).get("exchange-documents")):
        docs += listify(e.get("exchange-document")) if isinstance(e, dict) and "exchange-document" in e else [e]
    out = []
    for d in docs:
        try:
            bd = d.get("bibliographic-data") or {}
            title = ""
            for t in listify(bd.get("invention-title")):
                if isinstance(t, dict) and (t.get("@lang") in ("en", None) or not title):
                    title = val(t) or title
            pub = ""
            for did in listify((bd.get("publication-reference") or {}).get("document-id")):
                if isinstance(did, dict) and did.get("@document-id-type") == "docdb":
                    pub = _ymd(val(did.get("date")))
            who = ""
            for ap in listify(((bd.get("parties") or {}).get("applicants") or {}).get("applicant")):
                nm = val(((ap or {}).get("applicant-name") or {}).get("name"))
                if nm:
                    who = nm
                    break
            out.append({"country": d.get("@country", ""), "number": d.get("@doc-number", ""), "kind": d.get("@kind", ""),
                        "date": pub, "title": " ".join(str(title).split())[:160], "applicant": str(who).title()[:60]})
        except (AttributeError, TypeError):
            continue
    return out


def quality(refs: list[dict], total: int, home: str) -> dict | None:
    n = len(refs)
    if not n:
        return None
    pct = lambda k: round(sum(1 for r in refs if k(r)) / n, 2)  # noqa: E731
    return {"total": total, "sample": n, "granted": pct(lambda r: r["kind"][:1] in GRANTED),
            "utility": pct(lambda r: r["kind"][:1] in UTILITY), "intl": pct(lambda r: r["country"] != home)}


# ---------- OPS 클라이언트 ----------
class OPS:
    def __init__(self, key: str, secret: str, client: httpx.Client | None = None, pause: float = 7.0, sleep=time.sleep,
                 quota: Quota | None = None):
        self.key, self.secret = key, secret
        self.quota = quota
        self.client = client or httpx.Client(timeout=60)
        self.pause, self.sleep = pause, sleep
        self.token, self.exp = None, 0.0
        self.searches = 0
        self.sep = " "  # pd within "A B" — 공백이 거부되면 쉼표로 자동 전환
        self._last = 0.0

    def _auth(self) -> None:
        if self.token and time.time() < self.exp - 60:
            return
        if self.quota:
            self.quota.check(5_000)
        basic = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        r = self.client.post(AUTH, headers={"Authorization": f"Basic {basic}"}, data={"grant_type": "client_credentials"})
        if self.quota:
            self.quota.add(len(r.content))
        if r.status_code >= 400:
            raise OPSError(f"인증 실패 HTTP {r.status_code} — 키·시크릿을 확인하세요")
        js = r.json()
        self.token, self.exp = js["access_token"], time.time() + float(js.get("expires_in", 1200))

    def search(self, q: str, rng: str = "1-1", constituent: str = "", est: int = 30_000) -> tuple[int, dict | None]:
        """(전체 건수, 응답 JSON). 결과가 없으면 OPS 는 404 를 주므로 (0, None)."""
        url = SEARCH + (f"/{constituent}" if constituent else "")
        for attempt in range(4):
            wait = self.pause - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            if self.quota:
                self.quota.check(est)  # 응답이 최대 est 바이트라고 가정해도 한도를 넘지 않을 때만 보낸다
            self._auth()
            self._last = time.monotonic()
            self.searches += 1
            r = self.client.get(url, params={"q": q, "Range": rng}, headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
            if self.quota:
                self.quota.add(len(r.content))
            head = r.text[:300]
            reason = f"{r.headers.get('X-Rejection-Reason', '')} {head}".lower()
            if r.status_code in (403, 429) and "quota" in reason:
                raise QuotaExceeded(f"OPS 가 한도 초과로 거부했습니다({r.headers.get('X-Rejection-Reason', '') or head[:60]}) — 재시도 없이 중단")
            if r.status_code == 404:
                return 0, None
            if r.status_code in (400, 401) and "token" in head.lower():
                self.token = None
                continue
            if r.status_code in (403, 429, 503):  # 한도 초과·혼잡 — 잠시 쉬었다가 재시도
                self.sleep(30 * (attempt + 1))
                continue
            if r.status_code == 400:
                raise OPSQueryError(f"{q} → {head}")
            if r.status_code >= 400:
                raise OPSError(f"HTTP {r.status_code}: {head}")
            js = r.json()
            return total_count(js), js
        raise OPSError(f"한도 초과 또는 토큰 오류로 중단: {q}")

    def window(self, start: date, end: date) -> str:
        return f'pd within "{start:%Y%m%d}{self.sep}{end:%Y%m%d}"'

    def query(self, base: str, start: date, end: date, rng: str = "1-1", constituent: str = "", est: int = 30_000) -> tuple[int, dict | None]:
        orig = self.sep
        for attempt in range(2):
            try:
                return self.search(f"({base}) and {self.window(start, end)}", rng, constituent, est)
            except OPSQueryError:
                if attempt:
                    self.sep = orig
                    raise
                self.sep = "," if self.sep == " " else " "  # 날짜 구분자를 바꿔 한 번 더
        raise OPSError("unreachable")


# ---------- 검색식 ----------
def pa_expr(app: dict) -> str:
    terms = [f'pa="{p}"' for p in app["pa"]]
    return terms[0] if len(terms) == 1 else "(" + " or ".join(terms) + ")"


def base_expr(app: dict) -> str:
    return pa_expr(app) + (" and cpc=B25J" if app.get("scope") == "robot" else "")


def layer_expr(app: dict, layer: dict) -> str:
    e = f"{pa_expr(app)} and {layer['cpc']}"
    if app.get("scope") == "robot" and "B25J" not in layer["cpc"]:
        e += " and cpc=B25J"  # 대기업의 비로봇 특허(가전·자동차 기어 등)를 걷어낸다
    return e


def cells_of(app: dict, cfg: dict) -> list[tuple[str, str]]:
    """(층 id, 검색식) — 'total' 은 로봇 전체(B25J)."""
    only = app.get("only")
    out = [(l["id"], layer_expr(app, l)) for l in cfg["layers"] if not only or l["id"] in only]
    if app.get("scope") == "robot":
        out.insert(0, ("total", f"{pa_expr(app)} and {cfg['total']['cpc']}"))
    return out


def shift_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # 2/29
        return d.replace(year=d.year - n, day=28)


def periods(today: date, years: int) -> dict:
    a_start = shift_years(today, years) + timedelta(days=1)
    b_end = a_start - timedelta(days=1)
    return {"a": (a_start, today), "b": (shift_years(b_end, years) + timedelta(days=1), b_end)}


# ---------- 수집 ----------
def age_days(stamp: str | None, today: date) -> int:
    try:
        return (today - date.fromisoformat(stamp)).days
    except (TypeError, ValueError):
        return 10_000


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("enabled"))


def refresh_recent(ops: OPS, app: dict, cfg: dict, data: dict, today: date) -> None:
    """12개월 품질 지표 + 최근 60일 건수 — 기업(kind=company)만, 2회 검색.
    publish_records=true 일 때만 개별 특허 레코드(번호·제목·출원인)를 저장한다(기본은 건수·비율만)."""
    bud = cfg["budget"]
    rec = dict(data["applicants"].get(app["id"], {}))  # 검색이 끝까지 성공했을 때만 저장(중간 실패 시 빈 항목을 남기지 않는다)
    base = base_expr(app)
    q_start = today - timedelta(days=int(bud["quality_months"]) * 30)
    total, js = ops.query(base, q_start, today, "1-100", est=300_000)
    refs = parse_refs(js)
    rec["quality"] = quality(refs, total, app.get("home", ""))
    r_start = today - timedelta(days=int(bud["recent_days"]))
    if cfg.get("publish_records"):
        n, js2 = ops.query(base, r_start, today, "1-8", "biblio", est=300_000)
        items = parse_biblio(js2)
        if not items and js2:  # biblio 파싱이 안 되면 번호만이라도
            items = [{**r, "date": "", "title": "", "applicant": ""} for r in parse_refs(js2)]
    else:
        n, items = ops.query(base, r_start, today)[0], []  # 건수만
    rec["recent"] = items
    rec["recent_total"] = n
    rec["name"], rec["kind"], rec["company"], rec["home"] = app["name"], app["kind"], app.get("company"), app.get("home")
    rec["fetched"] = today.isoformat()
    data["applicants"][app["id"]] = rec


def collect(cfg: dict, data: dict, ops: OPS, today: date, max_searches: int | None = None, deadline: float | None = None) -> dict:
    """data 를 제자리에서 갱신. 예산·시간을 넘기면 멈추고 남은 건 다음 실행으로 넘긴다."""
    bud = cfg["budget"]
    cap = max_searches or int(bud["max_searches"])
    per = periods(today, int(cfg["windows"]["years"]))
    ttl_cell, ttl_recent = int(bud["cell_ttl_days"]), int(bud["recent_ttl_days"])
    out_of_time = lambda: deadline is not None and time.monotonic() > deadline  # noqa: E731
    data.setdefault("applicants", {})
    data.setdefault("cells", {})
    data["windows"] = {k: [v[0].isoformat(), v[1].isoformat()] for k, v in per.items()}
    warnings: list[str] = []
    try:
        if ops.quota and ops.quota.room() < MIN_ROOM:
            ops.quota.check(MIN_ROOM)  # 여유가 없으면 인증도 보내지 않고 QuotaExceeded
        for app in cfg["applicants"]:  # 1) 최근 공개 + 품질 (오래된 것만)
            if app["kind"] != "company":
                continue
            if age_days(data["applicants"].get(app["id"], {}).get("fetched"), today) < ttl_recent:
                continue
            if ops.searches + 2 > cap or out_of_time():
                break
            try:
                refresh_recent(ops, app, cfg, data, today)
            except OPSQueryError as e:
                warnings.append(f"{app['name']}: 최근 공개 검색 거부 — {e}"[:200])
        todo = []  # 2) 층별 건수: 빈 셀 먼저, 그다음 오래된 순
        for app in cfg["applicants"]:
            for lid, expr in cells_of(app, cfg):
                c = data["cells"].get(f"{app['id']}|{lid}")
                age = age_days((c or {}).get("fetched"), today)
                if c is None or age >= ttl_cell:
                    todo.append((-1 if c is None else 0, -age, app, lid, expr))
        todo.sort(key=lambda t: (t[0], t[1]))
        done = 0
        for _, _, app, lid, expr in todo:
            if ops.searches + 2 > cap or out_of_time():
                break
            key = f"{app['id']}|{lid}"
            cell = {"fetched": today.isoformat(), "ra": per["a"][0].isoformat() + "~" + per["a"][1].isoformat(),
                    "rb": per["b"][0].isoformat() + "~" + per["b"][1].isoformat()}
            try:
                cell["a"] = ops.query(expr, *per["a"])[0]
                cell["b"] = ops.query(expr, *per["b"])[0]
            except OPSQueryError as e:
                cell.update(a=None, b=None, error=str(e)[:160])
                warnings.append(f"{key}: 검색식 거부")
            data["cells"][key] = cell
            done += 1
        left = max(0, len(todo) - done)
        data["status"] = {"cells": sum(1 for c in data["cells"].values() if c.get("a") is not None),
                          "expected": sum(len(cells_of(a, cfg)) for a in cfg["applicants"]), "pending": left, "searches": ops.searches}
    except OPSError as e:  # 인증·한도 — 지금까지의 결과는 보존하고 중단
        warnings.append(f"수집 중단: {e}"[:200])
        log.warning("patents stopped: %s", e)
    data["warnings"] = warnings
    data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    data["source"] = "EPO OPS(DOCDB) — 공개 기준, 공개까지 약 18개월 지연"
    return data


# ---------- 점검 ----------
def probe(ops: OPS, today: date) -> int:
    """키·검색식·응답 구조를 점검한다. 저장하지 않고 건수와 구조만 출력."""
    a = periods(today, 3)["a"]
    tests = [
        ("로봇 전체 · Boston Dynamics", 'pa="boston dynamics" and cpc=B25J'),
        ("하모닉 감속기 · Harmonic Drive", 'pa="harmonic drive" and cpc=F16H49'),
        ("보행 · UBTech", 'pa="ubtech" and cpc=B62D57/032'),
        ("다지 손 · Tesla", 'pa="tesla" and cpc=B25J15/0009'),
        ("롤러스크류 · Schaeffler", 'pa="schaeffler" and cpc=F16H25/22'),
        ("AND 두 분류 · Samsung", 'pa="samsung electronics" and cpc=B25J9/16 and cpc=G06N'),
    ]
    bad = 0
    for label, q in tests:
        try:
            n, _ = ops.query(q, *a)
            print(f"  {label:32s} 최근 3년 {n:>6,}건   [날짜 구분자 {'공백' if ops.sep == ' ' else '쉼표'}]")
            bad += n == 0
        except OPSError as e:
            print(f"  {label:32s} 오류: {e}")
            bad += 1
    try:
        n, js = ops.query('pa="boston dynamics" and cpc=B25J', today - timedelta(days=365), today, "1-3", "biblio", est=300_000)
        items = parse_biblio(js)
        print(f"  biblio 구조 점검: 최근 1년 {n}건 중 해석 {len(items)}건")
        for it in items[:3]:
            print("   -", it["date"], it["country"] + it["number"] + it["kind"], "|", it["title"][:70], "|", it["applicant"])
        if js and not items:
            print("  ! 해석 실패 — 응답 키:", list((_search_result(js) or {}).keys())[:6])
    except OPSError as e:
        print("  biblio 점검 오류:", e)
        bad += 1
    used = f", 받은 데이터 약 {ops.quota.u['bytes'] / MB:.2f}MB" if ops.quota else ""
    print(f"점검 완료: 검색 {ops.searches}회{used}, 문제 {bad}건")
    return 1 if bad >= len(tests) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--max-searches", type=int, default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = read_json(SRC / "patents_cfg.json", {})
    if not args.probe and not enabled(cfg):
        log.info("EPO 특허 집계는 기본 꺼져 있습니다(data/patents_cfg.json 의 enabled) — 건너뜁니다")
        return 0
    today = datetime.now(timezone.utc).date()
    key, secret = os.environ.get("EPO_OPS_KEY", "").strip(), os.environ.get("EPO_OPS_SECRET", "").strip()
    if not key or not secret:
        log.warning("EPO_OPS_KEY / EPO_OPS_SECRET 이 없어 특허 수집을 건너뜁니다")
        return 0
    bud = cfg["budget"]
    data = read_json(OUT / "patents.json", {})
    quota = Quota(data.setdefault("usage", {}) if not args.probe else {}, today, int(bud["weekly_cap_mb"]) * MB, int(bud["daily_cap_mb"]) * MB)
    ops = OPS(key, secret, pause=float(bud["pause_seconds"]), quota=quota)
    if args.probe:
        return probe(ops, today)
    deadline = time.monotonic() + 60 * float(cfg["budget"]["max_minutes"])
    try:
        collect(cfg, data, ops, today, args.max_searches, deadline)
    finally:
        if data.get("cells") or data.get("applicants") or (data.get("usage") or {}).get("bytes"):  # 데이터가 없어도 한도 장부는 남긴다
            write_json(OUT / "patents.json", data)
    st, u = data.get("status", {}), data.get("usage", {})
    print(f"patents.json: 셀 {st.get('cells', 0)}/{st.get('expected', 0)}, 남은 {st.get('pending', 0)}, 검색 {st.get('searches', 0)}회, 경고 {len(data.get('warnings', []))}"
          f" | 데이터 이번 주 {u.get('bytes', 0) / MB:.1f}/{u.get('week_cap', 0) / MB:.0f}MB (무료 {FREE_WEEKLY_MB}MB), 오늘 {u.get('day_bytes', 0) / MB:.1f}/{u.get('day_cap', 0) / MB:.0f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
