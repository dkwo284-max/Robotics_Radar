import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from llm import Gemini  # noqa: E402

CFG = {"llm": {"models": ["lite", "flash"], "models_production": ["flash", "lite"], "max_requests_per_run": 2}}


def test_profile_selects_models(monkeypatch):
    monkeypatch.delenv("AI_PROFILE", raising=False)
    assert Gemini(CFG).models == ["lite", "flash"]
    monkeypatch.setenv("AI_PROFILE", "test")
    assert Gemini(CFG).models == ["lite", "flash"]
    monkeypatch.setenv("AI_PROFILE", "production")
    assert Gemini(CFG).models == ["flash", "lite"]
    assert Gemini({"llm": {"models": ["lite"]}}).models == ["lite"]   # production 목록이 없으면 기본 목록 그대로
