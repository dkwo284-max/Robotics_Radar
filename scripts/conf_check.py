"""학회·전시회 링크 주간 점검 (AI 미사용).

data/conferences.json 의 공식 페이지가 살아 있는지만 확인해 web/data/conf_status.json 에 남긴다.
매일 워크플로에서 불리지만 마지막 점검이 6일 이내면 아무것도 하지 않는다(--force 로 강제).
날짜가 바뀌었는지는 판단하지 않는다 — 링크가 죽었거나 지난 행사가 남아 있으면 화면에 '점검 필요'로 표시될 뿐이고,
큐레이션 수정은 사람이 한다.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone

import httpx

from common import OUT, SRC, read_json, write_json

UA = "RoboticsRadar/1.0 (personal dashboard; weekly link check)"
STATUS = OUT / "conf_status.json"


def due(prev: dict, today: date) -> bool:
    try:
        return (today - date.fromisoformat(prev.get("checked", ""))).days >= 6
    except ValueError:
        return True


def check(items: list[dict], client: httpx.Client) -> dict:
    out = {}
    for it in items:
        try:
            r = client.get(it["url"])
            code = r.status_code
        except httpx.HTTPError as e:  # noqa: PERF203
            code = 0
            out[it["id"]] = {"ok": False, "code": code, "err": type(e).__name__}
            continue
        # 403/429 는 봇 차단일 수 있어 '확인 불가'로 둔다(죽은 링크로 단정하지 않음)
        out[it["id"]] = {"ok": code < 400, "code": code, **({"blocked": True} if code in (401, 403, 429) else {})}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    today = datetime.now(timezone.utc).date()
    prev = read_json(STATUS, {})
    if not args.force and not due(prev, today):
        print("conf_check: 최근 점검", prev.get("checked"), "— 건너뜀")
        return 0
    items = read_json(SRC / "conferences.json", {"items": []})["items"]
    horizon = (today + timedelta(days=400)).isoformat()
    live = [i for i in items if i["end"] >= today.isoformat() and i["start"] <= horizon]
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA}) as c:
        res = check(live, c)
    write_json(STATUS, {"checked": today.isoformat(), "items": res})
    bad = [k for k, v in res.items() if not v["ok"] and not v.get("blocked")]
    print(f"conf_check: {len(res)}건 점검, 링크 문제 {len(bad)}건 {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
