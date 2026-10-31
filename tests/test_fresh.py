import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fresh import is_fresh, latest_slot  # noqa: E402


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_latest_slot_is_most_recent_1910():
    assert latest_slot(utc(2026, 10, 30, 20, 40)) == utc(2026, 10, 30, 19, 10)
    assert latest_slot(utc(2026, 10, 31, 0, 0)) == utc(2026, 10, 30, 19, 10)      # 자정을 넘어도 전날 19:10
    assert latest_slot(utc(2026, 10, 31, 19, 9)) == utc(2026, 10, 30, 19, 10)


def test_fallback_runs_skip_when_already_updated():
    gen = "2026-10-30T22:55+00:00"
    assert is_fresh(gen, utc(2026, 10, 30, 23, 40))      # 같은 날 예비 실행
    assert is_fresh(gen, utc(2026, 10, 31, 0, 0))        # 자정 넘어 늦게 시작한 예비 실행 (이전엔 여기서 다시 수집했다)
    assert is_fresh(gen, utc(2026, 10, 31, 2, 41))


def test_runs_when_stale():
    assert not is_fresh("2026-10-29T23:14+00:00", utc(2026, 10, 30, 19, 30))     # 어제 갱신분 → 오늘 정기 실행은 진행
    assert not is_fresh("2026-10-30T18:00+00:00", utc(2026, 10, 30, 20, 40))     # 19:10 전 갱신 → 예비 실행이 진행
    assert not is_fresh("", utc(2026, 10, 30, 20, 40)) and not is_fresh("garbage", utc(2026, 10, 30, 20, 40))
