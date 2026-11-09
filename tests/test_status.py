import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import status  # noqa: E402


def test_build_status_reads_pending_and_ai_usage(tmp_path):
    (tmp_path / "news.json").write_text(json.dumps({"generated_at": "2026-11-09T00:00+00:00", "ai_ok_day": "2026-11-09",
                                                      "items": [{"ai": True}, {"ai": False}], "warnings": ["x"]}), encoding="utf-8")
    (tmp_path / "prices.json").write_text(json.dumps({"generated_at": "2026-11-09T00:00+00:00", "quotes": {"a": {}, "b": {}}}), encoding="utf-8")
    (tmp_path / "ai-usage.json").write_text(json.dumps({"cap": 3, "days": {}}), encoding="utf-8")
    st = status.build_status(tmp_path)
    assert st["news"]["items"] == 2 and st["news"]["pending"] == 1 and st["news"]["warnings"] == ["x"]
    assert st["prices"]["symbols"] == 2
    assert st["ai"]["cap"] == 3
