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
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        lc = cfg.get("llm", {})
        self.models = list(lc.get("models", ["gemini-flash-latest"]))
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
        for model in self.models:
            for attempt in range(2):
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
