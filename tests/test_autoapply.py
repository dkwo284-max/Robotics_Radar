import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import autoapply as aa  # noqa: E402

CO = [{"id": "unitree", "name": "Unitree", "name_ko": "유니트리", "valuation": {"v": 9000, "as_of": "2025-06", "kind": "reported"}},
      {"id": "neura", "name": "Neura Robotics", "name_ko": "뉴라 로보틱스"}]
NEWS = [{"id": "n1", "title": "Unitree market cap hits 300bn yuan", "title_ko": "유니트리 시총 3,000억 위안", "summary_ko": "s1"},
        {"id": "n2", "title": "HK robot stocks surge", "title_ko": "홍콩 로봇주 급등 속 유니트리 시총 3,000억", "summary_ko": "s2"},
        {"id": "n3", "title": "SoftBank bets $5.4bn on Swiss robotics", "title_ko": "소프트뱅크, 스위스 로보틱스에 54억 달러", "summary_ko": ""},
        {"id": "n4", "title": "SoftBank to buy ABB robotics", "title_ko": "소프트뱅크, 스위스 로보틱스에 7조 투자", "summary_ko": ""}]
P = lambda cid, f, v, nid, as_of="2026-11", d="2026-11-10": {"company": cid, "field": f, "proposed": v, "as_of": as_of, "date": d, "title": next(n["title_ko"] for n in NEWS if n["id"] == nid), "url": f"https://x/{nid}", "news_id": nid}  # noqa: E731
PROPS = [P("unitree", "valuation", 42253.5, "n1"), P("unitree", "valuation", 38461.5, "n2"), P("neura", "funding_total", 5400, "n3"), P("neura", "funding_total", 5142, "n4")]


class LLM:
    enabled = True

    def __init__(self, ok=True):
        self.ok, self.calls = ok, 0

    def json_call(self, system, user, schema, max_tokens=0):
        self.calls += 1
        return {"items": [{"key": k.split("] ")[1], "ok": self.ok, "reason": "정의와 일치"} for k in [ln for ln in user.split("\n") if ln.startswith("[key]")]]}


def test_candidates_need_two_agreeing_articles_naming_the_company():
    c = aa.candidates(PROPS, CO, NEWS)
    assert [x["company"] for x in c] == ["unitree"]                       # 뉴라는 제목에 회사 이름이 없어 제외(다른 회사 숫자)
    assert c[0]["value"] == 42254 and c[0]["as_of"] == "2026-11" and len(c[0]["sources"]) == 2
    assert aa.candidates(PROPS[:1], CO, NEWS) == []                        # 기사 1건으로는 반영하지 않는다
    assert aa.candidates([P("unitree", "valuation", 42253.5, "n1"), P("unitree", "valuation", 20000, "n2")], CO, NEWS) == []   # 값이 서로 다르다
    old = [{**p, "as_of": "2025-03"} for p in PROPS[:2]]
    assert aa.candidates([{**p, "date": "2025-03-10"} for p in old], CO, NEWS) == []   # 지금 값(2025-06)보다 새롭지 않다


def test_run_applies_only_after_ai_confirms_and_never_asks_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, "OVERLAY", tmp_path / "auto.json")
    news = {"proposals": PROPS, "items": NEWS}

    class Off:
        enabled = False
    assert aa.run(CO, news, Off(), "2026-11-12") == 0 and not (tmp_path / "auto.json").exists()   # AI 없으면 미룬다
    no = LLM(ok=False)
    assert aa.run(CO, news, no, "2026-11-12") == 0 and no.calls == 1
    assert aa.run(CO, news, LLM(), "2026-11-13") == 0                       # 한 번 거절된 후보는 다시 묻지 않는다
    (tmp_path / "auto.json").unlink()
    yes = LLM()
    assert aa.run(CO, news, yes, "2026-11-12") == 1
    ov = aa.read_json(tmp_path / "auto.json", {})
    a = ov["applied"]["unitree|valuation"]
    assert a["v"] == 42254 and a["auto"]["prev"] == {"v": 9000, "as_of": "2025-06"} and len(a["auto"]["sources"]) == 2
    cos = [dict(c) for c in CO]
    used = aa.apply_overlay(cos, ov)
    assert cos[0]["valuation"]["v"] == 42254 and cos[0]["valuation"]["kind"] == "reported" and used[0]["field"] == "valuation"
    newer = [{**CO[0], "valuation": {"v": 50000, "as_of": "2026-12", "kind": "official"}}]
    assert aa.apply_overlay(newer, ov) == [] and newer[0]["valuation"]["v"] == 50000   # 손으로 더 새 값을 넣으면 그 값이 이긴다
