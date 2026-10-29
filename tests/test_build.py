import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build  # noqa: E402


def test_data_has_no_warnings():
    out, warnings = build.build()
    assert warnings == []
    assert len(out["companies"]) == 27


def test_tier_thresholds():
    assert build.tier_of(70) == 1
    assert build.tier_of(69) == 2
    assert build.tier_of(50) == 2
    assert build.tier_of(49) == 3


def test_attractiveness_only_for_body_layer():
    out, _ = build.build()
    for c in out["companies"]:
        if c["group"] == "brain":
            assert c["calc"]["attract"] is None
        else:
            s = c["scores"]
            assert c["calc"]["attract"] == s["scale"][0] + s["open"][0] + s["geo"][0] + s["capital"][0]


def test_efficiency_needs_units():
    c = {"valuation": {"v": 39000}, "cum_units": {"v": 1000}, "funding_total": {"v": None}}
    assert build.efficiency(c) == {"units": 1000, "val_per_unit": 39_000_000, "raised_per_unit": None}
    assert build.efficiency({"valuation": {"v": 100}})["val_per_unit"] is None


def test_bom_asp_matches_share():
    out, _ = build.build()
    bom = out["bom"]
    reducer = next(i for i in bom["items"] if i["id"] == "reducer")
    assert reducer["asp"] == round(bom["unit_bom_2026"] * reducer["share"] / reducer["qty"])
    assert next(i for i in bom["items"] if i.get("module"))["asp"] is None


def test_months_back():
    assert build.months_back("2026-10-29", "2025-11") == 11
    assert build.months_back("2026-10-29", "2025-10") == 12


def test_owner_basis_raises_only_axes_where_the_subsidiary_scores_higher():
    strategy = {"countries": {"axes": [{"id": "ai", "label": "AI"}, {"id": "cost", "label": "원가"}, {"id": "policy", "label": "정책"}],
                              "items": [{"id": "KR", "scores": {"ai": 4, "cost": 5, "policy": 7}}],
                              "owner_basis": {"KR": {"companies": ["x"], "weight": 0.3, "axis_map": {"ai": "tech", "cost": "scale"}}}}}
    companies = [{"id": "x", "name_ko": "엑스", "scores": {"tech": [27, ""], "scale": [6, ""]}}]
    warnings: list[str] = []
    build.owner_basis(strategy, companies, warnings)
    owner = strategy["countries"]["items"][0]["owner"]
    assert owner["scores"] == {"ai": 6, "cost": 5, "policy": 7}  # 9.0 환산 → 4+(9-4)*0.3=5.5→6, 원가는 내리지 않음, 매핑 없는 축은 그대로
    assert [a["axis"] for a in owner["adjust"]] == ["ai"] and not warnings
