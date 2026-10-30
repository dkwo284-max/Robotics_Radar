"""Gemini 무료 등급 호출 (JSON 응답). 키는 환경변수 GEMINI_API_KEY 에서만 읽는다."""
from __future__ import annotations

import json
import os
import time

import httpx

from common import log

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    pass


class Gemini:
    def __init__(self, cfg: dict, client: httpx.Client | None = None):
        lc = cfg.get("llm", {})
        # llm.enabled=false 면 키가 있어도 AI 를 전혀 쓰지 않는다(완전 무료 운영의 비상 스위치)
        self.key = os.environ.get("GEMINI_API_KEY", "").strip() if lc.get("enabled", True) else ""
        self.max_http = int(lc.get("max_http_attempts", 3))  # 요청 1건당 실제 HTTP 호출 상한(모델 바꿔 재시도·재시도 합산)
        # 정해진 시각의 실제 배포 실행(AI_PROFILE=production)은 models_production(Flash 우선), 수동·테스트는 models(Flash-Lite 우선)
        production = os.environ.get("AI_PROFILE", "").strip().lower() == "production"
        self.models = list((lc.get("models_production") if production else None) or lc.get("models", ["gemini-flash-latest"]))
        self.max_requests = int(lc.get("max_requests_per_run", 1))
        self.client = client or httpx.Client(timeout=float(lc.get("timeout_seconds", 240)))
        self.requests = 0

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def json_call(self, system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict:
        if not self.key:
            raise LLMError("GEMINI_API_KEY not set")
        if self.requests >= self.max_requests:
            raise LLMError("max_requests_per_run reached")
        self.requests += 1
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "maxOutputTokens": max_tokens},
        }
        last = None
        http = 0
        for model in self.models:
            for attempt in range(2):
                if http >= self.max_http:
                    raise LLMError(last or "max_http_attempts reached")
                http += 1
                try:
                    r = self.client.post(URL.format(model=model), json=body, headers={"x-goog-api-key": self.key})
                except httpx.TransportError as e:
                    last = f"{model}: {e}"
                    time.sleep(10)
                    continue
                if r.status_code == 404:
                    last = f"{model}: 404"
                    break  # 없는 모델 → 다음 후보
                if r.status_code in (429, 500, 503) and attempt == 0:
                    time.sleep(30 if r.status_code == 429 else 15)
                    continue
                if r.status_code >= 400:
                    last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                    break
                try:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    log.info("gemini %s ok", model)
                    return json.loads(text)
                except Exception as e:  # noqa: BLE001
                    last = f"{model}: bad response {e}"
                    break
        raise LLMError(last or "all models failed")
