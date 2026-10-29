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
