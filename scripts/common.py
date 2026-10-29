"""공통: 경로, 설정, 로그, JSON 읽기·쓰기."""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data"          # 큐레이션 기준값 + 점수 이력
OUT = ROOT / "web" / "data"  # 화면이 읽는 파일 (자동 수집 결과 포함, 봇이 커밋)
log = logging.getLogger("radar")


CUMULATIVE = {"cum_units", "funding_total"}  # 누적값 — 줄어들 수 없음
LIMITS = {"USD_M": 200_000, "units": 5_000_000}


def plausible(field: str, cur, new) -> bool:
    """AI 추출 수치를 '검증 대기'로 올릴 만한지: 기준값과 10% 넘게 다르되, 단위 착오로 보이는 값은 거른다."""
    if not isinstance(new, (int, float)) or new <= 0:
        return False
    unit = "units" if field in ("cum_units", "capacity", "target_2026") else "USD" if field == "price" else "USD_M"
    if unit in LIMITS and new > LIMITS[unit] or unit == "USD" and not 1_000 <= new <= 1_000_000:
        return False
    if not cur:
        return True
    if abs(new - cur) / cur <= 0.10:
        return False  # 이미 같은 값
    if field in CUMULATIVE and new < cur:
        return False
    return 0.2 <= new / cur <= 5


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def finite(obj):
    """JSON 에 NaN·Infinity 가 들어가면 브라우저가 못 읽으므로 None 으로."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: finite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [finite(v) for v in obj]
    return obj


def write_json(path: Path, data, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sep = None if indent else (",", ":")
    path.write_text(json.dumps(finite(data), ensure_ascii=False, indent=indent, separators=sep, allow_nan=False), encoding="utf-8")
